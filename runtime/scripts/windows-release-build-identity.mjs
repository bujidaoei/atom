import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createReadStream } from 'node:fs';
import { execFile } from 'node:child_process';
import { basename, resolve } from 'node:path';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const criticalFiles = Object.freeze({
  executable: 'QoderWake.exe',
  appAsar: 'resources/app.asar',
  nativeHost: 'resources/QoderWakeBrowserNativeHost.exe',
  uninstallHelper: 'resources/QoderWakeUninstallCleanup.exe',
});
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;

function normalizeArchivePath(value) {
  return value.replaceAll('\\', '/');
}

function hashStream(stream) {
  return new Promise((resolveHash, rejectHash) => {
    const digest = createHash('sha256');
    stream.on('data', (chunk) => digest.update(chunk));
    stream.once('error', rejectHash);
    stream.once('end', () => resolveHash(digest.digest('hex')));
  });
}

export function hashWindowsReleaseFile(path) {
  return hashStream(createReadStream(path));
}

async function listArchiveEntries(sevenZipPath, archivePath) {
  const result = await execute(sevenZipPath, ['l', '-slt', archivePath], {
    windowsHide: true,
    encoding: 'utf8',
    maxBuffer: 16 * 1024 * 1024,
  });
  return result.stdout
    .split(/\r?\n/gu)
    .filter((line) => line.startsWith('Path = '))
    .map((line) => normalizeArchivePath(line.slice('Path = '.length)))
    .filter((path) => path !== normalizeArchivePath(resolve(archivePath)) && path !== basename(archivePath));
}

function exactSuffixEntry(entries, suffix, label) {
  const normalizedSuffix = normalizeArchivePath(suffix).toLocaleLowerCase('en-US');
  const matches = entries.filter((entry) => entry.toLocaleLowerCase('en-US').endsWith(normalizedSuffix));
  if (matches.length !== 1) {
    throw new Error(`${label} must contain exactly one ${suffix}; found ${matches.length}`);
  }
  return matches[0];
}

function hashArchiveEntry(sevenZipPath, archivePath, entryPath) {
  return new Promise((resolveHash, rejectHash) => {
    const child = spawn(sevenZipPath, ['x', '-so', archivePath, entryPath], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    const digest = createHash('sha256');
    let stderr = '';
    let settled = false;
    const finish = (cause, hash) => {
      if (settled) return;
      settled = true;
      if (cause) rejectHash(cause);
      else resolveHash(hash);
    };
    child.stdout.on('data', (chunk) => digest.update(chunk));
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      stderr = `${stderr}${chunk}`.slice(-4_000);
    });
    child.once('error', (cause) => finish(new Error('7-Zip entry hashing failed to start', { cause })));
    child.once('exit', (code, signal) => {
      if (code !== 0) {
        finish(new Error(`7-Zip entry hashing failed (${String(code ?? signal)}): ${stderr}`));
        return;
      }
      finish(undefined, digest.digest('hex'));
    });
  });
}

async function archiveIdentity(sevenZipPath, archivePath, prefix, label) {
  const entries = await listArchiveEntries(sevenZipPath, archivePath);
  const identity = {};
  for (const [name, relativePath] of Object.entries(criticalFiles)) {
    const entry = exactSuffixEntry(entries, `${prefix}${relativePath}`, label);
    identity[name] = await hashArchiveEntry(sevenZipPath, archivePath, entry);
  }
  return Object.freeze(identity);
}

function sameCriticalIdentity(first, second) {
  return Object.keys(criticalFiles).every((name) => first[name] === second[name]);
}

function assertCompleteCriticalIdentity(identity, label) {
  if (!identity || typeof identity !== 'object') {
    throw new Error(`${label} Windows critical build identity must be an object`);
  }
  for (const name of Object.keys(criticalFiles)) {
    if (!SHA256_PATTERN.test(identity[name])) {
      throw new Error(`${label} Windows critical build identity ${name} must be one SHA-256`);
    }
  }
}

export function assertMatchingWindowsReleaseBuildIdentity(identity) {
  assertCompleteCriticalIdentity(identity?.unpacked, 'Unpacked');
  assertCompleteCriticalIdentity(identity?.zip, 'ZIP');
  assertCompleteCriticalIdentity(identity?.nupkg, 'NUPKG');
  if (
    !SHA256_PATTERN.test(identity?.nupkgSha256) ||
    !SHA256_PATTERN.test(identity?.setupEmbeddedNupkgSha256)
  ) {
    throw new Error('Windows NUPKG and Setup embedded NUPKG identities must be SHA-256 values');
  }
  if (!sameCriticalIdentity(identity.unpacked, identity.zip)) {
    throw new Error('Windows ZIP payload does not match the current unpacked Desktop build identity');
  }
  if (!sameCriticalIdentity(identity.unpacked, identity.nupkg)) {
    throw new Error('Windows NUPKG payload does not match the current unpacked Desktop build identity');
  }
  if (identity.nupkgSha256 !== identity.setupEmbeddedNupkgSha256) {
    throw new Error('Windows Setup embeds a different NUPKG build identity');
  }
  return Object.freeze(identity);
}

export async function inspectWindowsReleaseBuildIdentity(options) {
  const sevenZipPath = resolve(options.sevenZipPath);
  const packageRoot = resolve(options.packageRoot);
  const zipPath = resolve(options.zipPath);
  const nupkgPath = resolve(options.nupkgPath);
  const setupPath = resolve(options.setupPath);
  const unpacked = {};
  for (const [name, relativePath] of Object.entries(criticalFiles)) {
    unpacked[name] = await hashWindowsReleaseFile(resolve(packageRoot, relativePath));
  }
  const [zip, nupkg, nupkgSha256, setupEntries] = await Promise.all([
    archiveIdentity(sevenZipPath, zipPath, '', 'Windows ZIP'),
    archiveIdentity(sevenZipPath, nupkgPath, 'lib/net45/', 'Windows NUPKG'),
    hashWindowsReleaseFile(nupkgPath),
    listArchiveEntries(sevenZipPath, setupPath),
  ]);
  const embeddedNupkg = exactSuffixEntry(setupEntries, '.nupkg', 'Windows Setup');
  const setupEmbeddedNupkgSha256 = await hashArchiveEntry(sevenZipPath, setupPath, embeddedNupkg);
  return assertMatchingWindowsReleaseBuildIdentity({
    unpacked: Object.freeze(unpacked),
    zip,
    nupkg,
    nupkgSha256,
    setupEmbeddedNupkgSha256,
    setupSha256: await hashWindowsReleaseFile(setupPath),
    zipSha256: await hashWindowsReleaseFile(zipPath),
  });
}
