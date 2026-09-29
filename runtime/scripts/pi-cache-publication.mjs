import { createHash, randomUUID } from 'node:crypto';
import { lstat, mkdir, open, readFile, readdir, realpath, rename, rm } from 'node:fs/promises';
import { isAbsolute, relative, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

import { normalizePiSourceLock, readStablePlainFile } from './pi-source-boundary.mjs';

const generationNamePattern = /^pi-build-generation-[a-f0-9]{64}$/u;
const interruptedPointerPattern = /^pi-build-current-[0-9A-Za-z-]+\.tmp$/u;
const safeLayouts = new WeakSet();
const readerLayouts = new WeakSet();
const safeReaders = new WeakSet();
const pinnedReaders = new Map();

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isMissing(error) {
  return error instanceof Error && 'code' in error && error.code === 'ENOENT';
}

function isAlreadyPresent(error) {
  return error instanceof Error && 'code' in error && error.code === 'EEXIST';
}

function inside(parent, child) {
  const path = relative(parent, child);
  return path === '' || (!path.startsWith('..') && !isAbsolute(path));
}

function samePath(first, second) {
  return process.platform === 'win32' ? first.toLowerCase() === second.toLowerCase() : first === second;
}

function identity(entry) {
  return `${entry.dev}:${entry.ino}`;
}

function sameTrustedPiSource(first, second) {
  return JSON.stringify(first) === JSON.stringify(second);
}

async function readTrustedPiSource(repositoryRoot) {
  const root = await realpath(resolve(repositoryRoot));
  const path = resolve(root, 'pi-source.lock.json');
  const content = await readStablePlainFile(path, {
    repositoryRoot: root,
    trustedRoot: root,
    label: 'The trusted external Pi source lock',
  });
  return Object.freeze(normalizePiSourceLock(JSON.parse(content.toString('utf8'))));
}

async function assertPlainDirectory(path, label) {
  const entry = await lstat(path);
  if (entry.isSymbolicLink())
    throw new Error(`${label} must not be a symbolic link, junction, or reparse point`);
  if (!entry.isDirectory()) throw new Error(`${label} must be a plain directory`);
  return entry;
}

async function assertPlainFile(path, label) {
  const entry = await lstat(path);
  if (entry.isSymbolicLink())
    throw new Error(`${label} must not be a symbolic link, junction, or reparse point`);
  if (!entry.isFile()) throw new Error(`${label} must be a plain file`);
  if (entry.nlink !== 1) throw new Error(`${label} must not be a hard link`);
  return entry;
}

async function assertStableReaderCacheParent(layout) {
  if (!isRecord(layout) || !readerLayouts.has(layout)) {
    throw new Error('An authentic Pi cache reader layout is required');
  }
  const repositoryRoot = await realpath(resolve(layout.repositoryRoot));
  const cachePath = resolve(repositoryRoot, '.cache');
  const entry = await assertPlainDirectory(cachePath, 'The project cache parent');
  const canonical = await realpath(cachePath);
  const currentTrustedPiSource = await readTrustedPiSource(repositoryRoot);
  if (
    !samePath(repositoryRoot, layout.repositoryRoot) ||
    !samePath(canonical, layout.cacheParent) ||
    identity(entry) !== layout.cacheParentIdentity ||
    !inside(repositoryRoot, canonical) ||
    !samePath(layout.pointerPath, resolve(canonical, 'pi-build-current.json')) ||
    !sameTrustedPiSource(currentTrustedPiSource, layout.trustedPiSource)
  ) {
    throw new Error('The project cache parent changed after its safe layout was resolved');
  }
}

async function assertStableCacheParent(layout) {
  if (!isRecord(layout) || !safeLayouts.has(layout)) {
    throw new Error('An authentic Pi cache layout returned by resolveSafePiCacheLayout is required');
  }
  await assertStableReaderCacheParent(layout);
  const piPath = resolve(layout.repositoryRoot, 'pi');
  await assertPlainDirectory(piPath, 'The immutable Pi root');
  const piRoot = await realpath(piPath);
  if (
    !samePath(piRoot, layout.piRoot) ||
    inside(piRoot, layout.cacheParent) ||
    !samePath(layout.lockPath, resolve(layout.cacheParent, 'pi-build.lock'))
  ) {
    throw new Error('The immutable Pi or publication lock boundary changed after layout resolution');
  }
}

export async function resolvePiCacheReaderLayout({ repositoryRoot = process.cwd() } = {}) {
  const root = await realpath(resolve(repositoryRoot));
  const requestedCacheParent = resolve(root, '.cache');
  const cacheParentEntry = await assertPlainDirectory(requestedCacheParent, 'The project cache parent');
  const cacheParent = await realpath(requestedCacheParent);
  if (!inside(root, cacheParent)) {
    throw new Error('The project cache parent must resolve inside the repository');
  }
  const trustedPiSource = await readTrustedPiSource(root);
  const layout = Object.freeze({
    repositoryRoot: root,
    trustedPiSource,
    cacheParent,
    cacheParentIdentity: identity(cacheParentEntry),
    pointerPath: resolve(cacheParent, 'pi-build-current.json'),
  });
  readerLayouts.add(layout);
  return layout;
}

export async function resolveSafePiCacheLayout({ repositoryRoot = process.cwd() } = {}) {
  const root = await realpath(resolve(repositoryRoot));
  const piRoot = resolve(root, 'pi');
  await assertPlainDirectory(piRoot, 'The immutable Pi root');
  const verifiedPiRoot = await realpath(piRoot);
  const requestedCacheParent = resolve(root, '.cache');
  try {
    await mkdir(requestedCacheParent);
  } catch (error) {
    if (!isAlreadyPresent(error)) throw error;
  }
  const cacheParentEntry = await assertPlainDirectory(requestedCacheParent, 'The project cache parent');
  const cacheParent = await realpath(requestedCacheParent);
  if (!inside(root, cacheParent) || inside(verifiedPiRoot, cacheParent)) {
    throw new Error('The project cache parent must resolve inside the repository and outside immutable Pi');
  }
  const trustedPiSource = await readTrustedPiSource(root);
  const layout = Object.freeze({
    repositoryRoot: root,
    piRoot: verifiedPiRoot,
    trustedPiSource,
    cacheParent,
    cacheParentIdentity: identity(cacheParentEntry),
    pointerPath: resolve(cacheParent, 'pi-build-current.json'),
    lockPath: resolve(cacheParent, 'pi-build.lock'),
  });
  safeLayouts.add(layout);
  readerLayouts.add(layout);
  return layout;
}

async function removeLockIfStale(layout, staleMs) {
  await assertStableCacheParent(layout);
  let entry;
  try {
    entry = await assertPlainFile(layout.lockPath, 'The Pi build cache publication lock');
  } catch (error) {
    if (isMissing(error)) return;
    throw error;
  }
  if (Date.now() - entry.mtimeMs <= staleMs) return;
  throw new Error('The Pi build cache publication lock is stale and requires explicit owner-safe recovery');
}

async function removeOwnedPlainFile(layout, path, label, expectedIdentity) {
  await assertStableCacheParent(layout);
  const parent = await realpath(resolve(path, '..'));
  if (!samePath(parent, layout.cacheParent)) {
    throw new Error(`Refusing to remove ${label} outside the safe cache parent`);
  }
  const entry = await lstat(path).catch((error) => {
    if (isMissing(error)) return undefined;
    throw error;
  });
  if (!entry) return;
  if (entry.isSymbolicLink() || !entry.isFile() || entry.nlink !== 1) {
    throw new Error(`Refusing to remove ${label} because it is not a plain file`);
  }
  if (expectedIdentity && identity(entry) !== expectedIdentity) {
    throw new Error(`Refusing to remove ${label} because its ownership identity changed`);
  }
  await rm(path, { force: true });
}

// This lock serializes publishers that follow this module's protocol. Identity and token checks fail
// closed on observed replacement, but pathname APIs cannot defeat a hostile same-account final-unlink race.
export async function acquirePiBuildCacheLock(layout, options = {}) {
  const timeoutMs = options.timeoutMs ?? 120_000;
  const staleMs = options.staleMs ?? 30 * 60_000;
  const started = Date.now();
  const token = randomUUID();
  while (true) {
    await assertStableCacheParent(layout);
    try {
      const handle = await open(layout.lockPath, 'wx');
      const lockIdentity = identity(await handle.stat());
      try {
        await handle.writeFile(
          `${JSON.stringify({ token, pid: process.pid, createdAt: new Date().toISOString() })}\n`,
        );
        await handle.sync();
      } catch (error) {
        await handle.close();
        throw new Error(
          'Failed to initialize the Pi build cache lock; the incomplete lock was left for explicit owner-safe recovery',
          { cause: error },
        );
      }
      let released = false;
      return {
        async release() {
          if (released) return;
          released = true;
          await handle.close();
          await assertStableCacheParent(layout);
          const currentEntry = await assertPlainFile(layout.lockPath, 'The Pi build cache publication lock');
          if (identity(currentEntry) !== lockIdentity) {
            throw new Error('The Pi build cache publication lock ownership identity changed');
          }
          const current = JSON.parse(await readFile(layout.lockPath, 'utf8'));
          if (current.token !== token) {
            throw new Error('The Pi build cache publication lock ownership changed');
          }
          await removeOwnedPlainFile(layout, layout.lockPath, 'the owned Pi cache lock', lockIdentity);
        },
      };
    } catch (error) {
      if (!isAlreadyPresent(error)) throw error;
      await removeLockIfStale(layout, staleMs);
      if (Date.now() - started >= timeoutMs) {
        throw new Error('Timed out waiting for the Pi build cache publication lock', {
          cause: error,
        });
      }
      await delay(25);
    }
  }
}

function entryMode(entry) {
  return (entry.mode & 0o777).toString(8).padStart(3, '0');
}

function sameStableCacheEntry(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.nlink === second.nlink &&
    first.size === second.size &&
    first.mode === second.mode &&
    first.mtimeMs === second.mtimeMs &&
    first.ctimeMs === second.ctimeMs
  );
}

