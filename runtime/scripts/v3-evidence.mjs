import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const V3_EVIDENCE_SCHEMA_VERSION = 'workdude.v3.evidence/v1';

const statuses = new Set(['passed', 'failed', 'skipped', 'partial']);
const claimKinds = ['requirements', 'successCriteria', 'acceptanceScenarios', 'referenceStates'];
const sensitiveKeyPattern =
  /^(?:password|passphrase|secret|api[_-]?key|access[_-]?key|secret[_-]?key|access[_-]?token|refresh[_-]?token|authorization|credential|app[_-]?secret|prompt)$/iu;
const sensitiveValuePatterns = [
  /\bsk-[A-Za-z0-9_-]{16,}\b/u,
  /\bAKID[A-Za-z0-9]{12,}\b/u,
  /\bBearer\s+[A-Za-z0-9._~+/-]{16,}={0,2}\b/iu,
];

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isObject(value)) return value;

  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalize(value[key])]),
  );
}

function canonicalJson(value, spacing = 0) {
  return JSON.stringify(canonicalize(value), null, spacing);
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function normalizeStringArray(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((item) => typeof item === 'string' && item.length > 0))].sort();
}

function deriveStatus({ exitCode, mocked, skipped, partial }) {
  if (skipped) return 'skipped';
  if (partial || mocked) return 'partial';
  return exitCode === 0 ? 'passed' : 'failed';
}

function findSensitivePaths(value, path = '$', findings = []) {
  if (typeof value === 'string') {
    if (sensitiveValuePatterns.some((pattern) => pattern.test(value))) findings.push(path);
    return findings;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => findSensitivePaths(item, `${path}[${index}]`, findings));
    return findings;
  }
  if (!isObject(value)) return findings;

  for (const [key, item] of Object.entries(value)) {
    const itemPath = `${path}.${key}`;
    if (sensitiveKeyPattern.test(key)) findings.push(itemPath);
    findSensitivePaths(item, itemPath, findings);
  }
  return findings;
}

function isIsoInstant(value) {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}

function traceabilityCount(record) {
  return record.taskIds.length + claimKinds.reduce((count, kind) => count + record.claims[kind].length, 0);
}

export function createEvidenceRecord(input) {
  if (!isObject(input)) throw new TypeError('Evidence input must be an object');

  const startedAt = input.startedAt;
  const finishedAt = input.finishedAt;
  if (!isIsoInstant(startedAt) || !isIsoInstant(finishedAt)) {
    throw new TypeError('Evidence timestamps must be valid ISO instants');
  }

  const environmentDetails = isObject(input.environment) ? { ...input.environment } : {};
  delete environmentDetails.fingerprint;

  const exitCode = Number.isInteger(input.exitCode) ? input.exitCode : null;
  const mocked = input.mocked === true;
  const skipped = input.skipped === true;
  const partial = input.partial === true;

  const record = {
    schemaVersion: V3_EVIDENCE_SCHEMA_VERSION,
    evidenceId: input.evidenceId,
    gateId: input.gateId,
    taskIds: normalizeStringArray(input.taskIds),
    claims: Object.fromEntries(claimKinds.map((kind) => [kind, normalizeStringArray(input.claims?.[kind])])),
    source: {
      revision: input.source?.revision,
      dirty: input.source?.dirty,
    },
    command: {
      argv: normalizeStringArrayPreservingOrder(input.command?.argv),
      ...(typeof input.command?.cwd === 'string' ? { cwd: input.command.cwd } : {}),
    },
    environment: {
      details: canonicalize(environmentDetails),
      fingerprint: sha256(canonicalJson(environmentDetails)),
    },
    timing: {
      startedAt,
      finishedAt,
      durationMs: Date.parse(finishedAt) - Date.parse(startedAt),
    },
    outcome: {
      status: deriveStatus({ exitCode, mocked, skipped, partial }),
      exitCode,
      mocked,
      skipped,
      partial,
      ...(typeof input.reason === 'string' && input.reason.length > 0 ? { reason: input.reason } : {}),
    },
    metrics: isObject(input.metrics) ? canonicalize(input.metrics) : {},
    artifacts: Array.isArray(input.artifacts)
      ? input.artifacts.map((artifact) => canonicalize(artifact))
      : [],
  };

  assertEvidenceRecord(record);
  return record;
}

function normalizeStringArrayPreservingOrder(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === 'string' && item.length > 0);
}

