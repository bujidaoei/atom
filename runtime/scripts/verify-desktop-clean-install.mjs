import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { access, readFile, stat, writeFile } from 'node:fs/promises';
import { basename, relative, resolve, sep } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

import { createWindowsInnoTestInstallation, runWindowsProcess } from './windows-native-test-install.mjs';

if (process.platform !== 'win32') {
  throw new Error('The clean-install verification currently targets the Windows release.');
}

const desktopPackage = JSON.parse(await readFile('apps/desktop/package.json', 'utf8'));
const makeRoot = resolve('apps/desktop/out/make');
const installer = resolve(makeRoot, `inno/QoderWake-${desktopPackage.version}-Windows-x64-Setup.exe`);
await access(installer);

async function sha256(path) {
  const hash = createHash('sha256');
  hash.update(await readFile(path));
  return hash.digest('hex');
}

let installation;
let launched;
try {
  installation = await createWindowsInnoTestInstallation({
    installer,
    version: desktopPackage.version,
    prefix: 'workdude-clean-install',
    expectedInstallerSha256: process.env.WORKDUDE_WINDOWS_CURRENT_SETUP_SHA256,
  });
  const [launcherInfo, applicationInfo, archiveInfo] = await Promise.all([
    stat(installation.installedExecutable),
    stat(installation.applicationExecutable),
    stat(installation.applicationArchive),
  ]);
  if (launcherInfo.size < 100_000) throw new Error('Installed launcher is unexpectedly small.');
  if (applicationInfo.size < 1_000_000) {
    throw new Error('Installed application executable is unexpectedly small.');
  }
  if (archiveInfo.size < 1_000_000) throw new Error('Installed application archive is unexpectedly small.');

  launched = spawn(installation.applicationExecutable, [`--user-data-dir=${installation.userData}`], {
    env: { ...installation.environment, WORKDUDE_AUTOMATION_WINDOW: 'hidden' },
    windowsHide: true,
    stdio: 'ignore',
  });
  let earlyExit;
  launched.once('exit', (code, signal) => {
    earlyExit = { code, signal };
  });
  await delay(10_000);
  if (earlyExit) {
    throw new Error(`Clean-installed desktop exited during startup: ${JSON.stringify(earlyExit)}`);
  }

  const assets = [installer];
  const checksumLines = [];
  for (const asset of assets) checksumLines.push(`${await sha256(asset)}  ${basename(asset)}`);
  const checksumPath = resolve(makeRoot, 'SHA256SUMS-Windows-x64.txt');
  await writeFile(checksumPath, `${checksumLines.join('\n')}\n`, 'utf8');
  process.stdout.write(
    `Clean Windows install and launch verified in an isolated environment; checksums=${relative(process.cwd(), checksumPath).split(sep).join('/')}\n`,
  );
} finally {
  if (launched?.pid && launched.exitCode === null) {
    await runWindowsProcess('taskkill.exe', ['/PID', String(launched.pid), '/T', '/F']);
  }
  await delay(1_000);
  if (installation) {
    await installation.uninstallAndAssertApplicationRemoval();
    process.stdout.write(
      'Isolated Windows uninstall removed application files; authoritative product-data retention remains an upgrade-journey gate.\n',
    );
    await installation.cleanup();
  }
}
