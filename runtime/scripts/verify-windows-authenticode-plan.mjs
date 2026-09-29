import { Buffer } from 'node:buffer';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { lstat, open, mkdtemp, realpath, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { Readable } from 'node:stream';
import { pathToFileURL } from 'node:url';

import yauzl from 'yauzl';

import { canonicalizeWindowsDesktopUpgradePlan } from './plan-windows-desktop-upgrade.mjs';

const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const THUMBPRINT_PATTERN = /^[A-F0-9]{40}$/u;
const ALLOWED_PHASES = Object.freeze(['pre-upgrade', 'pre-install', 'archive', 'post-upgrade']);
const MAX_PLAN_BYTES = 1024 * 1024;
const MAX_ARCHIVE_ENTRIES = 4_096;
const MAX_ARCHIVE_ENTRY_BYTES = 512 * 1024 * 1024;
const MAX_ARCHIVE_TOTAL_BYTES = 8 * 1024 * 1024 * 1024;
const MAX_ARCHIVE_COMPRESSION_RATIO = 200;
const MAX_POWERSHELL_OUTPUT_BYTES = 64 * 1024;
const TEMPORARY_ROOT_PREFIX = 'workdude-authenticode-';
const WINDOWS_DEVICE_NAME = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/iu;

const MATRIX_AUTHORITIES = Object.freeze([
  { id: 'previous-setup', phase: 'pre-upgrade', kind: 'path' },
  { id: 'current-setup', phase: 'pre-install', kind: 'path' },
  { id: 'packaged-main', phase: 'pre-install', kind: 'path' },
  { id: 'packaged-native-host', phase: 'pre-install', kind: 'path' },
  { id: 'packaged-uninstall-helper', phase: 'pre-install', kind: 'path' },
  { id: 'zip-main', phase: 'archive', kind: 'archive', archive: 'zip', entryPath: 'QoderWake.exe' },
  {
    id: 'zip-native-host',
    phase: 'archive',
    kind: 'archive',
    archive: 'zip',
    entryPath: 'resources/QoderWakeBrowserNativeHost.exe',
  },
  {
    id: 'zip-uninstall-helper',
    phase: 'archive',
    kind: 'archive',
    archive: 'zip',
    entryPath: 'resources/QoderWakeUninstallCleanup.exe',
  },
  {
    id: 'nupkg-main',
    phase: 'archive',
    kind: 'archive',
    archive: 'nupkg',
    entryPath: 'lib/net45/QoderWake.exe',
  },
  {
    id: 'nupkg-execution-stub',
    phase: 'archive',
    kind: 'archive',
    archive: 'nupkg',
    entryPath: 'lib/net45/QoderWake_ExecutionStub.exe',
  },
  {
    id: 'nupkg-native-host',
    phase: 'archive',
    kind: 'archive',
    archive: 'nupkg',
    entryPath: 'lib/net45/resources/QoderWakeBrowserNativeHost.exe',
  },
  {
    id: 'nupkg-uninstall-helper',
    phase: 'archive',
    kind: 'archive',
    archive: 'nupkg',
    entryPath: 'lib/net45/resources/QoderWakeUninstallCleanup.exe',
  },
  {
    id: 'nupkg-updater',
    phase: 'archive',
    kind: 'archive',
    archive: 'nupkg',
    entryPath: 'lib/net45/squirrel.exe',
  },
  { id: 'installed-update', phase: 'post-upgrade', kind: 'installed', relativePath: 'Update.exe' },
  {
    id: 'installed-launcher',
    phase: 'post-upgrade',
    kind: 'installed',
    relativePath: 'QoderWake.exe',
  },
  { id: 'installed-main', phase: 'post-upgrade', kind: 'installed', installedKind: 'main' },
  {
    id: 'installed-native-host',
    phase: 'post-upgrade',
    kind: 'installed',
    installedKind: 'native-host',
  },
  {
    id: 'installed-uninstall-helper',
    phase: 'post-upgrade',
    kind: 'installed',
    installedKind: 'uninstall-helper',
  },
]);

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function requireRecord(value, label) {
  if (!isRecord(value)) throw new Error(`${label} must be an object.`);
  return value;
}

function requireString(value, label) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${label} must be a non-empty string.`);
  }
  return value;
}

function requireSha256(value, label) {
  if (typeof value !== 'string' || !SHA256_PATTERN.test(value)) {
    throw new Error(`${label} SHA-256 must be 64 lowercase hexadecimal characters.`);
  }
  return value;
}

function requireSize(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${label} size must be a non-negative safe integer.`);
  }
  return value;
}

function samePath(first, second) {
  return process.platform === 'win32' ? first.toLowerCase() === second.toLowerCase() : first === second;
}

function assertAbsoluteNormalizedPath(path, label) {
  const value = requireString(path, label);
  if (
    !isAbsolute(value) ||
    value.includes('\0') ||
    value.includes('\r') ||
    value.includes('\n') ||
    value.split(/[\\/]/u).some((segment) => segment === '.' || segment === '..') ||
    !samePath(resolve(value), value)
  ) {
    throw new Error(`${label} must be an absolute normalized path.`);
  }
  return value;
}