function assertPlainCacheEntry(entry, label) {
  if (entry.isSymbolicLink() || !entry.isFile() || entry.nlink !== 1) {
    throw new Error(`${label} must be a plain file`);
  }
}

async function readStableCacheFile(path, before, label) {
  assertPlainCacheEntry(before, label);
  const handle = await open(path, 'r');
  try {
    const opened = await handle.stat();
    assertPlainCacheEntry(opened, label);
    if (!sameStableCacheEntry(before, opened)) {
      throw new Error(`${label} changed before it was read`);
    }
    const content = await handle.readFile();
    const after = await handle.stat();
    const pathAfter = await lstat(path);
    assertPlainCacheEntry(pathAfter, label);
    if (!sameStableCacheEntry(opened, after) || !sameStableCacheEntry(after, pathAfter)) {
      throw new Error(`${label} changed while it was read`);
    }
    return content;
  } finally {
    await handle.close();
  }
}

const CACHE_SNAPSHOT_IO_CONCURRENCY = 8;

function createIoLimit(limit) {
  let active = 0;
  const waiting = [];
  return async function limitedIo(operation) {
    if (active >= limit) {
      await new Promise((resolveWait) => waiting.push(resolveWait));
    }
    active += 1;
    try {
      return await operation();
    } finally {
      active -= 1;
      waiting.shift()?.();
    }
  };
}

