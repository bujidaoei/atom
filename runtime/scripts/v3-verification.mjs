import { createHash, randomUUID } from 'node:crypto';
import { readdir, readFile, rename, rm, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { assertEvidenceRecord, isPassingEvidence } from './v3-evidence.mjs';

export const V3_VERIFICATION_SCHEMA_VERSION = 'workdude.v3.verification/v1';
export const V3_REQUIRED_RELEASE_GATES = [
  'test',
  'build',
  'real-infrastructure',
  'response-e2e',
  'visual',
  'secret-scan',
  'deployment',
  'release',
];

const claimKinds = ['requirements', 'successCriteria', 'acceptanceScenarios', 'referenceStates'];
const sensitiveKey = /password|passphrase|secret|api.?key|access.?key|token|authorization|credential/iu;
const sensitiveValue = /\b(?:sk-[A-Za-z0-9_-]{16,}|AKID[A-Za-z0-9]{12,}|Bearer\s+\S{16,})\b/iu;

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonical(value[key])]),
  );
}

function canonicalJson(value, spacing = 0) {
  return JSON.stringify(canonical(value), null, spacing);
}

export function parseV3SpecificationInventory(source) {
  const requirements = [...source.matchAll(/\bFR-\d{3}\b/gu)].map(([value]) => value);
  const successCriteria = [...source.matchAll(/\bSC-\d{3}\b/gu)].map(([value]) => value);
  const acceptanceScenarios = [];
  let story;
  let inAcceptance = false;
  let index = 0;
  for (const line of source.split(/\r?\n/u)) {
    const storyMatch = /^### User Story (\d+)\b/u.exec(line);
    if (storyMatch) {
      story = Number(storyMatch[1]);
      inAcceptance = false;
      index = 0;
      continue;
    }
    if (/^\*\*Acceptance Scenarios\*\*:/u.test(line)) {
      inAcceptance = true;
      continue;
    }
    if (inAcceptance && /^###? /u.test(line)) inAcceptance = false;
    if (inAcceptance && /^\d+\. \*\*Given\*\*/u.test(line) && story) {
      index += 1;
      acceptanceScenarios.push(`US${story}/AC${index}`);
    }
  }
  return {
    requirements: [...new Set(requirements)].sort(),
    successCriteria: [...new Set(successCriteria)].sort(),
    acceptanceScenarios,
  };
}

export function parseV3ReferenceStateIds(source) {
  return [...source.matchAll(/^\s*id: '([^']+)'/gmu)].map(([, id]) => id).sort();
}

export function parseOpenV3Tasks(source) {
  return [...source.matchAll(/^- \[ \] (T\d{3})\b.*$/gmu)].map(([line, id]) => ({ id, line }));
}

function sensitivePaths(value, path = '$', findings = []) {
  if (typeof value === 'string') {
    if (sensitiveValue.test(value)) findings.push(path);
    return findings;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => sensitivePaths(item, `${path}[${index}]`, findings));
    return findings;
  }
  if (!value || typeof value !== 'object') return findings;
  for (const [key, item] of Object.entries(value)) {
    const next = `${path}.${key}`;
    if (sensitiveKey.test(key)) findings.push(next);
    sensitivePaths(item, next, findings);
  }
  return findings;
}

