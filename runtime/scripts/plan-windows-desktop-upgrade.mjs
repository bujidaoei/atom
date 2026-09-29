import { Buffer } from 'node:buffer';
import { createHash } from 'node:crypto';
import { lstat, mkdtemp, open, readFile, realpath, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { Readable } from 'node:stream';
import { pathToFileURL } from 'node:url';

import yauzl from 'yauzl';

const VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-beta\.(0|[1-9]\d*))?$/u;
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const MAX_SAFE_VERSION_PART = BigInt(Number.MAX_SAFE_INTEGER);
const MAX_ARCHIVE_ENTRY_COUNT = 4_096;
const MAX_ARCHIVE_TARGET_SIZE_BYTES = 512 * 1024 * 1024;
const MAX_ARCHIVE_TARGET_COMPRESSION_RATIO = 200;
const PLAN_OUTPUT_DIRECTORY_PREFIX = 'workdude-windows-upgrade-plan-';

function samePath(first, second) {
  return process.platform === 'win32' ? first.toLowerCase() === second.toLowerCase() : first === second;
}

function parseWindowsDesktopVersion(version) {
  const match = VERSION_PATTERN.exec(version);
  if (!match) {
    throw new Error('Windows Desktop versions must use X.Y.Z or X.Y.Z-beta.N syntax.');
  }
  const parts = match.slice(1).map((part) => (part === undefined ? undefined : BigInt(part)));
  if (parts.some((part) => part !== undefined && part > MAX_SAFE_VERSION_PART)) {
    throw new Error('Windows Desktop version components must be safe integers.');
  }
  return parts;
}

export function compareWindowsDesktopVersions(first, second) {
  const left = parseWindowsDesktopVersion(first);
  const right = parseWindowsDesktopVersion(second);
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) return left[index] < right[index] ? -1 : 1;
  }
  if (left[3] === undefined && right[3] === undefined) return 0;
  if (left[3] === undefined) return 1;
  if (right[3] === undefined) return -1;
  if (left[3] === right[3]) return 0;
  return left[3] < right[3] ? -1 : 1;
}

function sameFileIdentity(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.size === second.size &&
    first.mtimeMs === second.mtimeMs &&
    first.ctimeMs === second.ctimeMs &&
    first.nlink === second.nlink
  );
}

async function openPlainFileSnapshot(path, label) {
  const absolute = resolve(path);
  const canonical = await realpath(absolute);
  if (!samePath(absolute, canonical)) {
    throw new Error(`${label} must not traverse a symbolic link, junction, or reparse point.`);
  }
  const handle = await open(canonical, 'r');
  try {
    const before = await handle.stat();
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1) {
      throw new Error(`${label} must be a plain single-link file.`);
    }
    const hash = createHash('sha256');
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    let position = 0;
    while (position < before.size) {
      const { bytesRead } = await handle.read(
        buffer,
        0,
        Math.min(buffer.length, before.size - position),
        position,
      );
      if (bytesRead === 0) throw new Error(`${label} ended while it was being verified.`);
      hash.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
    const after = await handle.stat();
    if (!sameFileIdentity(before, after)) {
      throw new Error(`${label} changed while it was being verified.`);
    }
    return Object.freeze({
      handle,
      label,
      stat: after,
      snapshot: Object.freeze({ path: canonical, sha256: hash.digest('hex'), sizeBytes: after.size }),
    });
  } catch (error) {
    await handle.close();
    throw error;
  }
}

async function assertOpenFileUnchanged(file) {
  const [handleStat, pathStat, canonical] = await Promise.all([
    file.handle.stat(),
    stat(file.snapshot.path),
    realpath(file.snapshot.path),
  ]);
  if (
    !samePath(canonical, file.snapshot.path) ||
    !sameFileIdentity(file.stat, handleStat) ||
    !sameFileIdentity(file.stat, pathStat) ||
    !handleStat.isFile() ||
    handleStat.isSymbolicLink() ||
    handleStat.nlink !== 1
  ) {
    throw new Error(`${file.label} changed while the upgrade plan was being created.`);
  }
}