async function cacheDirectorySnapshot(layout, root, label) {
  await assertStableReaderCacheParent(layout);
  const rootEntry = await assertPlainDirectory(root, label);
  const canonicalRoot = await realpath(root);
  if (
    !inside(layout.cacheParent, canonicalRoot) ||
    (typeof layout.piRoot === 'string' && inside(layout.piRoot, canonicalRoot))
  ) {
    throw new Error(`${label} resolves outside the safe cache boundary`);
  }
  const entries = [`directory\0.\0${entryMode(rootEntry)}\n`];
  const artifacts = new Map();
  let sourceLockContent;
  let sourceLockSha256;
  const limitedIo = createIoLimit(CACHE_SNAPSHOT_IO_CONCURRENCY);
  async function visit(directory) {
    const directoryBefore = await limitedIo(() => lstat(directory));
    if (directoryBefore.isSymbolicLink() || !directoryBefore.isDirectory()) {
      throw new Error(`${label} directory changed while it was read`);
    }
    const directoryEntries = await limitedIo(() => readdir(directory, { withFileTypes: true }));
    await Promise.all(
      directoryEntries.map(async (directoryEntry) => {
        const path = resolve(directory, directoryEntry.name);
        const name = relative(canonicalRoot, path).replaceAll('\\', '/');
        const entry = await limitedIo(() => lstat(path));
        if (entry.isSymbolicLink()) {
          throw new Error(`${label} contains a symbolic link, junction, or reparse point: ${name}`);
        }
        if (entry.isDirectory()) {
          entries.push(`directory\0${name}\0${entryMode(entry)}\n`);
          const canonicalDirectory = await limitedIo(() => realpath(path));
          if (!inside(canonicalRoot, canonicalDirectory)) {
            throw new Error(`${label} directory escapes its generation: ${name}`);
          }
          await visit(path);
          return;
        }
        if (entry.isFile()) {
          if (entry.nlink !== 1) throw new Error(`${label} contains a hard link: ${name}`);
          const content = await limitedIo(() => readStableCacheFile(path, entry, `${label} file ${name}`));
          const hash = createHash('sha256').update(content).digest('hex');
          entries.push(`file\0${name}\0${entryMode(entry)}\0${hash}\n`);
          artifacts.set(name, hash);
          if (name === 'source-lock.json') {
            sourceLockContent = content.toString('utf8');
            sourceLockSha256 = hash;
          }
          return;
        }
        throw new Error(`${label} contains an unsupported entry: ${name}`);
      }),
    );
    const directoryAfter = await limitedIo(() => lstat(directory));
    if (!sameStableCacheEntry(directoryBefore, directoryAfter)) {
      throw new Error(`${label} directory changed while it was read`);
    }
  }
  await visit(canonicalRoot);
  return Object.freeze({
    manifestSha256: createHash('sha256').update(entries.sort().join('')).digest('hex'),
    artifacts,
    sourceLockContent,
    sourceLockSha256,
  });
}