function assertSafeRelativePath(path, label) {
  const value = requireString(path, label);
  if (
    isAbsolute(value) ||
    value.includes('\\') ||
    value.includes('\0') ||
    value.includes('\r') ||
    value.includes('\n') ||
    /^[A-Za-z]:/u.test(value) ||
    value.startsWith('/') ||
    value.split('/').some((segment) => !segment || segment === '.' || segment === '..')
  ) {
    throw new Error(`${label} must be a safe normalized relative path.`);
  }
  return value;
}

function assertSafeArchiveEntryName(name, label) {
  const value = requireString(name, label);
  if (
    value.includes('\\') ||
    value.includes(':') ||
    value.includes('\0') ||
    value.startsWith('/') ||
    /^[A-Za-z]:/u.test(value) ||
    [...value].some((character) => {
      const code = character.codePointAt(0);
      return code < 32 || code === 127;
    })
  ) {
    throw new Error(`${label} is an unsafe archive entry name: ${value}`);
  }
  const normalized = value.endsWith('/') ? value.slice(0, -1) : value;
  const segments = normalized.split('/');
  if (
    !normalized ||
    segments.some(
      (segment) =>
        !segment ||
        segment === '.' ||
        segment === '..' ||
        segment.endsWith('.') ||
        segment.endsWith(' ') ||
        WINDOWS_DEVICE_NAME.test(segment.split('.')[0].replace(/[ .]+$/gu, '')),
    )
  ) {
    throw new Error(`${label} is an unsafe archive entry name: ${value}`);
  }
  return value;
}

function archiveEntryFold(name) {
  return name.normalize('NFKC').toLowerCase();
}

function isUnixSymlink(entry) {
  const unixMode = (entry.externalFileAttributes >>> 16) & 0xffff;
  return (unixMode & 0xf000) === 0xa000;
}

export function normalizeWindowsCertificateThumbprint(value) {
  if (typeof value !== 'string') throw new Error('The certificate thumbprint must be a string.');
  const normalized = value.replace(/[\s:-]/gu, '').toUpperCase();
  if (!THUMBPRINT_PATTERN.test(normalized)) {
    throw new Error('The certificate thumbprint must contain exactly 40 hexadecimal characters.');
  }
  return normalized;
}

export function validateWindowsAuthenticodeSignature(result, expectedThumbprint, label = 'Target') {
  const signature = requireRecord(result, `${label} Authenticode result`);
  if (signature.status !== 'Valid') {
    throw new Error(`${label} Authenticode status must be Valid; received ${String(signature.status)}.`);
  }
  const expected = normalizeWindowsCertificateThumbprint(expectedThumbprint);
  const actual = normalizeWindowsCertificateThumbprint(signature.signerThumbprint);
  if (actual !== expected) {
    throw new Error(`${label} signer thumbprint does not match the approved certificate.`);
  }
  if (signature.timeStamperCertificatePresent !== true) {
    throw new Error(`${label} must carry a non-empty Authenticode timestamp certificate.`);
  }
  return Object.freeze({ signerThumbprint: actual, timestampVerified: true });
}

async function readOpenedFile(handle, { capture = false, maxBytes = Number.MAX_SAFE_INTEGER } = {}) {
  const hash = createHash('sha256');
  const chunks = [];
  let sizeBytes = 0;
  const stream = handle.createReadStream({ autoClose: false, start: 0 });
  for await (const chunk of stream) {
    sizeBytes += chunk.length;
    if (sizeBytes > maxBytes) throw new Error(`The opened file exceeds the ${maxBytes}-byte limit.`);
    hash.update(chunk);
    if (capture) chunks.push(chunk);
  }
  return Object.freeze({
    sha256: hash.digest('hex'),
    sizeBytes,
    ...(capture ? { bytes: Buffer.concat(chunks, sizeBytes) } : {}),
  });
}

async function openPlainSingleLinkFile(path, label) {
  const declared = assertAbsoluteNormalizedPath(path, label);
  const canonical = await realpath(declared);
  if (!samePath(declared, canonical)) {
    throw new Error(`${label} must not traverse a symbolic link, junction, or reparse point.`);
  }
  const handle = await open(canonical, 'r');
  try {
    const identity = await handle.stat();
    if (!identity.isFile() || identity.isSymbolicLink() || identity.nlink !== 1) {
      throw new Error(`${label} must be a plain single-link file.`);
    }
    return Object.freeze({ path: canonical, handle, identity });
  } catch (error) {
    await handle.close();
    throw error;
  }
}

function sameFileIdentity(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.size === second.size &&
    first.mtimeMs === second.mtimeMs &&
    first.nlink === second.nlink
  );
}

function sameDirectoryIdentity(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.birthtimeMs === second.birthtimeMs &&
    first.mode === second.mode
  );
}

async function createControlledTemporaryRoot() {
  const parent = await realpath(resolve(tmpdir()));
  const path = await mkdtemp(join(parent, TEMPORARY_ROOT_PREFIX));
  const canonical = await realpath(path);
  const identity = await lstat(canonical);
  if (
    !isAbsolute(canonical) ||
    !samePath(path, canonical) ||
    !samePath(dirname(canonical), parent) ||
    !basename(canonical).startsWith(TEMPORARY_ROOT_PREFIX) ||
    basename(canonical).length === TEMPORARY_ROOT_PREFIX.length ||
    !identity.isDirectory() ||
    identity.isSymbolicLink()
  ) {
    throw new Error('The Authenticode temporary root is not one controlled plain directory.');
  }
  return Object.freeze({ path: canonical, parent, identity });
}

