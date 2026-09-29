import { Buffer } from 'node:buffer';
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { scanBufferForSecrets } from './scan-v3-secrets.mjs';
import { v4SecretCanaries } from './scan-v4-secrets.mjs';

const defaultRepositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SHA = /^[0-9a-f]{40}$/u;
const RELEASE_TAG = /^desktop-v[0-9A-Za-z][0-9A-Za-z.+-]{0,126}$/u;
const MAX_OBJECT_BYTES = 64 * 1024 * 1024;
const MAX_BATCH_BYTES = 16 * 1024 * 1024;

class ReleaseHistoryScanError extends Error {}

function gitEnvironment() {
  return {
    ...process.env,
    GIT_NO_LAZY_FETCH: '1',
    GIT_TERMINAL_PROMPT: '0',
  };
}

function invokeGit(repositoryRoot, args, options = {}) {
  return spawnSync('git', ['--no-replace-objects', ...args], {
    cwd: repositoryRoot,
    env: gitEnvironment(),
    windowsHide: true,
    input: options.input,
    encoding: options.encoding,
    maxBuffer: options.maxBuffer ?? 16 * 1024 * 1024,
  });
}

function gitText(repositoryRoot, args, failure) {
  const result = invokeGit(repositoryRoot, args, { encoding: 'utf8' });
  if (result.error || result.status !== 0) throw new ReleaseHistoryScanError(failure);
  return String(result.stdout).trim();
}

function requireCommit(repositoryRoot, revision, label) {
  const resolved = gitText(
    repositoryRoot,
    ['rev-parse', '--verify', `${revision}^{commit}`],
    `${label} revision is unavailable`,
  );
  if (resolved !== revision) throw new ReleaseHistoryScanError(`${label} revision is unavailable`);
}

function splitObjectIds(output, failure) {
  if (!output) return [];
  const ids = output.split(/\r?\n/u);
  if (ids.some((id) => !SHA.test(id))) throw new ReleaseHistoryScanError(failure);
  return ids;
}

function splitParentIds(output) {
  if (!output) return [];
  const ids = output.split(/\s+/u);
  if (ids.some((id) => !SHA.test(id))) {
    throw new ReleaseHistoryScanError('base parent metadata is malformed');
  }
  return ids;
}

function batchMetadata(repositoryRoot, objectIds) {
  const input = `${objectIds.join('\n')}\n`;
  const result = invokeGit(
    repositoryRoot,
    ['cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)'],
    { input, encoding: 'utf8', maxBuffer: Math.max(1024 * 1024, objectIds.length * 128) },
  );
  if (result.error || result.status !== 0) {
    throw new ReleaseHistoryScanError('Git object metadata is unavailable');
  }
  const lines = String(result.stdout).trim().split(/\r?\n/u);
  if (lines.length !== objectIds.length) {
    throw new ReleaseHistoryScanError('Git object metadata is incomplete');
  }
  return lines.map((line, index) => {
    const match = /^([0-9a-f]{40}) (blob|commit|tag|tree) ([0-9]+)$/u.exec(line);
    const expected = objectIds[index];
    if (!match || match[1] !== expected) {
      throw new ReleaseHistoryScanError('Git object metadata is malformed');
    }
    const size = Number(match[3]);
    if (!Number.isSafeInteger(size) || size < 0) {
      throw new ReleaseHistoryScanError('Git object size is invalid');
    }
    if (size > MAX_OBJECT_BYTES) {
      throw new ReleaseHistoryScanError(`Git object exceeds the 64 MiB scan limit: ${expected}`);
    }
    return { objectId: expected, type: match[2], size };
  });
}

function readBatch(repositoryRoot, metadata) {
  const input = `${metadata.map(({ objectId }) => objectId).join('\n')}\n`;
  const expectedBytes = metadata.reduce((total, { size }) => total + size + 128, 1024 * 1024);
  const result = invokeGit(repositoryRoot, ['cat-file', '--batch'], {
    input,
    maxBuffer: expectedBytes,
  });
  if (result.error || result.status !== 0 || !Buffer.isBuffer(result.stdout)) {
    throw new ReleaseHistoryScanError('Git object content is unavailable');
  }

  const contents = [];
  let offset = 0;
  for (const expected of metadata) {
    const newline = result.stdout.indexOf(10, offset);
    if (newline < 0) throw new ReleaseHistoryScanError('Git object batch is truncated');
    const header = result.stdout.subarray(offset, newline).toString('utf8');
    const exactHeader = `${expected.objectId} ${expected.type} ${expected.size}`;
    if (header !== exactHeader) throw new ReleaseHistoryScanError('Git object batch is malformed');
    const start = newline + 1;
    const end = start + expected.size;
    if (end >= result.stdout.length || result.stdout[end] !== 10) {
      throw new ReleaseHistoryScanError('Git object batch is truncated');
    }
    contents.push({ ...expected, content: result.stdout.subarray(start, end) });
    offset = end + 1;
  }
  if (offset !== result.stdout.length) {
    throw new ReleaseHistoryScanError('Git object batch has unexpected trailing content');
  }
  return contents;
}