async function cacheDirectoryManifest(layout, root, label) {
  return (await cacheDirectorySnapshot(layout, root, label)).manifestSha256;
}

function validateCacheSourceLock(layout, snapshot, label) {
  if (!snapshot.sourceLockContent || !snapshot.sourceLockSha256) {
    throw new Error(`${label} is missing source-lock.json`);
  }
  let sourceLock;
  try {
    sourceLock = JSON.parse(snapshot.sourceLockContent);
  } catch (error) {
    throw new Error(`${label} source-lock.json is invalid JSON`, { cause: error });
  }
  if (
    !isRecord(sourceLock) ||
    sourceLock.schemaVersion !== 1 ||
    !isRecord(sourceLock.source) ||
    !sameTrustedPiSource(normalizePiSourceLock(sourceLock.source), layout.trustedPiSource)
  ) {
    throw new Error(`${label} source identity does not match the trusted external Pi source`);
  }
  if (!isRecord(sourceLock.artifacts)) {
    throw new Error(`${label} artifact map is invalid`);
  }
  const actualArtifacts = [...snapshot.artifacts.entries()]
    .filter(([name]) => name !== 'source-lock.json')
    .sort(([first], [second]) => first.localeCompare(second));
  const lockedArtifactNames = Object.keys(sourceLock.artifacts).sort((first, second) =>
    first.localeCompare(second),
  );
  if (
    lockedArtifactNames.length !== actualArtifacts.length ||
    lockedArtifactNames.some((name, index) => name !== actualArtifacts[index][0])
  ) {
    throw new Error(`${label} artifact map is not complete for the published tree`);
  }
  for (const [name, hash] of actualArtifacts) {
    if (!/^[a-f0-9]{64}$/u.test(String(sourceLock.artifacts[name])) || sourceLock.artifacts[name] !== hash) {
      throw new Error(`${label} artifact map does not match ${name}`);
    }
  }
  return sourceLock;
}