async function removeControlledTemporaryRoot(scope) {
  const path = assertAbsoluteNormalizedPath(scope.path, 'The Authenticode temporary root');
  const canonical = await realpath(path);
  const identity = await lstat(path);
  if (
    !samePath(path, canonical) ||
    !samePath(dirname(path), scope.parent) ||
    !samePath(await realpath(dirname(path)), scope.parent) ||
    !basename(path).startsWith(TEMPORARY_ROOT_PREFIX) ||
    basename(path).length === TEMPORARY_ROOT_PREFIX.length ||
    !identity.isDirectory() ||
    identity.isSymbolicLink() ||
    !sameDirectoryIdentity(scope.identity, identity)
  ) {
    throw new Error('Refusing to remove a replaced or uncontrolled Authenticode temporary root.');
  }
  await rm(path, { recursive: true, force: false });
}

async function assertOpenedFileUnchanged(opened, expectedSha256, expectedSizeBytes, label) {
  const afterIdentity = await opened.handle.stat();
  if (!sameFileIdentity(opened.identity, afterIdentity)) {
    throw new Error(`${label} changed while it was being verified.`);
  }
  const after = await readOpenedFile(opened.handle);
  if (after.sha256 !== expectedSha256 || after.sizeBytes !== expectedSizeBytes) {
    throw new Error(`${label} changed after signature inspection; SHA-256 no longer matches.`);
  }

  const rebound = await openPlainSingleLinkFile(opened.path, label);
  try {
    if (!sameFileIdentity(afterIdentity, rebound.identity)) {
      throw new Error(`${label} path was replaced while it was being verified.`);
    }
    const reboundSnapshot = await readOpenedFile(rebound.handle);
    if (reboundSnapshot.sha256 !== expectedSha256 || reboundSnapshot.sizeBytes !== expectedSizeBytes) {
      throw new Error(`${label} path no longer binds the approved SHA-256.`);
    }
  } finally {
    await rebound.handle.close();
  }
}

async function readAndVerifyPlan(planPath, expectedPlanSha256) {
  const expected = requireSha256(expectedPlanSha256, 'The expected raw plan');
  const opened = await openPlainSingleLinkFile(planPath, 'The Windows upgrade plan');
  try {
    const snapshot = await readOpenedFile(opened.handle, { capture: true, maxBytes: MAX_PLAN_BYTES });
    if (snapshot.sha256 !== expected) {
      throw new Error('The raw Windows upgrade plan SHA-256 does not match the approved identity.');
    }
    let parsed;
    try {
      parsed = JSON.parse(snapshot.bytes.toString('utf8'));
    } catch (error) {
      throw new Error('The approved Windows upgrade plan is not valid JSON.', { cause: error });
    }
    return Object.freeze({ opened, parsed, rawSha256: snapshot.sha256, sizeBytes: snapshot.sizeBytes });
  } catch (error) {
    await opened.handle.close();
    throw error;
  }
}

function validatePlanIntegrity(plan) {
  const integrity = requireRecord(plan.integrity, 'Plan integrity');
  if (
    Object.keys(integrity).sort().join(',') !== 'algorithm,planSha256' ||
    integrity.algorithm !== 'sha256'
  ) {
    throw new Error('Plan integrity must use the closed SHA-256 schema.');
  }
  const expected = requireSha256(integrity.planSha256, 'The canonical plan integrity');
  const unsignedPlan = Object.fromEntries(Object.entries(plan).filter(([key]) => key !== 'integrity'));
  const actual = createHash('sha256')
    .update(canonicalizeWindowsDesktopUpgradePlan(unsignedPlan), 'utf8')
    .digest('hex');
  if (actual !== expected) throw new Error('The canonical Windows upgrade plan integrity does not match.');
}

function requireIdentity(value, label) {
  const identity = requireRecord(value, label);
  return Object.freeze({
    path: assertAbsoluteNormalizedPath(identity.path, `${label} path`),
    sha256: requireSha256(identity.sha256, label),
    sizeBytes: requireSize(identity.sizeBytes, label),
  });
}

function expectedInstalledRelativePath(authority, currentVersion) {
  if (authority.relativePath) return authority.relativePath;
  const squirrelVersion = currentVersion.replace('-beta.', '-beta');
  switch (authority.installedKind) {
    case 'main':
      return `app-${squirrelVersion}/QoderWake.exe`;
    case 'native-host':
      return `app-${squirrelVersion}/resources/QoderWakeBrowserNativeHost.exe`;
    case 'uninstall-helper':
      return `app-${squirrelVersion}/resources/QoderWakeUninstallCleanup.exe`;
    default:
      throw new Error(`Unsupported installed signature authority: ${String(authority.id)}`);
  }
}

function expectedPathAuthority(authority, planAuthority) {
  switch (authority.id) {
    case 'previous-setup':
      return planAuthority.previous.path;
    case 'current-setup':
      return planAuthority.currentSetup.path;
    case 'packaged-main':
      return resolve(planAuthority.packageRoot, 'QoderWake.exe');
    case 'packaged-native-host':
      return resolve(planAuthority.packageRoot, 'resources/QoderWakeBrowserNativeHost.exe');
    case 'packaged-uninstall-helper':
      return resolve(planAuthority.packageRoot, 'resources/QoderWakeUninstallCleanup.exe');
    default:
      throw new Error(`Unsupported path signature authority: ${String(authority.id)}`);
  }
}

