import { Buffer } from 'node:buffer';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { lstat, mkdir, mkdtemp, open, realpath, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

export function runWindowsProcess(executable, args, options = {}) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(executable, args, {
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      ...options,
    });
    let stdout = '';
    let stderr = '';
    child.stdout?.setEncoding('utf8');
    child.stderr?.setEncoding('utf8');
    child.stdout?.on('data', (chunk) => (stdout += chunk));
    child.stderr?.on('data', (chunk) => (stderr += chunk));
    child.once('error', rejectRun);
    child.once('exit', (code, signal) => resolveRun({ child, code, signal, stdout, stderr }));
  });
}

export async function pathExistsFailClosed(path, inspect = lstat) {
  try {
    await inspect(path);
    return true;
  } catch (error) {
    if (error && typeof error === 'object' && Reflect.get(error, 'code') === 'ENOENT') return false;
    throw error;
  }
}

function samePath(first, second) {
  return first.toLowerCase() === second.toLowerCase();
}

async function plainDirectoryIdentity(path, label) {
  const absolute = resolve(path);
  const entry = await lstat(absolute);
  if (!entry.isDirectory() || entry.isSymbolicLink()) {
    throw new Error(`${label} must be a plain directory without a reparse point.`);
  }
  const canonical = await realpath(absolute);
  if (!samePath(absolute, canonical)) {
    throw new Error(`${label} must not traverse a symbolic link, junction, or reparse point.`);
  }
  const current = await lstat(canonical);
  if (
    !current.isDirectory() ||
    current.isSymbolicLink() ||
    current.dev !== entry.dev ||
    current.ino !== entry.ino
  ) {
    throw new Error(`${label} identity changed while it was resolved.`);
  }
  return Object.freeze({ path: canonical, identity: `${current.dev}:${current.ino}` });
}

async function plainDirectory(path, label) {
  return (await plainDirectoryIdentity(path, label)).path;
}

async function removeOwnedTemporaryDirectory(path, expected, label) {
  const current = await plainDirectoryIdentity(path, label);
  if (!samePath(current.path, expected.path) || current.identity !== expected.identity) {
    throw new Error(`${label} ownership identity changed before removal.`);
  }
  await rm(current.path, { recursive: true, force: true, maxRetries: 20, retryDelay: 250 });
}

function fileIdentityKey(entry) {
  return `${entry.dev}:${entry.ino}:${entry.size}:${entry.mtimeMs}`;
}

export async function plainFileIdentity(path, label) {
  const absolute = resolve(path);
  const entry = await lstat(absolute);
  if (!entry.isFile() || entry.isSymbolicLink() || entry.nlink !== 1) {
    throw new Error(`${label} must be a plain single-link file.`);
  }
  const canonical = await realpath(absolute);
  if (!samePath(absolute, canonical)) {
    throw new Error(`${label} must not traverse a symbolic link, junction, or reparse point.`);
  }
  const handle = await open(canonical, 'r');
  try {
    const before = await handle.stat();
    if (!before.isFile() || before.nlink !== 1 || before.dev !== entry.dev || before.ino !== entry.ino) {
      throw new Error(`${label} identity changed while it was opened.`);
    }
    const hash = createHash('sha256');
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    let position = 0;
    while (true) {
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, position);
      if (bytesRead === 0) break;
      hash.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
    const after = await handle.stat();
    if (
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.size !== after.size ||
      before.mtimeMs !== after.mtimeMs
    ) {
      throw new Error(`${label} changed while it was hashed.`);
    }
    return Object.freeze({
      path: canonical,
      identity: fileIdentityKey(after),
      sha256: hash.digest('hex'),
      sizeBytes: after.size,
    });
  } finally {
    await handle.close();
  }
}

export async function assertOwnedFile(path, expected, label) {
  const current = await plainFileIdentity(path, label);
  if (
    !samePath(current.path, expected.path) ||
    current.identity !== expected.identity ||
    current.sha256 !== expected.sha256 ||
    current.sizeBytes !== expected.sizeBytes
  ) {
    throw new Error(`${label} ownership identity changed before execution.`);
  }
  return current;
}