function validateReleaseIdentity(release, revision) {
  const errors = [];
  if (!release || typeof release !== 'object') return ['release identity is required'];
  if (sensitivePaths(release).length) errors.push('release identity contains sensitive fields or values');
  const allowed = {
    root: new Set(['repository', 'revision', 'deployment', 'desktop']),
    deployment: new Set(['releaseId', 'revision', 'status']),
    desktop: new Set(['version', 'artifactSha256', 'signingStatus']),
  };
  const unexpectedRoot = Object.keys(release).filter((key) => !allowed.root.has(key));
  const unexpectedDeployment = Object.keys(release.deployment ?? {}).filter(
    (key) => !allowed.deployment.has(key),
  );
  const unexpectedDesktop = Object.keys(release.desktop ?? {}).filter((key) => !allowed.desktop.has(key));
  if (unexpectedRoot.length || unexpectedDeployment.length || unexpectedDesktop.length) {
    errors.push('release identity contains non-redacted fields outside the allowlist');
  }
  if (typeof release.repository !== 'string' || !release.repository.trim()) {
    errors.push('release repository identity is required');
  }
  if (release.revision !== revision) errors.push('release revision does not match evidence revision');
  if (
    typeof release.deployment?.releaseId !== 'string' ||
    !release.deployment.releaseId.trim() ||
    release.deployment?.revision !== revision ||
    release.deployment?.status !== 'passed'
  ) {
    errors.push('deployment identity must pass at the evidence revision');
  }
  if (typeof release.desktop?.version !== 'string' || !release.desktop.version.trim()) {
    errors.push('desktop version is required');
  }
  if (!/^[0-9a-f]{64}$/u.test(release.desktop?.artifactSha256 ?? '')) {
    errors.push('desktop artifact SHA-256 is required');
  }
  if (!['signed', 'test-only'].includes(release.desktop?.signingStatus)) {
    errors.push('desktop signing status must be signed or test-only');
  }
  return errors;
}

function claimCoverage(records, expected) {
  return Object.fromEntries(
    claimKinds.map((kind) => {
      const rows = expected[kind].map((id) => ({
        id,
        gateIds: records.filter((record) => record.claims[kind].includes(id)).map(({ gateId }) => gateId),
      }));
      return [kind, rows];
    }),
  );
}

export function evaluateV3Verification({
  records,
  specSource,
  taskSource,
  referenceSource,
  release,
  requiredGateIds = V3_REQUIRED_RELEASE_GATES,
  generatedAt = new Date().toISOString(),
}) {
  const errors = [];
  const normalized = records.map((record) => assertEvidenceRecord(record));
  const duplicateGateIds = normalized
    .map(({ gateId }) => gateId)
    .filter((gateId, index, all) => all.indexOf(gateId) !== index);
  if (duplicateGateIds.length)
    errors.push(`duplicate evidence gates: ${[...new Set(duplicateGateIds)].join(', ')}`);
  const byGate = new Map(normalized.map((record) => [record.gateId, record]));
  const missingGates = requiredGateIds.filter((gateId) => !byGate.has(gateId));
  if (missingGates.length) errors.push(`missing required gates: ${missingGates.join(', ')}`);
  const nonPassing = normalized.filter((record) => !isPassingEvidence(record)).map(({ gateId }) => gateId);
  if (nonPassing.length) errors.push(`non-passing gates: ${nonPassing.join(', ')}`);
  const revisions = [...new Set(normalized.map(({ source }) => source.revision))];
  if (revisions.length !== 1) errors.push('evidence records do not share one source revision');
  const revision = revisions[0] ?? '';
  const dirty = normalized.filter(({ source }) => source.dirty).map(({ gateId }) => gateId);
  if (dirty.length) errors.push(`dirty-source evidence is forbidden: ${dirty.join(', ')}`);

  const spec = parseV3SpecificationInventory(specSource);
  const expected = {
    requirements: spec.requirements,
    successCriteria: spec.successCriteria,
    acceptanceScenarios: spec.acceptanceScenarios,
    referenceStates: parseV3ReferenceStateIds(referenceSource),
  };
  const coverage = claimCoverage(normalized, expected);
  for (const kind of claimKinds) {
    const missing = coverage[kind].filter(({ gateIds }) => gateIds.length === 0).map(({ id }) => id);
    if (missing.length) errors.push(`uncovered ${kind}: ${missing.join(', ')}`);
  }
  const openTasks = parseOpenV3Tasks(taskSource);
  if (openTasks.length) errors.push(`open tasks: ${openTasks.map(({ id }) => id).join(', ')}`);
  errors.push(...validateReleaseIdentity(release, revision));

  const gates = normalized
    .map((record) => ({
      evidenceId: record.evidenceId,
      gateId: record.gateId,
      recordSha256: sha256(canonicalJson(record)),
      status: record.outcome.status,
      startedAt: record.timing.startedAt,
      finishedAt: record.timing.finishedAt,
      artifacts: record.artifacts,
    }))
    .sort((left, right) => left.gateId.localeCompare(right.gateId));
  const manifest = {
    schemaVersion: V3_VERIFICATION_SCHEMA_VERSION,
    generatedAt,
    source: { revision, dirty: false },
    complete: errors.length === 0,
    gates,
    coverage,
    openTasks,
    release: release ? canonical(release) : null,
  };
  return { errors, manifest };
}