function assertRowBinding(row, authority, planAuthority) {
  if (row.phase !== authority.phase) {
    throw new Error(`Signature matrix row ${authority.id} has the wrong phase.`);
  }
  requireSha256(row.sha256, `Signature matrix row ${authority.id}`);
  requireSize(row.sizeBytes, `Signature matrix row ${authority.id}`);

  if (authority.kind === 'path') {
    const expectedPath = expectedPathAuthority(authority, planAuthority);
    const path = assertAbsoluteNormalizedPath(row.path, `Signature matrix row ${authority.id} path`);
    if (!samePath(path, expectedPath)) {
      throw new Error(`Signature matrix row ${authority.id} path is not bound to its plan authority.`);
    }
    if (authority.id === 'previous-setup') {
      if (
        row.sha256 !== planAuthority.previous.sha256 ||
        row.sizeBytes !== planAuthority.previous.sizeBytes
      ) {
        throw new Error('Signature matrix row previous-setup is not bound to the previous Setup identity.');
      }
    }
    if (authority.id === 'current-setup') {
      if (
        row.sha256 !== planAuthority.currentSetup.sha256 ||
        row.sizeBytes !== planAuthority.currentSetup.sizeBytes
      ) {
        throw new Error('Signature matrix row current-setup is not bound to the current Setup identity.');
      }
    }
    if (row.archivePath !== undefined || row.entryPath !== undefined || row.relativePath !== undefined) {
      throw new Error(`Signature matrix row ${authority.id} mixes incompatible path authorities.`);
    }
    return;
  }

  if (authority.kind === 'archive') {
    const archiveIdentity = planAuthority[authority.archive];
    const archivePath = assertAbsoluteNormalizedPath(
      row.archivePath,
      `Signature matrix row ${authority.id} archive path`,
    );
    if (
      !samePath(archivePath, archiveIdentity.path) ||
      row.archiveSha256 !== archiveIdentity.sha256 ||
      row.archiveSizeBytes !== archiveIdentity.sizeBytes
    ) {
      throw new Error(`Signature matrix row ${authority.id} is not bound to the approved archive identity.`);
    }
    if (
      assertSafeArchiveEntryName(row.entryPath, `Signature matrix row ${authority.id}`) !==
      authority.entryPath
    ) {
      throw new Error(`Signature matrix row ${authority.id} has the wrong archive entry path.`);
    }
    requireSize(row.compressedSizeBytes, `Signature matrix row ${authority.id} compressed`);
    if (row.path !== undefined || row.relativePath !== undefined) {
      throw new Error(`Signature matrix row ${authority.id} mixes incompatible archive authorities.`);
    }
    return;
  }

  const expectedRelativePath = expectedInstalledRelativePath(authority, planAuthority.currentVersion);
  const relativePath = assertSafeRelativePath(
    row.relativePath,
    `Signature matrix row ${authority.id} relative path`,
  );
  if (relativePath !== expectedRelativePath) {
    throw new Error(`Signature matrix row ${authority.id} has the wrong installed relative path.`);
  }
  if (row.path !== undefined || row.archivePath !== undefined || row.entryPath !== undefined) {
    throw new Error(`Signature matrix row ${authority.id} mixes incompatible installed authorities.`);
  }
}

function assertMatchingContent(first, second, label) {
  if (first.sha256 !== second.sha256 || first.sizeBytes !== second.sizeBytes) {
    throw new Error(`${label} signature matrix entry SHA-256 and size must bind the same executable bytes.`);
  }
}