async function withOpenPlainFileSnapshots(files, createPlan) {
  const opened = [];
  try {
    for (const file of files) {
      opened.push(Object.freeze({ ...(await openPlainFileSnapshot(file.path, file.label)), id: file.id }));
    }
    const plan = await createPlan(Object.fromEntries(opened.map((file) => [file.id, file])));
    await Promise.all(opened.map(assertOpenFileUnchanged));
    return plan;
  } finally {
    await Promise.allSettled(opened.map((file) => file.handle.close()));
  }
}

export function canonicalizeWindowsDesktopUpgradePlan(value) {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalizeWindowsDesktopUpgradePlan).join(',')}]`;
  }
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value)
      .sort()
      .map(
        (key) => `${JSON.stringify(key)}:${canonicalizeWindowsDesktopUpgradePlan(Reflect.get(value, key))}`,
      )
      .join(',')}}`;
  }
  const serialized = JSON.stringify(value);
  if (serialized === undefined) throw new Error('The Windows Desktop upgrade plan is not JSON-safe.');
  return serialized;
}

function safeArchiveEntryName(name) {
  if (!name || name.includes('\\') || name.includes('\0') || name.includes(':') || name.startsWith('/')) {
    return false;
  }
  const normalized = name.endsWith('/') ? name.slice(0, -1) : name;
  return (
    Boolean(normalized) &&
    normalized.split('/').every((segment) => {
      if (!segment || segment === '.' || segment === '..' || segment.endsWith('.') || segment.endsWith(' ')) {
        return false;
      }
      const deviceBase = segment
        .split('.')[0]
        .replace(/[ .]+$/gu, '')
        .toUpperCase();
      return !/^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/u.test(deviceBase);
    })
  );
}

function unixFileType(entry) {
  return (entry.externalFileAttributes >>> 16) & 0o170000;
}

function validateArchiveTargetBounds(entry, label) {
  if (entry.uncompressedSize > MAX_ARCHIVE_TARGET_SIZE_BYTES) {
    throw new Error(`${label} entry exceeds the single-target extraction size limit: ${entry.fileName}`);
  }
  if (
    entry.uncompressedSize > 0 &&
    (entry.compressedSize === 0 ||
      entry.uncompressedSize / entry.compressedSize > MAX_ARCHIVE_TARGET_COMPRESSION_RATIO)
  ) {
    throw new Error(`${label} entry exceeds the compression-ratio limit: ${entry.fileName}`);
  }
}

class OpenFileRandomAccessReader extends yauzl.RandomAccessReader {
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
          const buffer = Buffer.allocUnsafe(Math.min(1024 * 1024, end - position));
          const { bytesRead } = await handle.read(buffer, 0, buffer.length, position);
          if (bytesRead === 0) throw new Error('The archive ended while an entry was being read.');
          yield buffer.subarray(0, bytesRead);
          position += bytesRead;
        }
      })(),
    );
  }
}