export function validateEvidenceRecord(record) {
  const errors = [];
  if (!isObject(record)) return ['record must be an object'];

  if (record.schemaVersion !== V3_EVIDENCE_SCHEMA_VERSION) {
    errors.push(`schemaVersion must equal ${V3_EVIDENCE_SCHEMA_VERSION}`);
  }
  if (typeof record.evidenceId !== 'string' || record.evidenceId.length === 0) {
    errors.push('evidenceId must be a non-empty string');
  }
  if (typeof record.gateId !== 'string' || record.gateId.length === 0) {
    errors.push('gateId must be a non-empty string');
  }
  if (!Array.isArray(record.taskIds) || record.taskIds.some((item) => typeof item !== 'string')) {
    errors.push('taskIds must be an array of strings');
  }

  if (!isObject(record.claims)) {
    errors.push('claims must be an object');
  } else {
    for (const kind of claimKinds) {
      if (
        !Array.isArray(record.claims[kind]) ||
        record.claims[kind].some((item) => typeof item !== 'string')
      ) {
        errors.push(`claims.${kind} must be an array of strings`);
      }
    }
  }

  if (!isObject(record.source) || !/^[0-9a-f]{7,64}$/iu.test(record.source.revision ?? '')) {
    errors.push('source.revision must be a Git revision');
  }
  if (!isObject(record.source) || typeof record.source.dirty !== 'boolean') {
    errors.push('source.dirty must be a boolean');
  }

  if (
    !isObject(record.command) ||
    !Array.isArray(record.command.argv) ||
    record.command.argv.length === 0 ||
    record.command.argv.some((item) => typeof item !== 'string' || item.length === 0)
  ) {
    errors.push('command.argv must be a non-empty array of strings');
  }

  if (!isObject(record.environment) || !isObject(record.environment.details)) {
    errors.push('environment.details must be an object');
  } else if (record.environment.fingerprint !== sha256(canonicalJson(record.environment.details))) {
    errors.push('environment.fingerprint does not match environment.details');
  }
  if (!/^[0-9a-f]{64}$/u.test(record.environment?.fingerprint ?? '')) {
    errors.push('environment.fingerprint must be a SHA-256 digest');
  }

  if (!isObject(record.timing)) {
    errors.push('timing must be an object');
  } else {
    const { startedAt, finishedAt, durationMs } = record.timing;
    if (!isIsoInstant(startedAt) || !isIsoInstant(finishedAt)) {
      errors.push('timing timestamps must be valid ISO instants');
    } else if (Date.parse(finishedAt) < Date.parse(startedAt)) {
      errors.push('timing.finishedAt must not precede timing.startedAt');
    } else if (durationMs !== Date.parse(finishedAt) - Date.parse(startedAt)) {
      errors.push('timing.durationMs must match the recorded timestamps');
    }
  }

  if (!isObject(record.outcome) || !statuses.has(record.outcome.status)) {
    errors.push('outcome.status must be passed, failed, skipped, or partial');
  } else {
    const { status, exitCode, mocked, skipped, partial } = record.outcome;
    if (exitCode !== null && !Number.isInteger(exitCode))
      errors.push('outcome.exitCode must be an integer or null');
    if (typeof mocked !== 'boolean' || typeof skipped !== 'boolean' || typeof partial !== 'boolean') {
      errors.push('outcome mocked/skipped/partial flags must be booleans');
    } else {
      const derived = deriveStatus({ exitCode, mocked, skipped, partial });
      if (status !== derived) errors.push(`outcome.status must be derived as ${derived}`);
    }
  }

  if (isObject(record.metrics)) {
    for (const [key, value] of Object.entries(record.metrics)) {
      if (!['string', 'number', 'boolean'].includes(typeof value) && value !== null) {
        errors.push(`metrics.${key} must be a scalar or null`);
      }
    }
  } else {
    errors.push('metrics must be an object');
  }

  if (!Array.isArray(record.artifacts)) {
    errors.push('artifacts must be an array');
  } else {
    record.artifacts.forEach((artifact, index) => {
      if (!isObject(artifact) || typeof artifact.path !== 'string' || artifact.path.length === 0) {
        errors.push(`artifacts[${index}].path must be a non-empty string`);
      }
      if (!isObject(artifact) || !/^[0-9a-f]{64}$/u.test(artifact.sha256 ?? '')) {
        errors.push(`artifacts[${index}].sha256 must be a SHA-256 digest`);
      }
      if (
        isObject(artifact) &&
        artifact.bytes !== undefined &&
        (!Number.isInteger(artifact.bytes) || artifact.bytes < 0)
      ) {
        errors.push(`artifacts[${index}].bytes must be a non-negative integer`);
      }
    });
  }

  if (isObject(record.claims) && Array.isArray(record.taskIds)) {
    const completeClaims = claimKinds.every((kind) => Array.isArray(record.claims[kind]));
    if (completeClaims && record.outcome?.status === 'passed' && traceabilityCount(record) === 0) {
      errors.push('passed evidence must link at least one task or claim');
    }
  }

  for (const path of findSensitivePaths(record)) {
    errors.push(`sensitive evidence is forbidden at ${path}`);
  }

  return errors;
}

export function assertEvidenceRecord(record) {
  const errors = validateEvidenceRecord(record);
  if (errors.length > 0) throw new TypeError(`Invalid V3 evidence:\n- ${errors.join('\n- ')}`);
  return record;
}

export function isPassingEvidence(record) {
  return validateEvidenceRecord(record).length === 0 && record.outcome.status === 'passed';
}

export async function writeEvidenceRecord(outputPath, record) {
  assertEvidenceRecord(record);
  const absolute = resolve(outputPath);
  const temporary = `${absolute}.${process.pid}.${randomUUID()}.tmp`;
  await mkdir(dirname(absolute), { recursive: true });

  try {
    await writeFile(temporary, `${canonicalJson(record, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    await rename(temporary, absolute);
  } finally {
    await rm(temporary, { force: true });
  }

  return absolute;
}

function parseCliArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--help') return { help: true };
    if (argument !== '--input' && argument !== '--output') {
      throw new TypeError(`Unknown argument: ${argument}`);
    }
    const value = argv[index + 1];
    if (!value) throw new TypeError(`Missing value for ${argument}`);
    options[argument.slice(2)] = value;
    index += 1;
  }
  return options;
}

async function runCli() {
  const options = parseCliArguments(process.argv.slice(2));
  if (options.help) {
    console.log(
      'Usage: node scripts/v3-evidence.mjs --input <record-or-input.json> --output <evidence.json>',
    );
    return;
  }
  if (!options.input || !options.output) throw new TypeError('--input and --output are required');

  const payload = JSON.parse(await readFile(resolve(options.input), 'utf8'));
  const record = payload.schemaVersion ? assertEvidenceRecord(payload) : createEvidenceRecord(payload);
  const output = await writeEvidenceRecord(options.output, record);
  console.log(JSON.stringify({ evidenceId: record.evidenceId, output, status: record.outcome.status }));
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : undefined;
if (invokedPath && fileURLToPath(import.meta.url) === invokedPath) {
  runCli().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