function validateWindowsUpgradePlan(value) {
  const plan = requireRecord(value, 'The Windows upgrade plan');
  if (
    plan.schemaVersion !== 1 ||
    plan.kind !== 'windows-squirrel-in-place-upgrade' ||
    plan.executionAllowed !== false
  ) {
    throw new Error('The Windows upgrade plan has an unsupported or executable schema.');
  }
  validatePlanIntegrity(plan);
  const previous = requireIdentity(plan.previous, 'The previous Setup identity');
  const current = requireRecord(plan.current, 'The current release identity');
  const currentVersion = requireString(current.version, 'The current release version');
  const currentSetup = requireIdentity(current.setup, 'The current Setup identity');
  const zip = requireIdentity(current.zip, 'The current ZIP identity');
  const nupkg = requireIdentity(current.nupkg, 'The current NUPKG identity');
  const packageRoot = assertAbsoluteNormalizedPath(current.packageRoot, 'The current package root');
  if (!Array.isArray(plan.signatureMatrix)) throw new Error('The signature matrix must be an array.');
  if (plan.signatureMatrix.length !== MATRIX_AUTHORITIES.length) {
    throw new Error(`The signature matrix must contain exactly ${MATRIX_AUTHORITIES.length} rows.`);
  }

  const rows = new Map();
  for (let index = 0; index < plan.signatureMatrix.length; index += 1) {
    const row = requireRecord(plan.signatureMatrix[index], `Signature matrix row ${index + 1}`);
    const id = requireString(row.id, `Signature matrix row ${index + 1} id`);
    if (rows.has(id)) throw new Error(`The signature matrix contains duplicate row ${id}.`);
    const authority = MATRIX_AUTHORITIES[index];
    if (id !== authority.id) {
      throw new Error(`The signature matrix row order or authority is invalid at ${authority.id}.`);
    }
    rows.set(id, row);
  }

  const planAuthority = { previous, currentSetup, zip, nupkg, packageRoot, currentVersion };
  for (const authority of MATRIX_AUTHORITIES) {
    assertRowBinding(rows.get(authority.id), authority, planAuthority);
  }
  assertMatchingContent(rows.get('packaged-main'), rows.get('zip-main'), 'Packaged/ZIP main');
  assertMatchingContent(rows.get('packaged-main'), rows.get('nupkg-main'), 'Packaged/NUPKG main');
  assertMatchingContent(rows.get('packaged-main'), rows.get('installed-main'), 'Packaged/installed main');
  assertMatchingContent(
    rows.get('packaged-native-host'),
    rows.get('zip-native-host'),
    'Packaged/ZIP Native Host',
  );
  assertMatchingContent(
    rows.get('packaged-native-host'),
    rows.get('nupkg-native-host'),
    'Packaged/NUPKG Native Host',
  );
  assertMatchingContent(
    rows.get('packaged-native-host'),
    rows.get('installed-native-host'),
    'Packaged/installed Native Host',
  );
  assertMatchingContent(
    rows.get('packaged-uninstall-helper'),
    rows.get('zip-uninstall-helper'),
    'Packaged/ZIP uninstall helper',
  );
  assertMatchingContent(
    rows.get('packaged-uninstall-helper'),
    rows.get('nupkg-uninstall-helper'),
    'Packaged/NUPKG uninstall helper',
  );
  assertMatchingContent(
    rows.get('packaged-uninstall-helper'),
    rows.get('installed-uninstall-helper'),
    'Packaged/installed uninstall helper',
  );
  assertMatchingContent(
    rows.get('nupkg-execution-stub'),
    rows.get('installed-launcher'),
    'NUPKG/installed launcher',
  );
  assertMatchingContent(rows.get('nupkg-updater'), rows.get('installed-update'), 'NUPKG/installed updater');
  return Object.freeze({ plan, rows, zip, nupkg });
}

function normalizePhases(phases) {
  if (!Array.isArray(phases) || phases.length === 0) {
    throw new Error('At least one Authenticode verification phase is required.');
  }
  const normalized = [];
  for (const phase of phases) {
    if (!ALLOWED_PHASES.includes(phase)) throw new Error(`Unsupported Authenticode phase: ${String(phase)}`);
    if (normalized.includes(phase)) throw new Error(`Duplicate Authenticode phase: ${phase}`);
    normalized.push(phase);
  }
  return Object.freeze(normalized);
}

async function copyOpenedTargetToStage(opened, row, temporaryRoot) {
  const destination = resolve(temporaryRoot, `target-${row.id}.exe`);
  const output = await open(destination, 'wx+', 0o600);
  try {
    const hash = createHash('sha256');
    let sizeBytes = 0;
    const stream = opened.handle.createReadStream({ autoClose: false, start: 0 });
    for await (const chunk of stream) {
      sizeBytes += chunk.length;
      if (sizeBytes > row.sizeBytes) throw new Error(`Signature target ${row.id} exceeded its matrix size.`);
      hash.update(chunk);
      await output.write(chunk, 0, chunk.length, sizeBytes - chunk.length);
    }
    await output.sync();
    if (hash.digest('hex') !== row.sha256 || sizeBytes !== row.sizeBytes) {
      throw new Error(`Signature target ${row.id} staging SHA-256 or size does not match its matrix row.`);
    }
    return destination;
  } finally {
    await output.close();
  }
}

async function verifyStagedSignatureTarget(row, stagedPath, signatureRunner, expectedThumbprint) {
  const staged = await openPlainSingleLinkFile(stagedPath, `Staged signature target ${row.id}`);
  try {
    const before = await readOpenedFile(staged.handle);
    if (before.sha256 !== row.sha256 || before.sizeBytes !== row.sizeBytes) {
      throw new Error(`Staged signature target ${row.id} SHA-256 or size does not match its matrix row.`);
    }
    const signature = await signatureRunner(staged.path);
    validateWindowsAuthenticodeSignature(signature, expectedThumbprint, `Signature target ${row.id}`);
    await assertOpenedFileUnchanged(staged, row.sha256, row.sizeBytes, `Staged signature target ${row.id}`);
    return Object.freeze({
      id: row.id,
      phase: row.phase,
      sha256: row.sha256,
      sizeBytes: row.sizeBytes,
    });
  } finally {
    await staged.handle.close();
  }
}

async function verifyPathTarget(row, path, temporaryRoot, signatureRunner, expectedThumbprint) {
  const opened = await openPlainSingleLinkFile(path, `Signature target ${row.id}`);
  try {
    const before = await readOpenedFile(opened.handle);
    if (before.sha256 !== row.sha256 || before.sizeBytes !== row.sizeBytes) {
      throw new Error(`Signature target ${row.id} SHA-256 or size does not match its matrix row.`);
    }
    const stagedPath = await copyOpenedTargetToStage(opened, row, temporaryRoot);
    const result = await verifyStagedSignatureTarget(row, stagedPath, signatureRunner, expectedThumbprint);
    await assertOpenedFileUnchanged(opened, row.sha256, row.sizeBytes, `Signature target ${row.id}`);
    return result;
  } finally {
    await opened.handle.close();
  }
}