function archiveTargetSnapshots(file, requiredEntries, label) {
  return new Promise((resolveArchive, rejectArchive) => {
    yauzl.fromRandomAccessReader(
      new OpenFileRandomAccessReader(file.handle),
      file.stat.size,
      {
        autoClose: true,
        decodeStrings: true,
        lazyEntries: true,
        // Legacy Squirrel NUPKGs use Windows separators. yauzl normalizes them to
        // '/' before its absolute/traversal checks when strictFileNames is false;
        // the normalized name still passes our stricter Windows-safe path gate.
        strictFileNames: false,
        validateEntrySizes: true,
      },
      (openError, archive) => {
        if (openError || !archive) {
          rejectArchive(new Error(`${label} could not be opened as a ZIP archive.`, { cause: openError }));
          return;
        }
        const required = new Set(requiredEntries);
        const found = new Map();
        const seen = new Set();
        let entryCount = 0;
        let settled = false;
        const reject = (error) => {
          if (settled) return;
          settled = true;
          archive.close();
          rejectArchive(error);
        };
        archive.on('error', (error) => reject(error));
        archive.on('entry', (entry) => {
          entryCount += 1;
          const name = entry.fileName;
          const folded = name.normalize('NFKC').toLowerCase();
          if (entryCount > MAX_ARCHIVE_ENTRY_COUNT) {
            reject(new Error(`${label} exceeds the archive entry-count limit.`));
            return;
          }
          if (!safeArchiveEntryName(name)) {
            reject(new Error(`${label} contains an unsafe entry: ${name}`));
            return;
          }
          if (unixFileType(entry) === 0o120000) {
            reject(new Error(`${label} contains a Unix symbolic-link entry: ${name}`));
            return;
          }
          if (seen.has(folded)) {
            reject(new Error(`${label} contains a duplicate or case-conflicting entry: ${name}`));
            return;
          }
          seen.add(folded);
          if (name.endsWith('/') || !required.has(name)) {
            archive.readEntry();
            return;
          }
          try {
            validateArchiveTargetBounds(entry, label);
          } catch (error) {
            reject(error);
            return;
          }
          archive.openReadStream(entry, (streamError, stream) => {
            if (streamError || !stream) {
              reject(new Error(`${label} entry could not be read: ${name}`, { cause: streamError }));
              return;
            }
            const hash = createHash('sha256');
            let sizeBytes = 0;
            stream.on('data', (chunk) => {
              hash.update(chunk);
              sizeBytes += chunk.length;
              if (sizeBytes > MAX_ARCHIVE_TARGET_SIZE_BYTES) {
                stream.destroy(
                  new Error(`${label} entry exceeds the single-target extraction size limit: ${name}`),
                );
              }
            });
            stream.once('error', reject);
            stream.once('end', () => {
              found.set(
                name,
                Object.freeze({
                  entryPath: name,
                  sha256: hash.digest('hex'),
                  sizeBytes,
                  compressedSizeBytes: entry.compressedSize,
                }),
              );
              archive.readEntry();
            });
          });
        });
        archive.on('end', () => {
          if (settled) return;
          const missing = requiredEntries.filter((name) => !found.has(name));
          if (missing.length > 0) {
            reject(new Error(`${label} is missing required entries: ${missing.join(', ')}`));
            return;
          }
          settled = true;
          archive.close();
          resolveArchive(found);
        });
        archive.readEntry();
      },
    );
  });
}

function requiredArgument(args, name) {
  const prefix = `--${name}=`;
  const matches = args.filter((item) => item.startsWith(prefix));
  if (matches.length > 1) throw new Error(`Duplicate --${name} argument.`);
  const value = matches[0]?.slice(prefix.length);
  if (!value) throw new Error(`Missing ${prefix}<value>`);
  return value;
}

function optionalArgument(args, name) {
  const prefix = `--${name}=`;
  const matches = args.filter((item) => item.startsWith(prefix));
  if (matches.length > 1) throw new Error(`Duplicate --${name} argument.`);
  const value = matches[0]?.slice(prefix.length);
  if (matches.length === 1 && !value) throw new Error(`Missing ${prefix}<value>`);
  return value;
}

function sameDirectoryIdentity(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.birthtimeMs === second.birthtimeMs &&
    first.mode === second.mode
  );
}

async function plainOutputDirectory(path, label) {
  if (!isAbsolute(path) || !samePath(resolve(path), path)) {
    throw new Error(`${label} must be an absolute normalized directory.`);
  }
  const canonical = await realpath(path);
  const identity = await lstat(canonical);
  if (!samePath(canonical, path) || !identity.isDirectory() || identity.isSymbolicLink()) {
    throw new Error(`${label} must be one plain directory without a reparse point.`);
  }
  return Object.freeze({ path: canonical, identity });
}