function scanObjects(repositoryRoot, metadata, canaries) {
  const findings = [];
  let batch = [];
  let batchBytes = 0;
  const flush = () => {
    if (batch.length === 0) return;
    for (const object of readBatch(repositoryRoot, batch)) {
      for (const match of scanBufferForSecrets(object.content, canaries)) {
        findings.push({
          category: `git-${object.type}`,
          path: `git-object:${object.objectId}`,
          line: match.line,
          detector: match.detector,
          fingerprint: match.fingerprint,
        });
      }
    }
    batch = [];
    batchBytes = 0;
  };

  for (const object of metadata) {
    if (batch.length > 0 && batchBytes + object.size > MAX_BATCH_BYTES) flush();
    batch.push(object);
    batchBytes += object.size;
  }
  flush();
  return [
    ...new Map(
      findings.map((finding) => [
        `${finding.path}\0${finding.line}\0${finding.detector}\0${finding.fingerprint}`,
        finding,
      ]),
    ).values(),
  ];
}

function emptyResult(options, error) {
  return {
    baseRevision: null,
    targetRevision: null,
    tag: null,
    includeBase: options.includeBase === true,
    commitCount: 0,
    objectCount: 0,
    scannedObjects: 0,
    scannedBytes: 0,
    findings: [],
    errors: [{ category: 'git-history', path: '.', error }],
  };
}

export function inspectV4ReleaseHistoryRange(options) {
  const repositoryRoot = resolve(options.repositoryRoot ?? defaultRepositoryRoot);
  if (!SHA.test(options.baseRevision ?? '')) {
    throw new ReleaseHistoryScanError('base revision must be a lowercase 40-character Git SHA');
  }
  if (!SHA.test(options.targetRevision ?? '')) {
    throw new ReleaseHistoryScanError('target revision must be a lowercase 40-character Git SHA');
  }
  if (!RELEASE_TAG.test(options.tag ?? '')) {
    throw new ReleaseHistoryScanError('release tag name is invalid');
  }
  const worktree = gitText(
    repositoryRoot,
    ['rev-parse', '--is-inside-work-tree'],
    'Git repository is unavailable',
  );
  if (worktree !== 'true') throw new ReleaseHistoryScanError('Git repository is unavailable');
  const shallow = gitText(
    repositoryRoot,
    ['rev-parse', '--is-shallow-repository'],
    'repository depth is unavailable',
  );
  if (shallow !== 'false') {
    throw new ReleaseHistoryScanError('release history scan requires a complete non-shallow repository');
  }

  requireCommit(repositoryRoot, options.baseRevision, 'base');
  requireCommit(repositoryRoot, options.targetRevision, 'target');
  const ancestry = invokeGit(
    repositoryRoot,
    ['merge-base', '--is-ancestor', options.baseRevision, options.targetRevision],
    { encoding: 'utf8' },
  );
  if (ancestry.error || (ancestry.status !== 0 && ancestry.status !== 1)) {
    throw new ReleaseHistoryScanError('release revision ancestry is unavailable');
  }
  if (ancestry.status === 1) {
    throw new ReleaseHistoryScanError('base revision is not an ancestor of target revision');
  }

  const tagRef = `refs/tags/${options.tag}`;
  const tagObject = gitText(repositoryRoot, ['rev-parse', '--verify', tagRef], 'release tag is unavailable');
  if (!SHA.test(tagObject)) throw new ReleaseHistoryScanError('release tag is unavailable');
  const tagType = gitText(repositoryRoot, ['cat-file', '-t', tagObject], 'release tag type is unavailable');
  if (tagType !== 'tag') throw new ReleaseHistoryScanError('release tag must be an annotated tag object');
  const tagMetadata = gitText(
    repositoryRoot,
    ['cat-file', '-p', tagObject],
    'release tag metadata is unavailable',
  );
  const directTarget = /^object ([0-9a-f]{40})\r?\ntype ([^\r\n]+)\r?\n/u.exec(tagMetadata);
  if (!directTarget) throw new ReleaseHistoryScanError('release tag metadata is malformed');
  if (directTarget[1] !== options.targetRevision || directTarget[2] !== 'commit') {
    throw new ReleaseHistoryScanError('release tag must point directly to target revision');
  }

  const exclusions = options.includeBase
    ? splitParentIds(
        gitText(
          repositoryRoot,
          ['show', '-s', '--format=%P', options.baseRevision],
          'base parents are unavailable',
        ),
      ).map((parent) => `^${parent}`)
    : [`^${options.baseRevision}`];
  const revisionArguments = [options.targetRevision, ...exclusions];
  const commits = splitObjectIds(
    gitText(
      repositoryRoot,
      ['rev-list', '--reverse', '--topo-order', ...revisionArguments],
      'accepted release revisions are unavailable',
    ),
    'accepted release revision metadata is malformed',
  );
  if (commits.length === 0) throw new ReleaseHistoryScanError('accepted release revision range is empty');
  if (options.includeBase && !commits.includes(options.baseRevision)) {
    throw new ReleaseHistoryScanError('inclusive base revision is absent from the accepted range');
  }

  const historyObjects = splitObjectIds(
    gitText(
      repositoryRoot,
      ['rev-list', '--objects', '--no-object-names', ...revisionArguments],
      'accepted release objects are unavailable',
    ),
    'accepted release object metadata is malformed',
  );
  const objectIds = [...new Set([...historyObjects, tagObject])];
  if (objectIds.length === 0) throw new ReleaseHistoryScanError('accepted release object range is empty');
  return {
    repositoryRoot,
    baseRevision: options.baseRevision,
    targetRevision: options.targetRevision,
    tag: options.tag,
    includeBase: options.includeBase === true,
    commits,
    objectIds,
  };
}