async function readCurrentPointer(layout) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await assertStableReaderCacheParent(layout);
    let before;
    try {
      before = await assertPlainFile(layout.pointerPath, 'The Pi build cache current pointer');
    } catch (error) {
      if (isMissing(error)) {
        throw new Error('No Pi build cache generation has been published', { cause: error });
      }
      throw error;
    }
    const handle = await open(layout.pointerPath, 'r');
    try {
      const opened = await handle.stat();
      if (!sameStableCacheEntry(before, opened)) {
        if (identity(before) !== identity(opened)) continue;
        throw new Error('The Pi build cache current pointer changed before it was read');
      }
      const content = await handle.readFile('utf8');
      const after = await handle.stat();
      const pathAfter = await lstat(layout.pointerPath);
      assertPlainCacheEntry(pathAfter, 'The Pi build cache current pointer');
      if (identity(after) !== identity(pathAfter)) continue;
      if (!sameStableCacheEntry(opened, after) || !sameStableCacheEntry(after, pathAfter)) {
        throw new Error('The Pi build cache current pointer changed while it was read');
      }
      let pointer;
      try {
        pointer = JSON.parse(content);
      } catch (error) {
        throw new Error('The Pi build cache current pointer is invalid JSON', { cause: error });
      }
      return validateCurrentPointer(pointer, layout.trustedPiSource);
    } finally {
      await handle.close();
    }
  }
  throw new Error('The Pi build cache current pointer changed too frequently to read safely');
}

function validateCurrentPointer(pointer, trustedPiSource) {
  if (
    pointer?.schemaVersion !== 2 ||
    typeof pointer.generation !== 'string' ||
    !generationNamePattern.test(pointer.generation) ||
    typeof pointer.manifestSha256 !== 'string' ||
    pointer.manifestSha256 !== pointer.generation.slice('pi-build-generation-'.length) ||
    typeof pointer.sourceLockSha256 !== 'string' ||
    !/^[a-f0-9]{64}$/u.test(pointer.sourceLockSha256) ||
    typeof pointer.piSourceManifestSha256 !== 'string' ||
    !/^[a-f0-9]{64}$/u.test(pointer.piSourceManifestSha256)
  ) {
    throw new Error('The Pi build cache current pointer is invalid or unbound');
  }
  if (pointer.piSourceManifestSha256 !== trustedPiSource.manifestSha256) {
    throw new Error('The Pi build cache current pointer source identity does not match trusted Pi source');
  }
  return pointer;
}

export async function resolvePublishedPiBuildCache(layout) {
  const pointer = await readCurrentPointer(layout);
  const root = resolve(layout.cacheParent, pointer.generation);
  const relativeRoot = relative(layout.cacheParent, root);
  if (relativeRoot !== pointer.generation || !generationNamePattern.test(relativeRoot)) {
    throw new Error('The Pi build cache generation pointer escapes the safe cache parent');
  }
  await assertPlainDirectory(root, 'The published Pi build cache generation');
  const canonicalRoot = await realpath(root);
  if (!samePath(canonicalRoot, root)) {
    throw new Error('The published Pi build cache generation must be a plain directory');
  }
  const snapshot = await cacheDirectorySnapshot(
    layout,
    canonicalRoot,
    'The published Pi build cache generation',
  );
  validateCacheSourceLock(layout, snapshot, 'The published Pi build cache generation');
  if (
    snapshot.manifestSha256 !== pointer.manifestSha256 ||
    snapshot.sourceLockSha256 !== pointer.sourceLockSha256
  ) {
    throw new Error('The published Pi build cache generation does not match its atomic pointer');
  }
  return Object.freeze({
    generation: pointer.generation,
    manifestSha256: snapshot.manifestSha256,
    sourceLockSha256: snapshot.sourceLockSha256,
    sourceLockContent: snapshot.sourceLockContent,
    piSourceManifestSha256: layout.trustedPiSource.manifestSha256,
    root: canonicalRoot,
  });
}