class OpenedFileRandomAccessReader extends yauzl.RandomAccessReader {
  constructor(handle) {
    super();
    this.handle = handle;
  }

  _readStreamForRange(start, end) {
    const handle = this.handle;
    return Readable.from(
      (async function* readRange() {
        let position = start;
        while (position < end) {
          const buffer = Buffer.allocUnsafe(Math.min(64 * 1024, end - position));
          const { bytesRead } = await handle.read(buffer, 0, buffer.length, position);
          if (bytesRead === 0)
            throw new Error('Unexpected end of archive while reading from the opened handle.');
          position += bytesRead;
          yield buffer.subarray(0, bytesRead);
        }
      })(),
    );
  }
}

function openZipFromOpenedFile(opened, label) {
  return new Promise((resolveArchive, rejectArchive) => {
    yauzl.fromRandomAccessReader(
      new OpenedFileRandomAccessReader(opened.handle),
      opened.identity.size,
      { autoClose: false, lazyEntries: true, strictFileNames: true, validateEntrySizes: true },
      (error, archive) => {
        if (error || !archive) {
          rejectArchive(new Error(`${label} could not be opened as a ZIP archive.`, { cause: error }));
          return;
        }
        resolveArchive(archive);
      },
    );
  });
}

async function writeArchiveEntryToControlledFile(archive, entry, row, destination) {
  if (entry.generalPurposeBitFlag & 1) {
    throw new Error(`Archive entry ${entry.fileName} must not be encrypted.`);
  }
  if (isUnixSymlink(entry)) throw new Error(`Archive entry ${entry.fileName} must not be a Unix symlink.`);
  if (
    entry.uncompressedSize !== row.sizeBytes ||
    entry.compressedSize !== row.compressedSizeBytes ||
    entry.uncompressedSize > MAX_ARCHIVE_ENTRY_BYTES
  ) {
    throw new Error(`Archive entry ${entry.fileName} size does not match its matrix row or safety limit.`);
  }
  const ratio = entry.uncompressedSize / Math.max(entry.compressedSize, 1);
  if (ratio > MAX_ARCHIVE_COMPRESSION_RATIO) {
    throw new Error(`Archive entry ${entry.fileName} exceeds the compression ratio limit.`);
  }

  const stream = await new Promise((resolveStream, rejectStream) => {
    archive.openReadStream(entry, (error, openedStream) => {
      if (error || !openedStream) {
        rejectStream(new Error(`Archive entry ${entry.fileName} could not be read.`, { cause: error }));
        return;
      }
      resolveStream(openedStream);
    });
  });
  const output = await open(destination, 'wx+', 0o600);
  try {
    const hash = createHash('sha256');
    let sizeBytes = 0;
    for await (const chunk of stream) {
      sizeBytes += chunk.length;
      if (sizeBytes > row.sizeBytes) throw new Error(`Archive entry ${entry.fileName} exceeded its size.`);
      hash.update(chunk);
      await output.write(chunk, 0, chunk.length, sizeBytes - chunk.length);
    }
    await output.sync();
    const digest = hash.digest('hex');
    if (digest !== row.sha256 || sizeBytes !== row.sizeBytes) {
      throw new Error(`Archive entry ${entry.fileName} SHA-256 or size does not match its matrix row.`);
    }
  } finally {
    await output.close();
  }
}

async function extractArchiveTargets(opened, rows, temporaryRoot) {
  const archive = await openZipFromOpenedFile(opened, `Archive ${opened.path}`);
  const required = new Map(rows.map((row) => [row.entryPath, row]));
  const extracted = new Map();
  const seen = new Set();
  let entryCount = 0;
  let totalUncompressedBytes = 0;

  try {
    await new Promise((resolveEntries, rejectEntries) => {
      let settled = false;
      const reject = (error) => {
        if (settled) return;
        settled = true;
        rejectEntries(error);
      };
      archive.once('error', reject);
      archive.on('entry', (entry) => {
        if (settled) return;
        try {
          entryCount += 1;
          if (entryCount > MAX_ARCHIVE_ENTRIES)
            throw new Error('Archive entry count exceeds the safety limit.');
          const name = assertSafeArchiveEntryName(entry.fileName, 'Archive');
          const folded = archiveEntryFold(name);
          if (seen.has(folded))
            throw new Error(`Archive contains a duplicate or case-conflicting entry: ${name}`);
          seen.add(folded);
          if (!Number.isSafeInteger(entry.uncompressedSize) || !Number.isSafeInteger(entry.compressedSize)) {
            throw new Error(`Archive entry ${name} has an invalid size.`);
          }
          totalUncompressedBytes += entry.uncompressedSize;
          if (
            entry.uncompressedSize > MAX_ARCHIVE_ENTRY_BYTES ||
            totalUncompressedBytes > MAX_ARCHIVE_TOTAL_BYTES
          ) {
            throw new Error(`Archive entry ${name} exceeds the size safety limit.`);
          }
          if (
            !name.endsWith('/') &&
            entry.uncompressedSize / Math.max(entry.compressedSize, 1) > MAX_ARCHIVE_COMPRESSION_RATIO
          ) {
            throw new Error(`Archive entry ${name} exceeds the compression ratio limit.`);
          }
          if (isUnixSymlink(entry)) throw new Error(`Archive entry ${name} must not be a Unix symlink.`);

          const row = required.get(name);
          if (!row) {
            archive.readEntry();
            return;
          }
          if (name.endsWith('/') || extracted.has(name)) {
            throw new Error(`Archive target ${name} is not one unique regular file.`);
          }
          const destination = resolve(
            temporaryRoot,
            `${String(extracted.size).padStart(2, '0')}-${row.id}.exe`,
          );
          void writeArchiveEntryToControlledFile(archive, entry, row, destination).then(() => {
            extracted.set(name, destination);
            archive.readEntry();
          }, reject);
        } catch (error) {
          reject(error);
        }
      });
      archive.once('end', () => {
        if (settled) return;
        const missing = rows.filter((row) => !extracted.has(row.entryPath));
        if (missing.length > 0) {
          reject(
            new Error(
              `Archive is missing signature matrix targets: ${missing.map(({ id }) => id).join(', ')}`,
            ),
          );
          return;
        }
        settled = true;
        resolveEntries();
      });
      archive.readEntry();
    });
  } finally {
    archive.close();
  }
  return extracted;
}