async function stageOwnedExecutable(sourcePath, expected, temporaryRoot, rootIdentity, fileName, label) {
  const currentRoot = await plainDirectoryIdentity(temporaryRoot, 'The native lifecycle temporary root');
  if (
    currentRoot.identity !== rootIdentity.identity ||
    !samePath(currentRoot.path, rootIdentity.path) ||
    basename(fileName) !== fileName
  ) {
    throw new Error('Refusing to stage a Windows executable outside the owned lifecycle root.');
  }
  const destination = resolve(currentRoot.path, fileName);
  if (!samePath(resolve(destination, '..'), currentRoot.path)) {
    throw new Error('The staged Windows executable escaped the owned lifecycle root.');
  }

  const source = await open(expected.path, 'r');
  try {
    const before = await source.stat();
    if (!before.isFile() || before.nlink !== 1 || fileIdentityKey(before) !== expected.identity) {
      throw new Error(`${label} ownership identity changed before staging.`);
    }
    const output = await open(destination, 'wx+', 0o700);
    let digest;
    let sizeBytes = 0;
    try {
      const hash = createHash('sha256');
      const buffer = Buffer.allocUnsafe(1024 * 1024);
      while (sizeBytes < before.size) {
        const { bytesRead } = await source.read(
          buffer,
          0,
          Math.min(buffer.length, before.size - sizeBytes),
          sizeBytes,
        );
        if (bytesRead === 0) throw new Error(`${label} ended while it was being staged.`);
        const chunk = buffer.subarray(0, bytesRead);
        hash.update(chunk);
        await output.write(chunk, 0, bytesRead, sizeBytes);
        sizeBytes += bytesRead;
      }
      await output.sync();
      digest = hash.digest('hex');
    } finally {
      await output.close();
    }
    const after = await source.stat();
    if (
      fileIdentityKey(after) !== expected.identity ||
      digest !== expected.sha256 ||
      sizeBytes !== expected.sizeBytes
    ) {
      throw new Error(`${label} changed while it was being staged.`);
    }
  } finally {
    await source.close();
  }

  await assertOwnedFile(sourcePath, expected, label);
  const staged = await plainFileIdentity(destination, `The staged ${label}`);
  if (staged.sha256 !== expected.sha256 || staged.sizeBytes !== expected.sizeBytes) {
    throw new Error(`The staged ${label} does not match the approved bytes.`);
  }
  return staged;
}

async function windowsKnownFolders() {
  const command = [
    "$profile = [Environment]::GetFolderPath('UserProfile')",
    "$local = [Environment]::GetFolderPath('LocalApplicationData')",
    '[pscustomobject]@{ profile = $profile; localAppData = $local } | ConvertTo-Json -Compress',
  ].join('; ');
  const result = await runWindowsProcess('powershell.exe', [
    '-NoProfile',
    '-NonInteractive',
    '-Command',
    command,
  ]);
  if (result.code !== 0) {
    throw new Error(
      `Windows Known Folder resolution failed (${result.code ?? result.signal}): ${result.stderr.slice(-4_000)}`,
    );
  }
  const folders = JSON.parse(result.stdout);
  if (!folders?.profile || !folders?.localAppData) {
    throw new Error('Windows Known Folder resolution returned an invalid result.');
  }
  return folders;
}