export async function pinPublishedPiBuildCache({ repositoryRoot = process.cwd() } = {}) {
  const canonicalRoot = await realpath(resolve(repositoryRoot));
  const key = process.platform === 'win32' ? canonicalRoot.toLowerCase() : canonicalRoot;
  let pinned = pinnedReaders.get(key);
  if (!pinned) {
    pinned = (async () => {
      const layout = await resolvePiCacheReaderLayout({ repositoryRoot: canonicalRoot });
      const snapshot = await resolvePublishedPiBuildCache(layout);
      const reader = Object.freeze({
        repositoryRoot: canonicalRoot,
        trustedPiSource: layout.trustedPiSource,
        ...snapshot,
      });
      safeReaders.add(reader);
      return reader;
    })();
    pinnedReaders.set(key, pinned);
    pinned.catch(() => pinnedReaders.delete(key));
  }
  return pinned;
}

export function resolvePiBuildCacheArtifact(reader, artifactPath) {
  if (!isRecord(reader) || !safeReaders.has(reader)) {
    throw new Error('An authentic process-pinned Pi cache reader is required');
  }
  if (
    typeof artifactPath !== 'string' ||
    !artifactPath ||
    artifactPath.includes('\\') ||
    artifactPath.includes('\0') ||
    isAbsolute(artifactPath) ||
    artifactPath.split('/').some((segment) => !segment || segment === '.' || segment === '..')
  ) {
    throw new Error('A safe relative Pi cache artifact path is required');
  }
  const candidate = resolve(reader.root, ...artifactPath.split('/'));
  const name = relative(reader.root, candidate).replaceAll('\\', '/');
  if (name !== artifactPath || !inside(reader.root, candidate)) {
    throw new Error('The Pi cache artifact path escapes its pinned generation');
  }
  return candidate;
}

export async function readPiBuildCacheArtifact(reader, artifactPath) {
  const path = resolvePiBuildCacheArtifact(reader, artifactPath);
  const before = await lstat(path);
  return readStableCacheFile(path, before, `The Pi cache artifact ${artifactPath}`);
}

async function interruptedPointerFiles(layout) {
  await assertStableCacheParent(layout);
  const matches = [];
  for (const entry of await readdir(layout.cacheParent, { withFileTypes: true })) {
    if (!interruptedPointerPattern.test(entry.name)) continue;
    const path = resolve(layout.cacheParent, entry.name);
    const pointerEntry = await assertPlainFile(path, `Interrupted Pi build cache pointer ${entry.name}`);
    matches.push({ path, identity: identity(pointerEntry) });
  }
  return matches.sort((first, second) => first.path.localeCompare(second.path));
}

async function recoverInterruptedPointerFiles(layout) {
  for (const interrupted of await interruptedPointerFiles(layout)) {
    await removeOwnedPlainFile(
      layout,
      interrupted.path,
      'an interrupted Pi cache pointer',
      interrupted.identity,
    );
  }
}

async function runWithLock(layout, options, operation) {
  const held = await acquirePiBuildCacheLock(layout, options);
  let primaryError;
  let result;
  try {
    result = await operation();
  } catch (error) {
    primaryError = error;
  }
  let releaseError;
  try {
    await held.release();
  } catch (error) {
    releaseError = error;
  }
  if (primaryError && releaseError) {
    throw new AggregateError(
      [primaryError, releaseError],
      'Pi cache operation and lock release both failed',
      { cause: primaryError },
    );
  }
  if (releaseError) throw releaseError;
  if (primaryError) throw primaryError;
  return result;
}

async function syncCacheParent(layout) {
  await assertStableCacheParent(layout);
  const handle = await open(layout.cacheParent, 'r');
  try {
    await handle.sync();
  } catch (error) {
    if (!(
      process.platform === 'win32' &&
      error instanceof Error &&
      'code' in error &&
      error.code === 'EPERM'
    )) {
      throw error;
    }
  } finally {
    await handle.close();
  }
}