export async function writeWindowsDesktopUpgradePlanFile(plan, { outputRoot = tmpdir() } = {}) {
  if (
    !plan ||
    typeof plan !== 'object' ||
    plan.executionAllowed !== false ||
    plan.integrity?.algorithm !== 'sha256' ||
    !SHA256_PATTERN.test(plan.integrity?.planSha256 ?? '')
  ) {
    throw new Error('Only one verified non-executing Windows upgrade plan may be written.');
  }
  const { integrity, ...unsignedPlan } = plan;
  const canonicalPlanSha256 = createHash('sha256')
    .update(canonicalizeWindowsDesktopUpgradePlan(unsignedPlan), 'utf8')
    .digest('hex');
  if (canonicalPlanSha256 !== integrity.planSha256) {
    throw new Error('The Windows upgrade plan canonical integrity changed before output.');
  }

  const parent = await plainOutputDirectory(outputRoot, 'The Windows upgrade plan output root');
  const directoryPath = await mkdtemp(join(parent.path, PLAN_OUTPUT_DIRECTORY_PREFIX));
  const directory = await plainOutputDirectory(directoryPath, 'The Windows upgrade plan directory');
  if (
    !samePath(dirname(directory.path), parent.path) ||
    !basename(directory.path).startsWith(PLAN_OUTPUT_DIRECTORY_PREFIX) ||
    basename(directory.path).length === PLAN_OUTPUT_DIRECTORY_PREFIX.length
  ) {
    throw new Error('The Windows upgrade plan directory is outside the owned output root.');
  }

  const raw = `${JSON.stringify(plan, null, 2)}\n`;
  const planPath = resolve(directory.path, 'upgrade-plan.json');
  const output = await open(planPath, 'wx', 0o600);
  try {
    await output.writeFile(raw, 'utf8');
    await output.sync();
  } finally {
    await output.close();
  }
  const snapshot = await openPlainFileSnapshot(planPath, 'The written Windows upgrade plan');
  try {
    const reboundParent = await plainOutputDirectory(parent.path, 'The Windows upgrade plan output root');
    const reboundDirectory = await plainOutputDirectory(directory.path, 'The Windows upgrade plan directory');
    if (
      !sameDirectoryIdentity(parent.identity, reboundParent.identity) ||
      !sameDirectoryIdentity(directory.identity, reboundDirectory.identity) ||
      snapshot.snapshot.sha256 !== createHash('sha256').update(raw, 'utf8').digest('hex') ||
      snapshot.snapshot.sizeBytes !== Buffer.byteLength(raw, 'utf8')
    ) {
      throw new Error('The written Windows upgrade plan identity changed before handoff.');
    }
    await assertOpenFileUnchanged(snapshot);
    const installedUpdater = plan.signatureMatrix.find(({ id }) => id === 'installed-update');
    if (!installedUpdater || !SHA256_PATTERN.test(installedUpdater.sha256)) {
      throw new Error('The Windows upgrade plan lacks one installed Updater SHA-256 identity.');
    }
    return Object.freeze({
      executionAllowed: false,
      planPath: snapshot.snapshot.path,
      planSha256: snapshot.snapshot.sha256,
      canonicalPlanSha256,
      currentSetupSha256: plan.current.setup.sha256,
      currentUpdaterSha256: installedUpdater.sha256,
    });
  } finally {
    await snapshot.handle.close();
  }
}