export async function scanV4ReleaseHistory(options) {
  let range;
  try {
    range = inspectV4ReleaseHistoryRange(options);
  } catch (cause) {
    return emptyResult(
      options,
      cause instanceof ReleaseHistoryScanError ? cause.message : 'release history inspection failed',
    );
  }

  try {
    const metadata = batchMetadata(range.repositoryRoot, range.objectIds);
    const canaries = [...v4SecretCanaries(options.env ?? process.env), ...(options.canaries ?? [])];
    const findings = scanObjects(range.repositoryRoot, metadata, canaries);
    return {
      baseRevision: range.baseRevision,
      targetRevision: range.targetRevision,
      tag: range.tag,
      includeBase: range.includeBase,
      commitCount: range.commits.length,
      objectCount: metadata.length,
      scannedObjects: metadata.length,
      scannedBytes: metadata.reduce((total, { size }) => total + size, 0),
      findings,
      errors: [],
    };
  } catch (cause) {
    return emptyResult(
      options,
      cause instanceof ReleaseHistoryScanError ? cause.message : 'release history object scan failed',
    );
  }
}

function parseArguments(argv) {
  const options = { includeBase: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--include-base') {
      options.includeBase = true;
      continue;
    }
    if (argument === '--base' || argument === '--target' || argument === '--tag') {
      const value = argv[index + 1];
      if (!value) throw new Error(`${argument} requires a value`);
      index += 1;
      if (argument === '--base') options.baseRevision = value;
      if (argument === '--target') options.targetRevision = value;
      if (argument === '--tag') options.tag = value;
      continue;
    }
    throw new Error('Unknown release history scan argument');
  }
  return options;
}

async function main() {
  let options;
  try {
    options = parseArguments(process.argv.slice(2));
  } catch {
    console.error('[v4-release-history-scan] ERROR . [git-history]: scan arguments are invalid');
    process.exitCode = 2;
    return;
  }
  const result = await scanV4ReleaseHistory({ ...options, repositoryRoot: process.cwd() });
  console.log(
    `[v4-release-history-scan] commits=${result.commitCount} objects=${result.scannedObjects} bytes=${result.scannedBytes}`,
  );
  for (const finding of result.findings) {
    console.error(
      `[v4-release-history-scan] ${finding.path}:${finding.line} [${finding.category}/${finding.detector}] fingerprint=${finding.fingerprint}`,
    );
  }
  for (const error of result.errors) {
    console.error(`[v4-release-history-scan] ERROR ${error.path} [${error.category}]: ${error.error}`);
  }
  if (result.errors.length > 0) process.exitCode = 2;
  else if (result.findings.length > 0) process.exitCode = 1;
  else console.log('[v4-release-history-scan] PASS: accepted Git objects and tag metadata are clean.');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
