import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { Buffer } from 'node:buffer';
import { lstat, readFile, readdir } from 'node:fs/promises';
import { basename, dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

import { createLineResolver } from './scan-line-index.mjs';

const execute = promisify(execFile);
const defaultRepositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultScanConcurrency = 8;

// provider-audit-definition:start v3-secret-environment-names
const secretEnvironmentNames = [
  'DEEPSEEK_API_KEY',
  'STORAGE_S3_ACCESS_KEY',
  'STORAGE_S3_SECRET_KEY',
  'FEISHU_APP_SECRET',
  'FEISHU_AUTH_ENCRYPTION_KEY',
  'APP_SECRET_ENCRYPTION_KEY',
  'SANDBOX_BROKER_TOKEN',
  'APP_ACCESS_TOKEN',
  'GITHUB_TOKEN',
  'GH_TOKEN',
];
// provider-audit-definition:end v3-secret-environment-names

const highConfidenceDetectorIds = [
  'provider-api-key',
  'github-token',
  'cloud-access-key',
  'private-key',
  'jwt',
];
const highConfidenceExpression =
  /(\bsk-[A-Za-z0-9]{20,}\b)|(\bgh[pousr]_[A-Za-z0-9]{30,}\b)|(\b(?:AKIA|ASIA|AKID)[A-Za-z0-9]{16,}\b)|(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)|(\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b)/gu;
const highConfidenceSignal = /(?:\bsk-|\bgh[pousr]_|\b(?:AKIA|ASIA|AKID)|-----BEGIN|\beyJ)/u;

const defaultArtifactRoots = [
  { category: 'bundle', path: 'dist' },
  { category: 'bundle', path: 'build' },
  { category: 'bundle', path: 'out' },
  { category: 'bundle', path: 'apps/desktop/out' },
  { category: 'log', path: 'logs' },
  { category: 'log', path: 'test-results' },
  { category: 'log', path: 'playwright-report' },
  { category: 'evidence', path: 'evidence' },
  { category: 'evidence', path: 'output' },
  { category: 'evidence', path: 'specs/003-workdude-v3-rebuild/evidence' },
  { category: 'export', path: 'exports' },
  { category: 'release', path: 'release' },
  { category: 'release', path: 'releases' },
];

function isEnvironmentFile(path) {
  const name = basename(path).toLowerCase();
  return name === '.env' || (name.startsWith('.env.') && name !== '.env.example');
}

function isIgnoredDirectory(path) {
  const name = basename(path).toLowerCase();
  return name === '.git';
}

function fingerprint(value) {
  return createHash('sha256').update(value).digest('hex').slice(0, 12);
}

function displayPath(root, path) {
  const candidate = relative(root, path).replaceAll('\\', '/');
  return candidate && !candidate.startsWith('../') ? candidate : basename(path);
}

async function collectFiles(path) {
  let entry;
  try {
    entry = await lstat(path);
  } catch (error) {
    if (error && typeof error === 'object' && error.code === 'ENOENT') return [];
    throw error;
  }
  if (entry.isSymbolicLink()) return [];
  if (entry.isFile()) return [path];
  if (!entry.isDirectory() || isIgnoredDirectory(path)) return [];

  // Directory enumeration order is platform/filesystem dependent. Sort once
  // before flattening so the bounded worker pool receives a stable source
  // order and findings remain deterministic across runs and hosts.
  const children = (await readdir(path)).sort();
  return (await Promise.all(children.map((child) => collectFiles(resolve(path, child))))).flat();
}

function scanConcurrency(value) {
  if (value === undefined) return defaultScanConcurrency;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(32, Math.floor(parsed)));
}

/**
 * Run independent file scans with a small, explicit worker pool. Results retain
 * source order so findings and errors remain deterministic even when a later
 * file finishes first.
 */
export async function mapScansInOrder(items, worker, concurrency) {
  if (items.length === 0) return [];
  const results = new Array(items.length);
  let nextIndex = 0;
  const run = async () => {
    while (true) {
      const index = nextIndex++;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  };
  const workerCount = Math.min(scanConcurrency(concurrency), items.length);
  await Promise.all(Array.from({ length: workerCount }, run));
  return results;
}

async function gitWorktreeFiles(root) {
  const result = await execute('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
    cwd: root,
    encoding: 'buffer',
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
  });
  return result.stdout
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
    .map((path) => resolve(root, path))
    .filter((path) => !isEnvironmentFile(path));
}

function environmentCanaries(env) {
  return secretEnvironmentNames.flatMap((name) => {
    const value = env[name];
    return value && value.length >= 8 ? [{ id: `environment:${name}`, value }] : [];
  });
}