async function verifyArchiveTargets(
  archiveIdentity,
  rows,
  temporaryRoot,
  signatureRunner,
  expectedThumbprint,
) {
  const opened = await openPlainSingleLinkFile(
    archiveIdentity.path,
    `Signature archive ${archiveIdentity.path}`,
  );
  try {
    const before = await readOpenedFile(opened.handle);
    if (before.sha256 !== archiveIdentity.sha256 || before.sizeBytes !== archiveIdentity.sizeBytes) {
      throw new Error(`Signature archive ${archiveIdentity.path} SHA-256 or size does not match the plan.`);
    }
    const extracted = await extractArchiveTargets(opened, rows, temporaryRoot);
    const results = [];
    for (const row of rows) {
      results.push(
        await verifyStagedSignatureTarget(
          row,
          extracted.get(row.entryPath),
          signatureRunner,
          expectedThumbprint,
        ),
      );
    }
    await assertOpenedFileUnchanged(
      opened,
      archiveIdentity.sha256,
      archiveIdentity.sizeBytes,
      `Signature archive ${archiveIdentity.path}`,
    );
    return results;
  } finally {
    await opened.handle.close();
  }
}

const POWERSHELL_AUTHENTICODE_SCRIPT = String.raw`
$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$signature = Get-AuthenticodeSignature -LiteralPath ([string]$payload.path)
[pscustomobject]@{
  status = [string]$signature.Status
  signerThumbprint = if ($null -eq $signature.SignerCertificate) { $null } else { [string]$signature.SignerCertificate.Thumbprint }
  timeStamperCertificatePresent = $null -ne $signature.TimeStamperCertificate
} | ConvertTo-Json -Compress
`;

export function runWindowsAuthenticodeSignature(path) {
  if (process.platform !== 'win32') {
    return Promise.reject(new Error('Windows Authenticode verification requires a Windows runner.'));
  }
  const target = assertAbsoluteNormalizedPath(path, 'The Authenticode target');
  return new Promise((resolveSignature, rejectSignature) => {
    const child = spawn(
      'powershell.exe',
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', POWERSHELL_AUTHENTICODE_SCRIPT],
      {
        shell: false,
        stdio: ['pipe', 'pipe', 'pipe'],
        timeout: 60_000,
        windowsHide: true,
      },
    );
    const stdout = [];
    const stderr = [];
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let outputError;
    const collect = (chunks, chunk, kind) => {
      const nextSize = kind === 'stdout' ? (stdoutBytes += chunk.length) : (stderrBytes += chunk.length);
      if (nextSize > MAX_POWERSHELL_OUTPUT_BYTES) {
        outputError = new Error(`PowerShell ${kind} exceeded the bounded output limit.`);
        child.kill();
        return;
      }
      chunks.push(chunk);
    };
    child.stdout.on('data', (chunk) => collect(stdout, chunk, 'stdout'));
    child.stderr.on('data', (chunk) => collect(stderr, chunk, 'stderr'));
    child.stdin.once('error', rejectSignature);
    child.once('error', rejectSignature);
    child.once('close', (code, signal) => {
      if (outputError) {
        rejectSignature(outputError);
        return;
      }
      if (code !== 0) {
        rejectSignature(
          new Error(
            `PowerShell Authenticode inspection failed (${code ?? signal ?? 'unknown'}): ${Buffer.concat(stderr).toString('utf8').trim()}`,
          ),
        );
        return;
      }
      try {
        resolveSignature(JSON.parse(Buffer.concat(stdout).toString('utf8')));
      } catch (error) {
        rejectSignature(new Error('PowerShell returned malformed Authenticode JSON.', { cause: error }));
      }
    });
    child.stdin.end(JSON.stringify({ path: target }));
  });
}