export async function resolveDedicatedWindowsLifecycleScope() {
  if (process.platform !== 'win32') {
    throw new Error('The isolated native lifecycle helper requires Windows.');
  }
  const declaredProfile = process.env.WORKDUDE_WINDOWS_INSTALL_TEST_PROFILE_ROOT;
  if (!declaredProfile || !process.env.USERPROFILE || !process.env.LOCALAPPDATA) {
    throw new Error(
      'Windows native install/uninstall requires a dedicated test account and WORKDUDE_WINDOWS_INSTALL_TEST_PROFILE_ROOT.',
    );
  }
  const profileRoot = resolve(process.env.USERPROFILE);
  const localAppData = resolve(process.env.LOCALAPPDATA);
  const known = await windowsKnownFolders();
  const [canonicalProfile, canonicalLocalAppData] = await Promise.all([
    plainDirectory(profileRoot, 'The dedicated Windows profile'),
    plainDirectory(localAppData, 'The dedicated Windows LocalAppData'),
  ]);
  if (
    !samePath(resolve(declaredProfile), canonicalProfile) ||
    !samePath(resolve(known.profile), canonicalProfile) ||
    !samePath(resolve(known.localAppData), canonicalLocalAppData)
  ) {
    throw new Error('Windows native lifecycle refused a non-dedicated or forged Known Folder scope.');
  }
  const localRelative = relative(canonicalProfile, canonicalLocalAppData);
  if (!localRelative || isAbsolute(localRelative) || localRelative.startsWith('..')) {
    throw new Error('Windows LocalAppData must be a strict descendant of the dedicated profile.');
  }
  const profileMarker = resolve(canonicalProfile, '.workdude-dedicated-native-runner');
  const profileMarkerIdentity = await plainFileIdentity(
    profileMarker,
    'The dedicated Windows profile marker',
  );
  const expectedMarker = Buffer.from('workdude-dedicated-native-runner\n', 'utf8');
  if (
    profileMarkerIdentity.sizeBytes !== expectedMarker.length ||
    profileMarkerIdentity.sha256 !== createHash('sha256').update(expectedMarker).digest('hex')
  ) {
    throw new Error('Windows native lifecycle dedicated test-profile marker is invalid.');
  }
  return Object.freeze({
    profileRoot: canonicalProfile,
    localAppData: canonicalLocalAppData,
  });
}

async function waitForApplicationsRemoved(paths) {
  const deadline = Date.now() + 360_000;
  while (Date.now() < deadline) {
    if ((await Promise.all(paths.map((path) => pathExistsFailClosed(path)))).every((present) => !present))
      return;
    await delay(250);
  }
  const retained = [];
  for (const path of paths) if (await pathExistsFailClosed(path)) retained.push(path);
  throw new Error(`Windows uninstall retained application files: ${retained.join(', ')}`);
}

async function readWindowsUninstallResidue(installRoot, environment) {
  const command = [
    "$installRoot = [IO.Path]::GetFullPath($env:WORKDUDE_EXPECTED_INSTALL_ROOT).TrimEnd('\\')",
    "$installPrefix = $installRoot + '\\'",
    "$registryPaths = @('HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{5E9F36A2-7D55-4B89-9F5E-7E3D0A4D21C8}_is1', 'HKCU:\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.workdude.browser_connector', 'HKCU:\\Software\\Chromium\\NativeMessagingHosts\\com.workdude.browser_connector', 'HKCU:\\Software\\Microsoft\\Edge\\NativeMessagingHosts\\com.workdude.browser_connector')",
    '$registry = @($registryPaths | Where-Object { Test-Path -LiteralPath $_ })',
    "$shortcutPaths = @((Join-Path ([Environment]::GetFolderPath('Programs')) 'QoderWake/QoderWake.lnk'), (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'QoderWake.lnk'))",
    '$shortcuts = @($shortcutPaths | Where-Object { Test-Path -LiteralPath $_ })',
    // Residue must belong to the dedicated run identity (or live under the
    // owned install root). Matching on executable name alone would flag the
    // separately installed official QoderWake daemon as leftover test residue.
    "$processes = @(Get-CimInstance Win32_Process | Where-Object { @('QoderWake.exe', 'QoderWakeBrowserNativeHost.exe', 'QoderWakeUninstallCleanup.exe') -contains $_.Name } | ForEach-Object { $executable = [string]$_.ExecutablePath; $underRoot = $executable -and ($executable.Equals($installRoot, [StringComparison]::OrdinalIgnoreCase) -or $executable.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase)); $owner = Invoke-CimMethod -InputObject $_ -MethodName GetOwner -ErrorAction SilentlyContinue; [pscustomobject]@{ processId = $_.ProcessId; name = $_.Name; executablePath = $executable; ownedByRunIdentity = (($owner.ReturnValue -eq 0) -and ($owner.User -ieq $env:USERNAME) -and ($owner.Domain -ieq $env:USERDOMAIN)); underInstallRoot = [bool]$underRoot } })",
    '[pscustomobject]@{ installRootPresent = (Test-Path -LiteralPath $installRoot); registry = $registry; shortcuts = $shortcuts; processes = $processes } | ConvertTo-Json -Depth 4 -Compress',
  ].join('; ');
  const result = await runWindowsProcess(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-Command', command],
    {
      env: { ...environment, WORKDUDE_EXPECTED_INSTALL_ROOT: installRoot },
    },
  );
  if (result.code !== 0) {
    throw new Error(
      `Windows uninstall residue inspection failed (${result.code ?? result.signal}): ${result.stderr.slice(-4_000)}`,
    );
  }
  const residue = JSON.parse(result.stdout);
  if (
    typeof residue?.installRootPresent !== 'boolean' ||
    !Array.isArray(residue.registry) ||
    !Array.isArray(residue.shortcuts) ||
    !Array.isArray(residue.processes)
  ) {
    throw new Error('Windows uninstall residue inspection returned an invalid result.');
  }
  const processes = residue.processes
    .map((process) => {
      if (
        !process ||
        typeof process !== 'object' ||
        typeof process.ownedByRunIdentity !== 'boolean' ||
        typeof process.underInstallRoot !== 'boolean'
      ) {
        throw new Error('Windows uninstall residue inspection returned invalid process ownership.');
      }
      return process;
    })
    .filter((process) => process.ownedByRunIdentity || process.underInstallRoot);
  return { ...residue, processes };
}