function scanText(text, canaries, options = {}) {
  const matches = [];
  let lineForOffset;
  const lineAt = (offset) => (lineForOffset ??= createLineResolver(text))(offset);
  if (options.highConfidence !== false) {
    highConfidenceExpression.lastIndex = 0;
    for (const match of text.matchAll(highConfidenceExpression)) {
      const detectorIndex = match.slice(1).findIndex((value) => value !== undefined);
      const detector = highConfidenceDetectorIds[detectorIndex];
      if (!detector) continue;
      const value = match[0];
      matches.push({
        detector,
        offset: match.index,
        line: lineAt(match.index),
        fingerprint: fingerprint(value),
      });
    }
  }
  for (const canary of canaries) {
    if (!canary.value || canary.value.length < 8) continue;
    let offset = text.indexOf(canary.value);
    while (offset >= 0) {
      matches.push({
        detector: `canary:${canary.id}`,
        offset,
        line: lineAt(offset),
        fingerprint: fingerprint(canary.value),
      });
      offset = text.indexOf(canary.value, offset + canary.value.length);
    }
  }
  return matches;
}

export function forEachUtf16AsciiString(buffer, callback) {
  // Decode each interpretation with Node's native UTF-16 decoder instead of
  // appending one JavaScript character at a time. The old `value +=` loop was
  // quadratic for long printable runs in packed binaries (notably Electron's
  // executable/app.asar), which made the release scan spend several minutes in
  // GC while retaining the same four endian/alignment interpretations.
  // The control-code escapes are intentional: UTF-16 detector input is limited
  // to printable ASCII plus tab/newline/CR. Keep the rule explicit for review.
  // eslint-disable-next-line no-control-regex
  const asciiRun = /[\u0009\u000a\u000d\u0020-\u007e]{8,}/gu;
  for (const littleEndian of [true, false]) {
    for (const alignment of [0, 1]) {
      const byteLength = buffer.length - alignment;
      const alignedLength = byteLength - (byteLength % 2);
      if (alignedLength < 2) continue;
      let bytes = buffer.subarray(alignment, alignment + alignedLength);
      if (!littleEndian) {
        // `swap16` mutates, so copy only the current interpretation and let it
        // be released before the next orientation is decoded.
        bytes = Buffer.from(bytes);
        bytes.swap16();
      }
      const text = bytes.toString('utf16le');
      asciiRun.lastIndex = 0;
      for (const match of text.matchAll(asciiRun)) callback(match[0]);
    }
  }
}

export function utf16AsciiStrings(buffer) {
  const values = [];
  forEachUtf16AsciiString(buffer, (value) => values.push(value));
  return values;
}

export function scanBufferForSecrets(buffer, canaries, options = {}) {
  if (options.highConfidence === false && !canaries.some(({ value }) => value?.length >= 8)) return [];
  const matches = [];
  const utf8 = buffer.toString('utf8');
  const scanInput = (scanInputText, index) => {
    // Packed binaries can contain thousands of unrelated printable UTF-16
    // runs. Avoid allocating a line index and running every detector unless a
    // high-confidence token or configured canary is actually present.
    if (
      index > 0 &&
      (options.highConfidence === false || !highConfidenceSignal.test(scanInputText)) &&
      !canaries.some(({ value }) => value?.length >= 8 && scanInputText.includes(value))
    ) {
      return;
    }
    for (const match of scanText(scanInputText, canaries, options)) {
      matches.push({
        line: match.line,
        detector: match.detector,
        fingerprint: match.fingerprint,
        ...(options.includeOffsets ? { offset: match.offset } : {}),
      });
    }
  };
  scanInput(utf8, 0);
  if (!options.utf8Only) forEachUtf16AsciiString(buffer, (value) => scanInput(value, 1));
  return [
    ...new Map(
      matches.map((match) => [
        `${options.includeOffsets ? match.offset : match.line}:${match.detector}:${match.fingerprint}`,
        match,
      ]),
    ).values(),
  ];
}