export async function verifyWindowsAuthenticodePlan({
  planPath,
  expectedPlanSha256,
  expectedThumbprint,
  phases,
  installRoot,
  signatureRunner = runWindowsAuthenticodeSignature,
}) {
  const normalizedPhases = normalizePhases(phases);
  const signerThumbprint = normalizeWindowsCertificateThumbprint(expectedThumbprint);
  if (typeof signatureRunner !== 'function') throw new Error('An Authenticode signature runner is required.');
  const planSnapshot = await readAndVerifyPlan(planPath, expectedPlanSha256);
  let temporaryScope;
  try {
    const validated = validateWindowsUpgradePlan(planSnapshot.parsed);
    const selectedRows = MATRIX_AUTHORITIES.filter(({ phase }) => normalizedPhases.includes(phase)).map(
      ({ id }) => validated.rows.get(id),
    );
    temporaryScope = await createControlledTemporaryRoot();
    let canonicalInstallRoot;
    if (normalizedPhases.includes('post-upgrade')) {
      canonicalInstallRoot = await realpath(assertAbsoluteNormalizedPath(installRoot, 'The install root'));
      if (!samePath(canonicalInstallRoot, resolve(installRoot))) {
        throw new Error('The install root must not traverse a symbolic link, junction, or reparse point.');
      }
    }

    const results = new Map();
    for (const row of selectedRows.filter(({ phase }) => phase !== 'archive')) {
      const path =
        row.phase === 'post-upgrade'
          ? resolve(
              canonicalInstallRoot,
              assertSafeRelativePath(row.relativePath, `Signature target ${row.id}`),
            )
          : row.path;
      if (row.phase === 'post-upgrade' && !samePath(resolve(canonicalInstallRoot, row.relativePath), path)) {
        throw new Error(`Signature target ${row.id} escapes the install root.`);
      }
      results.set(
        row.id,
        await verifyPathTarget(row, path, temporaryScope.path, signatureRunner, signerThumbprint),
      );
    }

    const archiveRows = selectedRows.filter(({ phase }) => phase === 'archive');
    if (archiveRows.length > 0) {
      for (const archiveIdentity of [validated.zip, validated.nupkg]) {
        const rows = archiveRows.filter((row) => samePath(row.archivePath, archiveIdentity.path));
        if (rows.length === 0) continue;
        for (const result of await verifyArchiveTargets(
          archiveIdentity,
          rows,
          temporaryScope.path,
          signatureRunner,
          signerThumbprint,
        )) {
          results.set(result.id, result);
        }
      }
    }

    await assertOpenedFileUnchanged(
      planSnapshot.opened,
      planSnapshot.rawSha256,
      planSnapshot.sizeBytes,
      'The Windows upgrade plan',
    );
    return Object.freeze({
      schemaVersion: 1,
      planSha256: planSnapshot.rawSha256,
      signerThumbprint,
      phases: normalizedPhases,
      timestampRequired: true,
      verifiedTargets: Object.freeze(selectedRows.map(({ id }) => results.get(id))),
    });
  } finally {
    try {
      if (temporaryScope) await removeControlledTemporaryRoot(temporaryScope);
    } finally {
      await planSnapshot.opened.handle.close();
    }
  }
}

export function parseWindowsAuthenticodeCliArguments(arguments_) {
  if (!Array.isArray(arguments_) || !arguments_.every((argument) => typeof argument === 'string')) {
    throw new Error('CLI arguments must be strings.');
  }
  const valuedOptions = new Set([
    'plan',
    'expected-plan-sha256',
    'expected-thumbprint',
    'phases',
    'install-root',
  ]);
  const values = new Map();
  let requireTimestamp = false;
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (argument === '--require-timestamp') {
      if (requireTimestamp) throw new Error('Duplicate --require-timestamp flag.');
      requireTimestamp = true;
      continue;
    }
    const match = /^--([^=]+)(?:=(.*))?$/u.exec(argument);
    if (!match || !valuedOptions.has(match[1])) {
      throw new Error(`Unsupported Authenticode verifier argument: ${argument}`);
    }
    const name = match[1];
    if (values.has(name)) throw new Error(`Duplicate --${name} argument.`);
    const value = match[2] ?? arguments_[++index];
    if (!value || value.startsWith('--')) throw new Error(`Missing --${name} value.`);
    values.set(name, value);
  }
  if (!requireTimestamp) {
    throw new Error('Stable Authenticode verification requires the --require-timestamp flag.');
  }
  for (const name of ['plan', 'expected-plan-sha256', 'expected-thumbprint', 'phases']) {
    if (!values.has(name)) throw new Error(`Missing --${name} argument.`);
  }
  const phases = values.get('phases').split(',');
  const hasPostUpgrade = phases.includes('post-upgrade');
  if (hasPostUpgrade !== values.has('install-root')) {
    throw new Error(
      hasPostUpgrade
        ? 'The post-upgrade phase requires --install-root.'
        : '--install-root is allowed only for the post-upgrade phase.',
    );
  }
  const planPath = values.get('plan');
  const expectedPlanSha256 = values.get('expected-plan-sha256');
  const expectedThumbprint = values.get('expected-thumbprint');
  const installRoot = values.get('install-root');
  return Object.freeze({ planPath, expectedPlanSha256, expectedThumbprint, phases, installRoot });
}

async function runCli() {
  const result = await verifyWindowsAuthenticodePlan(
    parseWindowsAuthenticodeCliArguments(process.argv.slice(2)),
  );
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await runCli();
}