export async function createWindowsDesktopUpgradePlan({
  repositoryRoot = process.cwd(),
  previousInstallerPath,
  previousVersion,
  previousSha256,
}) {
  if (
    !isAbsolute(previousInstallerPath) ||
    previousInstallerPath.split(/[\\/]/u).some((segment) => segment === '.' || segment === '..') ||
    !samePath(resolve(previousInstallerPath), previousInstallerPath)
  ) {
    throw new Error('The previous Windows Setup path must be absolute and normalized.');
  }
  if (!SHA256_PATTERN.test(previousSha256)) {
    throw new Error('The previous Windows Setup SHA-256 must be 64 lowercase hexadecimal characters.');
  }

  const root = await realpath(resolve(repositoryRoot));
  const [rootPackage, desktopPackage] = await Promise.all([
    readFile(resolve(root, 'package.json'), 'utf8').then(JSON.parse),
    readFile(resolve(root, 'apps/desktop/package.json'), 'utf8').then(JSON.parse),
  ]);
  if (rootPackage.version !== desktopPackage.version) {
    throw new Error('Root and Desktop package versions must match one supported version.');
  }
  const currentVersion = desktopPackage.version;
  parseWindowsDesktopVersion(currentVersion);
  if (compareWindowsDesktopVersions(previousVersion, currentVersion) >= 0) {
    throw new Error('The previous Windows Desktop version must be strictly older than the current version.');
  }
  const expectedPreviousName = `QoderWake-${previousVersion}.Setup.exe`;
  if (basename(previousInstallerPath) !== expectedPreviousName) {
    throw new Error(`The previous Windows Setup name must be exactly ${expectedPreviousName}.`);
  }

  const squirrelVersion = currentVersion.replace('-beta.', '-beta');
  const current = {
    setup: resolve(root, `apps/desktop/out/make/squirrel.windows/x64/QoderWake-${currentVersion}.Setup.exe`),
    nupkg: resolve(
      root,
      `apps/desktop/out/make/squirrel.windows/x64/qoderwake-${squirrelVersion}-full.nupkg`,
    ),
    zip: resolve(root, `apps/desktop/out/make/zip/win32/x64/QoderWake-win32-x64-${currentVersion}.zip`),
    packageRoot: resolve(root, 'apps/desktop/out/QoderWake-win32-x64'),
  };
  const packagedMainPath = resolve(current.packageRoot, 'QoderWake.exe');
  const packagedNativeHostPath = resolve(current.packageRoot, 'resources/QoderWakeBrowserNativeHost.exe');
  const packagedUninstallHelperPath = resolve(current.packageRoot, 'resources/QoderWakeUninstallCleanup.exe');
  return withOpenPlainFileSnapshots(
    [
      { id: 'previousSetup', path: previousInstallerPath, label: 'The previous Windows Setup' },
      { id: 'currentSetup', path: current.setup, label: 'The current Windows Setup' },
      { id: 'currentNupkg', path: current.nupkg, label: 'The current Windows NUPKG' },
      { id: 'currentZip', path: current.zip, label: 'The current Windows ZIP' },
      { id: 'packagedMain', path: packagedMainPath, label: 'The packaged Windows application' },
      {
        id: 'packagedNativeHost',
        path: packagedNativeHostPath,
        label: 'The packaged Windows Browser Native Host',
      },
      {
        id: 'packagedUninstallHelper',
        path: packagedUninstallHelperPath,
        label: 'The packaged Windows uninstall cleanup helper',
      },
    ],
    async (files) => {
      const previousSetup = files.previousSetup.snapshot;
      const currentSetup = files.currentSetup.snapshot;
      const currentNupkg = files.currentNupkg.snapshot;
      const currentZip = files.currentZip.snapshot;
      const packagedMain = files.packagedMain.snapshot;
      const packagedNativeHost = files.packagedNativeHost.snapshot;
      const packagedUninstallHelper = files.packagedUninstallHelper.snapshot;
      if (previousSetup.sha256 !== previousSha256) {
        throw new Error('The previous Windows Setup SHA-256 does not match the supplied identity.');
      }
      if (samePath(previousSetup.path, currentSetup.path) || previousSetup.sha256 === currentSetup.sha256) {
        throw new Error('Previous and current Windows Setup identities must be distinct.');
      }
      if (basename(previousSetup.path) !== expectedPreviousName) {
        throw new Error(`The previous Windows Setup name must be exactly ${expectedPreviousName}.`);
      }

      const [zipEntries, nupkgEntries] = await Promise.all([
        archiveTargetSnapshots(
          files.currentZip,
          [
            'QoderWake.exe',
            'resources/QoderWakeBrowserNativeHost.exe',
            'resources/QoderWakeUninstallCleanup.exe',
          ],
          'The current Windows ZIP',
        ),
        archiveTargetSnapshots(
          files.currentNupkg,
          [
            'lib/net45/QoderWake.exe',
            'lib/net45/QoderWake_ExecutionStub.exe',
            'lib/net45/resources/QoderWakeBrowserNativeHost.exe',
            'lib/net45/resources/QoderWakeUninstallCleanup.exe',
            'lib/net45/squirrel.exe',
          ],
          'The current Windows NUPKG',
        ),
      ]);
      for (const [entry, expected] of [
        [zipEntries.get('QoderWake.exe'), packagedMain],
        [zipEntries.get('resources/QoderWakeBrowserNativeHost.exe'), packagedNativeHost],
        [zipEntries.get('resources/QoderWakeUninstallCleanup.exe'), packagedUninstallHelper],
        [nupkgEntries.get('lib/net45/QoderWake.exe'), packagedMain],
        [nupkgEntries.get('lib/net45/resources/QoderWakeBrowserNativeHost.exe'), packagedNativeHost],
        [nupkgEntries.get('lib/net45/resources/QoderWakeUninstallCleanup.exe'), packagedUninstallHelper],
      ]) {
        if (entry.sha256 !== expected.sha256 || entry.sizeBytes !== expected.sizeBytes) {
          throw new Error(
            `A Windows archive executable does not match its packaged source: ${entry.entryPath}`,
          );
        }
      }
      const executionStub = nupkgEntries.get('lib/net45/QoderWake_ExecutionStub.exe');
      const updater = nupkgEntries.get('lib/net45/squirrel.exe');
      const archiveTarget = (archive, entry) =>
        Object.freeze({
          archivePath: archive.path,
          archiveSha256: archive.sha256,
          archiveSizeBytes: archive.sizeBytes,
          ...entry,
        });

      const unsignedPlan = Object.freeze({
        schemaVersion: 1,
        kind: 'windows-squirrel-in-place-upgrade',
        executionAllowed: false,
        previous: Object.freeze({ ...previousSetup, version: previousVersion }),
        current: Object.freeze({
          version: currentVersion,
          setup: currentSetup,
          nupkg: currentNupkg,
          zip: currentZip,
          packageRoot: current.packageRoot,
        }),
        phases: Object.freeze([
          'install-previous',
          'seed-authoritative-user-data-marker',
          'capture-previous-identity',
          'upgrade-current-without-uninstall',
          'verify-current-identity-and-launch',
          'uninstall-current',
          'verify-application-removal-and-user-data-retention',
        ]),
        signatureMatrix: Object.freeze([
          {
            id: 'previous-setup',
            phase: 'pre-upgrade',
            path: previousSetup.path,
            sha256: previousSetup.sha256,
            sizeBytes: previousSetup.sizeBytes,
          },
          {
            id: 'current-setup',
            phase: 'pre-install',
            path: currentSetup.path,
            sha256: currentSetup.sha256,
            sizeBytes: currentSetup.sizeBytes,
          },
          {
            id: 'packaged-main',
            phase: 'pre-install',
            path: packagedMain.path,
            sha256: packagedMain.sha256,
            sizeBytes: packagedMain.sizeBytes,
          },
          {
            id: 'packaged-native-host',
            phase: 'pre-install',
            path: packagedNativeHost.path,
            sha256: packagedNativeHost.sha256,
            sizeBytes: packagedNativeHost.sizeBytes,
          },
          {
            id: 'packaged-uninstall-helper',
            phase: 'pre-install',
            path: packagedUninstallHelper.path,
            sha256: packagedUninstallHelper.sha256,
            sizeBytes: packagedUninstallHelper.sizeBytes,
          },
          {
            id: 'zip-main',
            phase: 'archive',
            ...archiveTarget(currentZip, zipEntries.get('QoderWake.exe')),
          },
          {
            id: 'zip-native-host',
            phase: 'archive',
            ...archiveTarget(currentZip, zipEntries.get('resources/QoderWakeBrowserNativeHost.exe')),
          },
          {
            id: 'zip-uninstall-helper',
            phase: 'archive',
            ...archiveTarget(currentZip, zipEntries.get('resources/QoderWakeUninstallCleanup.exe')),
          },
          {
            id: 'nupkg-main',
            phase: 'archive',
            ...archiveTarget(currentNupkg, nupkgEntries.get('lib/net45/QoderWake.exe')),
          },
          {
            id: 'nupkg-execution-stub',
            phase: 'archive',
            ...archiveTarget(currentNupkg, executionStub),
          },
          {
            id: 'nupkg-native-host',
            phase: 'archive',
            ...archiveTarget(
              currentNupkg,
              nupkgEntries.get('lib/net45/resources/QoderWakeBrowserNativeHost.exe'),
            ),
          },
          {
            id: 'nupkg-uninstall-helper',
            phase: 'archive',
            ...archiveTarget(
              currentNupkg,
              nupkgEntries.get('lib/net45/resources/QoderWakeUninstallCleanup.exe'),
            ),
          },
          {
            id: 'nupkg-updater',
            phase: 'archive',
            ...archiveTarget(currentNupkg, updater),
          },
          {
            id: 'installed-update',
            phase: 'post-upgrade',
            relativePath: 'Update.exe',
            sha256: updater.sha256,
            sizeBytes: updater.sizeBytes,
          },
          {
            id: 'installed-launcher',
            phase: 'post-upgrade',
            relativePath: 'QoderWake.exe',
            sha256: executionStub.sha256,
            sizeBytes: executionStub.sizeBytes,
          },
          {
            id: 'installed-main',
            phase: 'post-upgrade',
            relativePath: `app-${squirrelVersion}/QoderWake.exe`,
            sha256: packagedMain.sha256,
            sizeBytes: packagedMain.sizeBytes,
          },
          {
            id: 'installed-native-host',
            phase: 'post-upgrade',
            relativePath: `app-${squirrelVersion}/resources/QoderWakeBrowserNativeHost.exe`,
            sha256: packagedNativeHost.sha256,
            sizeBytes: packagedNativeHost.sizeBytes,
          },
          {
            id: 'installed-uninstall-helper',
            phase: 'post-upgrade',
            relativePath: `app-${squirrelVersion}/resources/QoderWakeUninstallCleanup.exe`,
            sha256: packagedUninstallHelper.sha256,
            sizeBytes: packagedUninstallHelper.sizeBytes,
          },
        ]),
        retention: Object.freeze({
          authority: 'real-product-data',
          manualMarkerIsInsufficient: true,
          sameUserDataBeforeAndAfterUpgrade: true,
        }),
        smartScreen: Object.freeze({ status: 'external-required', substitutedByAuthenticode: false }),
      });
      const planSha256 = createHash('sha256')
        .update(canonicalizeWindowsDesktopUpgradePlan(unsignedPlan), 'utf8')
        .digest('hex');
      return Object.freeze({
        ...unsignedPlan,
        integrity: Object.freeze({ algorithm: 'sha256', planSha256 }),
      });
    },
  );
}

async function runCli() {
  const arguments_ = process.argv.slice(2);
  const plan = await createWindowsDesktopUpgradePlan({
    previousInstallerPath: requiredArgument(arguments_, 'previous-installer'),
    previousVersion: requiredArgument(arguments_, 'previous-version'),
    previousSha256: requiredArgument(arguments_, 'previous-sha256'),
  });
  const outputRoot = optionalArgument(arguments_, 'secure-output-root');
  const output = outputRoot ? await writeWindowsDesktopUpgradePlanFile(plan, { outputRoot }) : plan;
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await runCli();
}