export async function scanV3Secrets(options = {}) {
  const repositoryRoot = resolve(options.repositoryRoot ?? defaultRepositoryRoot);
  const env = options.env ?? process.env;
  const canaries = [...environmentCanaries(env), ...(options.canaries ?? [])];
  const artifactRoots = options.artifactRoots ?? defaultArtifactRoots;
  const sources = [];
  const errors = [];
  const excludedArtifactFiles = options.excludedArtifactFiles ?? new Set();
  const isExcludedArtifact = (path) =>
    excludedArtifactFiles.has(process.platform === 'win32' ? path.toLowerCase() : path);

  if (options.includeTracked !== false) {
    try {
      const tracked = options.trackedFiles
        ? options.trackedFiles.map((path) => resolve(repositoryRoot, path))
        : await gitWorktreeFiles(repositoryRoot);
      for (const path of tracked) {
        if (isEnvironmentFile(path) || isExcludedArtifact(path)) continue;
        let entry;
        try {
          entry = await lstat(path);
        } catch (error) {
          if (error && typeof error === 'object' && error.code === 'ENOENT') continue;
          throw error;
        }
        if (entry.isFile() && !entry.isSymbolicLink()) {
          sources.push({ category: 'tracked', path, artifact: false });
        }
      }
    } catch (error) {
      errors.push({
        category: 'tracked',
        path: '.',
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  for (const root of artifactRoots) {
    const absoluteRoot = resolve(repositoryRoot, root.path);
    try {
      for (const path of await collectFiles(absoluteRoot)) {
        if (!isExcludedArtifact(path)) sources.push({ category: root.category, path, artifact: true });
      }
    } catch (error) {
      errors.push({
        category: root.category,
        path: displayPath(repositoryRoot, absoluteRoot),
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  const uniqueSources = new Map();
  for (const source of sources) {
    const key = `${source.category}:${source.path.toLowerCase()}`;
    if (!uniqueSources.has(key)) uniqueSources.set(key, source);
  }

  const scannedPaths = new Set();
  const recordScannedPath = (path) => {
    const key = path.toLowerCase();
    scannedPaths.add(key);
    options.scannedFilePaths?.add(key);
  };
  const sourceResults = await mapScansInOrder(
    [...uniqueSources.values()],
    async (source) => {
      const sourceFindings = [];
      const sourceErrors = [];
      if (isEnvironmentFile(source.path) && !source.artifact) {
        return { findings: sourceFindings, errors: sourceErrors };
      }
      try {
        const buffer = await readFile(source.path);
        recordScannedPath(source.path);
        const matches = scanBufferForSecrets(buffer, canaries);
        const filteredMatches = options.filterMatches
          ? await options.filterMatches({ source, buffer, matches })
          : matches;
        for (const match of filteredMatches) {
          sourceFindings.push({
            category: source.category,
            path: displayPath(repositoryRoot, source.path),
            ...match,
          });
        }
      } catch (error) {
        sourceErrors.push({
          category: source.category,
          path: displayPath(repositoryRoot, source.path),
          error: error instanceof Error ? error.message : String(error),
        });
      }
      return { findings: sourceFindings, errors: sourceErrors };
    },
    options.concurrency,
  );
  const findings = sourceResults.flatMap((result) => result?.findings ?? []);
  errors.push(...sourceResults.flatMap((result) => result?.errors ?? []));

  const deduplicatedFindings = [
    ...new Map(
      findings.map((finding) => [
        `${finding.category}:${finding.path}:${finding.line}:${finding.detector}:${finding.fingerprint}`,
        finding,
      ]),
    ).values(),
  ];

  return {
    findings: deduplicatedFindings,
    errors: errors.map((item) => ({ ...item, error: sanitizeScanError(item.error) })),
    scannedFiles: scannedPaths.size,
    categories: [...new Set([...uniqueSources.values()].map((source) => source.category))].sort(),
  };
}

function sanitizeScanError(message) {
  return String(message)
    .replace(/([a-z][a-z0-9+.-]*:\/\/[^:\s/@]+:)[^@\s/]+@/giu, '$1[redacted]@')
    .slice(0, 300);
}

function parseArguments(argv) {
  const options = { canaries: [], artifactRoots: [] };
  let artifactRootsConfigured = false;
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--no-tracked') {
      options.includeTracked = false;
      continue;
    }
    if (argument === '--no-artifacts') {
      if (artifactRootsConfigured) throw new Error('--no-artifacts cannot be combined with --root');
      artifactRootsConfigured = true;
      continue;
    }
    if (argument === '--canary' || argument === '--canary-env' || argument === '--root') {
      const value = argv[index + 1];
      if (!value) throw new Error(`${argument} requires a value`);
      index += 1;
      if (argument === '--canary') options.canaries.push({ id: `cli-${options.canaries.length + 1}`, value });
      if (argument === '--canary-env') {
        const canary = process.env[value];
        if (!canary) throw new Error(`Canary environment variable is missing: ${value}`);
        options.canaries.push({ id: `environment:${value}`, value: canary });
      }
      if (argument === '--root') {
        if (artifactRootsConfigured) throw new Error('--root cannot be combined with --no-artifacts');
        const separator = value.indexOf('=');
        if (separator <= 0) throw new Error('--root must use category=path');
        artifactRootsConfigured = true;
        options.artifactRoots.push({ category: value.slice(0, separator), path: value.slice(separator + 1) });
      }
      continue;
    }
    throw new Error(`Unknown argument: ${argument}`);
  }
  if (!artifactRootsConfigured) delete options.artifactRoots;
  return options;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const result = await scanV3Secrets(options);
  console.log(
    `[v3-secret-scan] scanned ${result.scannedFiles} files; categories=${result.categories.join(',') || 'none'}`,
  );
  for (const finding of result.findings) {
    console.error(
      `[v3-secret-scan] ${finding.path}:${finding.line} [${finding.category}/${finding.detector}] fingerprint=${finding.fingerprint}`,
    );
  }
  for (const error of result.errors) {
    console.error(`[v3-secret-scan] ERROR ${error.path} [${error.category}]: ${error.error}`);
  }
  if (result.errors.length > 0) process.exitCode = 2;
  else if (result.findings.length > 0) process.exitCode = 1;
  else
    console.log(
      '[v3-secret-scan] PASS: no tracked or generated artifact contains a configured canary or known secret shape.',
    );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