async function assertWindowsUninstallResidueRemoved(installRoot, environment) {
  const deadline = Date.now() + 20_000;
  let residue;
  do {
    residue = await readWindowsUninstallResidue(installRoot, environment);
    if (
      !residue.installRootPresent &&
      residue.registry.length === 0 &&
      residue.shortcuts.length === 0 &&
      residue.processes.length === 0
    ) {
      return;
    }
    await delay(250);
  } while (Date.now() < deadline);

  if (residue.installRootPresent) {
    throw new Error(`Windows uninstall retained application files: ${installRoot}`);
  }
  if (residue.registry.length > 0) {
    throw new Error(`Windows uninstall retained registry ownership: ${residue.registry.join(', ')}`);
  }
  if (residue.shortcuts.length > 0) {
    throw new Error(`Windows uninstall retained owned shortcuts: ${residue.shortcuts.join(', ')}`);
  }
  throw new Error(
    `Windows uninstall retained QoderWake processes: ${residue.processes
      .map(({ ProcessId, Name }) => `${Name}:${ProcessId}`)
      .join(', ')}`,
  );
}

export async function createWindowsInnoTestInstallation({
  installer,
  version,
  prefix,
  expectedInstallerSha256,
  packageRoot = resolve('apps/desktop/out/QoderWake-win32-x64'),
}) {
  if (!/^workdude-[a-z0-9-]+$/u.test(prefix)) throw new Error('Invalid Windows lifecycle prefix');
  await resolveDedicatedWindowsLifecycleScope();
  const expectedInstallerName = `QoderWake-${version}-Windows-x64-Setup.exe`;
  if (basename(installer) !== expectedInstallerName) throw new Error('Unexpected Inno installer name');
  const installerIdentity = await plainFileIdentity(installer, 'Windows Setup');
  if (
    expectedInstallerSha256 !== undefined &&
    (!/^[a-f0-9]{64}$/u.test(expectedInstallerSha256) || installerIdentity.sha256 !== expectedInstallerSha256)
  )
    throw new Error('Windows Setup differs from reviewed SHA-256');
  const root = resolve(await mkdtemp(join(tmpdir(), `${prefix}-`)));
  if (!root.startsWith(`${resolve(tmpdir())}${sep}`) || !basename(root).startsWith(`${prefix}-`))
    throw new Error('Unexpected native lifecycle root');
  const rootIdentity = await plainDirectoryIdentity(root, 'Windows lifecycle root');
  const installRoot = join(root, 'Selected Install Directory');
  const environment = { ...process.env, ELECTRON_ENABLE_LOGGING: '1' };
  // Even a selected directory can reuse an existing per-user Inno registration.
  const prior = await readWindowsUninstallResidue(installRoot, environment);
  if (prior.installRootPresent || prior.registry.length || prior.shortcuts.length || prior.processes.length) {
    await removeOwnedTemporaryDirectory(root, rootIdentity, 'Windows lifecycle root');
    throw new Error('Refusing to reset an existing Windows installation; dedicated account must be clean');
  }
  const applicationFiles = [
    'QoderWake.exe',
    'resources/app.asar',
    'resources/QoderWakeBrowserNativeHost.exe',
    'resources/QoderWakeUninstallCleanup.exe',
  ];
  const packaged = await Promise.all(
    applicationFiles.map((file) => plainFileIdentity(join(packageRoot, file), file)),
  );
  const stagedInstaller = await stageOwnedExecutable(
    installer,
    installerIdentity,
    root,
    rootIdentity,
    expectedInstallerName,
    'Windows Setup',
  );
  const installed = await runWindowsProcess(
    stagedInstaller.path,
    [
      '/VERYSILENT',
      '/SUPPRESSMSGBOXES',
      '/NORESTART',
      '/NOCLOSEAPPLICATIONS',
      '/NOICONS',
      '/TASKS=',
      `/DIR=${installRoot}`,
    ],
    { env: environment },
  );
  await assertOwnedFile(stagedInstaller.path, stagedInstaller, 'Staged Windows Setup');
  await assertOwnedFile(installer, installerIdentity, 'Windows Setup');
  if (installed.code !== 0) throw new Error('Inno install failed; evidence retained at ' + root);
  for (const [index, file] of applicationFiles.entries()) {
    await assertOwnedFile(packaged[index].path, packaged[index], 'Packaged ' + file);
    const actual = await plainFileIdentity(join(installRoot, file), 'Installed ' + file);
    if (actual.sha256 !== packaged[index].sha256 || actual.sizeBytes !== packaged[index].sizeBytes)
      throw new Error('Installed bytes differ from packaged artifact: ' + file);
  }
  const uninstaller = join(installRoot, 'unins000.exe');
  const uninstallerIdentity = await plainFileIdentity(uninstaller, 'Installed Inno uninstaller');
  const userData = join(root, 'user-data');
  await mkdir(userData);
  let uninstalled = false;
  return {
    root,
    installRoot,
    environment,
    userData,
    installedExecutable: join(installRoot, 'QoderWake.exe'),
    applicationExecutable: join(installRoot, 'QoderWake.exe'),
    applicationArchive: join(installRoot, 'resources/app.asar'),
    async uninstallAndAssertApplicationRemoval() {
      if (uninstalled) return;
      const verified = await assertOwnedFile(uninstaller, uninstallerIdentity, 'Installed Inno uninstaller');
      const result = await runWindowsProcess(
        verified.path,
        ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
        { env: environment },
      );
      if (result.code !== 0) throw new Error('Inno uninstall failed; evidence retained at ' + root);
      await waitForApplicationsRemoved([installRoot]);
      await assertWindowsUninstallResidueRemoved(installRoot, environment);
      uninstalled = true;
    },
    async cleanup() {
      if (!uninstalled) throw new Error('Verified uninstall required before evidence cleanup');
      await removeOwnedTemporaryDirectory(root, rootIdentity, 'Windows lifecycle root');
    },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv.length !== 3 || process.argv[2] !== '--scope-only') {
    throw new Error('Use --scope-only; installation is available only through the imported owned helper.');
  }
  await resolveDedicatedWindowsLifecycleScope();
  process.stdout.write('{"verified":true,"scope":"dedicated-windows-known-folders"}\n');
}