export function renderV3Traceability(manifest) {
  const lines = ['# WorkDude V3 Traceability', '', `Source revision: \`${manifest.source.revision}\``, ''];
  for (const kind of claimKinds) {
    lines.push(`## ${kind}`, '', '| Claim | Passing gates |', '| --- | --- |');
    for (const row of manifest.coverage[kind]) {
      lines.push(`| ${row.id} | ${row.gateIds.map((gateId) => `\`${gateId}\``).join(', ')} |`);
    }
    lines.push('');
  }
  return `${lines.join('\n')}\n`;
}

export function renderV3Release(manifest) {
  const release = manifest.release;
  return [
    '# WorkDude V3 Release Evidence',
    '',
    `- Repository: ${release.repository}`,
    `- Revision: \`${release.revision}\``,
    `- Deployment: ${release.deployment.releaseId} (${release.deployment.status})`,
    `- Desktop version: ${release.desktop.version}`,
    `- Desktop SHA-256: \`${release.desktop.artifactSha256}\``,
    `- Signing: ${release.desktop.signingStatus}`,
    '',
  ].join('\n');
}

async function atomicWrite(path, content) {
  const absolute = resolve(path);
  const temporary = `${absolute}.${process.pid}.${randomUUID()}.tmp`;
  await mkdir(dirname(absolute), { recursive: true });
  try {
    await writeFile(temporary, content, { encoding: 'utf8', flag: 'wx' });
    await rename(temporary, absolute);
  } finally {
    await rm(temporary, { force: true });
  }
}

export async function writeV3VerificationArtifacts(outputDirectory, evaluation) {
  if (evaluation.errors.length) {
    throw new Error(`V3 verification is incomplete:\n- ${evaluation.errors.join('\n- ')}`);
  }
  const output = resolve(outputDirectory);
  await Promise.all([
    atomicWrite(join(output, 'verification.json'), `${canonicalJson(evaluation.manifest, 2)}\n`),
    atomicWrite(join(output, 'traceability.md'), renderV3Traceability(evaluation.manifest)),
    atomicWrite(join(output, 'release.md'), renderV3Release(evaluation.manifest)),
  ]);
  return output;
}

async function loadEvidenceRecords(directory) {
  const names = (await readdir(directory)).filter((name) => name.endsWith('.json')).sort();
  return Promise.all(names.map(async (name) => JSON.parse(await readFile(join(directory, name), 'utf8'))));
}

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!['--evidence-dir', '--output-dir', '--release-input'].includes(key) || !value) {
      throw new Error(
        'Usage: node scripts/v3-verification.mjs --evidence-dir <dir> --output-dir <dir> --release-input <json>',
      );
    }
    options[key.slice(2)] = value;
  }
  return options;
}

async function runCli() {
  const options = parseArguments(process.argv.slice(2));
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const evaluation = evaluateV3Verification({
    records: await loadEvidenceRecords(resolve(options['evidence-dir'])),
    specSource: await readFile(join(root, 'specs/003-workdude-v3-rebuild/spec.md'), 'utf8'),
    taskSource: await readFile(join(root, 'specs/003-workdude-v3-rebuild/tasks.md'), 'utf8'),
    referenceSource: await readFile(join(root, 'tests/visual/v3/reference-states.ts'), 'utf8'),
    release: JSON.parse(await readFile(resolve(options['release-input']), 'utf8')),
  });
  await writeV3VerificationArtifacts(resolve(options['output-dir']), evaluation);
  console.log(JSON.stringify({ revision: evaluation.manifest.source.revision, complete: true }));
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : undefined;
if (invokedPath && fileURLToPath(import.meta.url) === invokedPath) {
  runCli().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