export async function recoverInterruptedPiBuildGenerationPublication(layout, options = {}) {
  await runWithLock(layout, options, () => recoverInterruptedPointerFiles(layout));
}

export async function removePiBuildCacheScratch(layout, path) {
  await assertStableCacheParent(layout);
  const absolute = resolve(path);
  const relativePath = relative(layout.cacheParent, absolute);
  if (isAbsolute(relativePath) || relativePath.startsWith('..') || !/^pi-build-stage-/u.test(relativePath)) {
    throw new Error(`Refusing to remove an unrelated project cache directory: ${absolute}`);
  }
  const parent = await realpath(resolve(absolute, '..'));
  if (!samePath(parent, layout.cacheParent)) {
    throw new Error('Refusing to remove Pi cache scratch outside the safe cache parent');
  }
  const entry = await lstat(absolute).catch((error) => {
    if (isMissing(error)) return undefined;
    throw error;
  });
  if (entry?.isSymbolicLink() || (entry && !entry.isDirectory())) {
    throw new Error('Refusing to remove a Pi cache scratch link or non-directory');
  }
  if (entry) {
    await cacheDirectoryManifest(layout, absolute, 'The Pi build cache scratch directory');
  }
  await rm(absolute, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}

async function assertReplaceablePointer(layout) {
  const pointer = await lstat(layout.pointerPath).catch((error) => {
    if (isMissing(error)) return undefined;
    throw error;
  });
  if (pointer && (pointer.isSymbolicLink() || !pointer.isFile() || pointer.nlink !== 1)) {
    throw new Error('The Pi build cache current pointer must be a plain file');
  }
}

async function writePointer(layout, generation, snapshot, operations) {
  const temporaryPointer = resolve(layout.cacheParent, `pi-build-current-${randomUUID()}.tmp`);
  const handle = await open(temporaryPointer, 'wx');
  const temporaryPointerIdentity = identity(await handle.stat());
  try {
    await handle.writeFile(
      `${JSON.stringify({
        schemaVersion: 2,
        generation,
        manifestSha256: snapshot.manifestSha256,
        sourceLockSha256: snapshot.sourceLockSha256,
        piSourceManifestSha256: layout.trustedPiSource.manifestSha256,
      })}\n`,
    );
    await handle.sync();
  } finally {
    await handle.close();
  }
  let primaryError;
  try {
    await assertStableCacheParent(layout);
    await assertPlainFile(temporaryPointer, 'The staged Pi build cache current pointer');
    await assertReplaceablePointer(layout);
    await operations.rename(temporaryPointer, layout.pointerPath);
    await syncCacheParent(layout);
  } catch (error) {
    primaryError = error;
  }
  let cleanupError;
  try {
    await removeOwnedPlainFile(
      layout,
      temporaryPointer,
      'the failed Pi cache pointer',
      temporaryPointerIdentity,
    );
  } catch (error) {
    cleanupError = error;
  }
  if (primaryError && cleanupError) {
    throw new AggregateError(
      [primaryError, cleanupError],
      'Pi cache pointer switch and cleanup both failed',
      { cause: primaryError },
    );
  }
  if (cleanupError) throw cleanupError;
  if (primaryError) throw primaryError;
}

async function removeOwnedUnreferencedGeneration(layout, generation, generationRoot, expectedIdentity) {
  await assertStableCacheParent(layout);
  const pointerEntry = await lstat(layout.pointerPath).catch((error) => {
    if (isMissing(error)) return undefined;
    throw error;
  });
  if (pointerEntry) {
    const pointer = await readCurrentPointer(layout);
    if (pointer.generation === generation) {
      throw new Error('Refusing to remove a Pi build cache generation referenced by the current pointer');
    }
  }
  const generationEntry = await assertPlainDirectory(generationRoot, 'The failed Pi build cache generation');
  if (identity(generationEntry) !== expectedIdentity) {
    throw new Error(
      'Refusing to remove the failed Pi build cache generation because its ownership identity changed',
    );
  }
  await cacheDirectorySnapshot(layout, generationRoot, 'The failed Pi build cache generation');
  const currentEntry = await assertPlainDirectory(generationRoot, 'The failed Pi build cache generation');
  if (identity(currentEntry) !== expectedIdentity) {
    throw new Error(
      'Refusing to remove the failed Pi build cache generation because its ownership identity changed',
    );
  }
  await rm(generationRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  await syncCacheParent(layout);
}

export async function publishPiBuildCacheGeneration(layout, publicationRoot, options = {}) {
  await assertStableCacheParent(layout);
  const operations = { rename: options.operations?.rename ?? rename };
  const publication = resolve(publicationRoot);
  const publicationParent = await realpath(resolve(publication, '..'));
  if (
    !samePath(publicationParent, layout.cacheParent) ||
    !/^pi-build-stage-/u.test(relative(layout.cacheParent, publication))
  ) {
    throw new Error('The Pi build cache publication root is outside the safe staging boundary');
  }

  return runWithLock(layout, options, async () => {
    await recoverInterruptedPointerFiles(layout);
    const publicationEntry = await assertPlainDirectory(publication, 'The Pi build cache publication root');
    await assertPlainFile(
      resolve(publication, 'source-lock.json'),
      'The Pi build cache publication source-lock',
    );
    const publicationIdentity = identity(publicationEntry);
    const publicationSnapshot = await cacheDirectorySnapshot(
      layout,
      publication,
      'The Pi build cache publication root',
    );
    validateCacheSourceLock(layout, publicationSnapshot, 'The Pi build cache publication root');
    const generation = `pi-build-generation-${publicationSnapshot.manifestSha256}`;
    const generationRoot = resolve(layout.cacheParent, generation);
    const existing = await lstat(generationRoot).catch((error) => {
      if (isMissing(error)) return undefined;
      throw error;
    });
    if (existing) {
      if (existing.isSymbolicLink() || !existing.isDirectory()) {
        throw new Error('The target Pi build cache generation must be a plain directory');
      }
      const existingSnapshot = await cacheDirectorySnapshot(
        layout,
        generationRoot,
        'The target Pi build cache generation',
      );
      validateCacheSourceLock(layout, existingSnapshot, 'The target Pi build cache generation');
      if (existingSnapshot.manifestSha256 !== publicationSnapshot.manifestSha256) {
        throw new Error('The target Pi build cache generation conflicts with its manifest identity');
      }
    } else {
      await assertStableCacheParent(layout);
      await operations.rename(publication, generationRoot);
      let primaryError;
      try {
        await syncCacheParent(layout);
        const movedEntry = await assertPlainDirectory(
          generationRoot,
          'The published Pi build cache generation',
        );
        if (identity(movedEntry) !== publicationIdentity) {
          throw new Error('The moved Pi build cache generation ownership identity changed');
        }
        const movedSnapshot = await cacheDirectorySnapshot(
          layout,
          generationRoot,
          'The published Pi build cache generation',
        );
        validateCacheSourceLock(layout, movedSnapshot, 'The published Pi build cache generation');
        if (movedSnapshot.manifestSha256 !== publicationSnapshot.manifestSha256) {
          throw new Error('The moved Pi build cache generation changed during publication');
        }
      } catch (error) {
        primaryError = error;
      }
      if (primaryError) {
        let cleanupError;
        try {
          await removeOwnedUnreferencedGeneration(layout, generation, generationRoot, publicationIdentity);
        } catch (error) {
          cleanupError = error;
        }
        if (cleanupError) {
          throw new AggregateError(
            [primaryError, cleanupError],
            'Pi cache generation validation and owned cleanup both failed',
            { cause: primaryError },
          );
        }
        throw primaryError;
      }
    }
    await writePointer(layout, generation, publicationSnapshot, operations);
    return Object.freeze({
      generation,
      manifestSha256: publicationSnapshot.manifestSha256,
      sourceLockSha256: publicationSnapshot.sourceLockSha256,
      sourceLockContent: publicationSnapshot.sourceLockContent,
      piSourceManifestSha256: layout.trustedPiSource.manifestSha256,
      root: generationRoot,
    });
  });
}
