import { spawn } from 'node:child_process';
import { access, cp, mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { setTimeout as delay } from 'node:timers/promises';
import {
  readExistingBrowserNativeManifest,
  cleanupVerifierOwnedBrowserNativeRegistry,
} from './windows-verifier-native-registry.mjs';

if (process.platform !== 'win32') {
  throw new Error('The local desktop smoke check currently targets the Windows package.');
}

const packageRoot = resolve('apps/desktop/out/QoderWake-win32-x64');
const executable = resolve(packageRoot, 'QoderWake.exe');
const archive = resolve(packageRoot, 'resources/app.asar');
const nativeHost = resolve(packageRoot, 'resources/QoderWakeBrowserNativeHost.exe');
const uninstallHelper = resolve(packageRoot, 'resources/QoderWakeUninstallCleanup.exe');
const desktopPackage = JSON.parse(await readFile('apps/desktop/package.json', 'utf8'));
const zip = resolve(`apps/desktop/out/make/zip/win32/x64/QoderWake-win32-x64-${desktopPackage.version}.zip`);
const mainBundle = await readFile('apps/desktop/.vite/build/main.js', 'utf8');
const agentBundle = await readFile('apps/desktop/.vite/build/local-agent-host.mjs', 'utf8');
const brokerBundle = await readFile('apps/desktop/.vite/build/local-broker-host.js', 'utf8');

if (desktopPackage.type === 'module' && /\brequire\s*\(/u.test(mainBundle)) {
  throw new Error('Desktop Main is CommonJS but the packaged application declares an ESM package scope.');
}
if (/\brequire\s*\(\s*['"]dockerode['"]\s*\)/u.test(brokerBundle)) {
  throw new Error('Desktop Broker depends on unpackaged dockerode at runtime.');
}
if (agentBundle.includes('{}.url') || !agentBundle.includes('import.meta.url')) {
  throw new Error('Desktop Agent Host lost ESM import.meta.url semantics during bundling.');
}

await Promise.all([
  access(executable),
  access(archive),
  access(nativeHost),
  access(uninstallHelper),
  access(zip),
]);
const [executableInfo, archiveInfo, nativeHostInfo, uninstallHelperInfo, zipInfo] = await Promise.all([
  stat(executable),
  stat(archive),
  stat(nativeHost),
  stat(uninstallHelper),
  stat(zip),
]);
if (
  executableInfo.size < 1_000_000 ||
  archiveInfo.size < 10_000 ||
  nativeHostInfo.size < 4_096 ||
  uninstallHelperInfo.size < 4_096 ||
  zipInfo.size < 1_000_000
) {
  throw new Error('Desktop package contains an unexpectedly small required artifact.');
}

const userData = await mkdtemp(join(tmpdir(), 'workdude-desktop-smoke-'));
const userDataSeed = process.env.WORKDUDE_SMOKE_USER_DATA_SEED;
if (userDataSeed) {
  await cp(resolve(userDataSeed), userData, { recursive: true });
}
const baselineRegistryManifest = await readExistingBrowserNativeManifest();
const child = spawn(executable, [`--user-data-dir=${userData}`], {
  env: {
    ...process.env,
    ELECTRON_ENABLE_LOGGING: '1',
    WORKDUDE_AUTOMATION_WINDOW: 'hidden',
  },
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: true,
});
let stdout = '';
let stderr = '';
child.stdout.setEncoding('utf8');
child.stderr.setEncoding('utf8');
child.stdout.on('data', (chunk) => {
  stdout += chunk;
});
child.stderr.on('data', (chunk) => {
  stderr += chunk;
});
const exited = new Promise((resolveExit) => {
  child.once('exit', (code, signal) => resolveExit({ code, signal }));
});
let startupFailure;
let cleanupFailure;
try {
  const earlyExit = await Promise.race([exited, delay(10_000, null)]);
  if (earlyExit !== null) {
    throw new Error(
      `Packaged desktop exited during startup: ${JSON.stringify(earlyExit)}\nstdout:\n${stdout.slice(-8_000)}\nstderr:\n${stderr.slice(-8_000)}`,
    );
  }
} catch (cause) {
  startupFailure = cause;
} finally {
  if (child.exitCode === null) child.kill();
  const cleanupExit = await Promise.race([exited, delay(5_000, null)]);
  await delay(1_000);
  if (cleanupExit === null) {
    cleanupFailure = new Error('Desktop smoke process did not exit; retained its profile and registration.');
  } else {
    try {
      await cleanupVerifierOwnedBrowserNativeRegistry(userData, baselineRegistryManifest);
    } catch (cause) {
      cleanupFailure = cause;
    }
  }
  if (!cleanupFailure) {
    await rm(userData, { recursive: true, force: true, maxRetries: 15, retryDelay: 250 });
  }
}

const failures = [startupFailure, cleanupFailure].filter((failure) => failure !== undefined);
if (failures.length > 0) throw new AggregateError(failures, 'Desktop smoke verification failed.');

process.stdout.write(
  `Windows desktop package started and verified: exe=${executableInfo.size}, asar=${archiveInfo.size}, nativeHost=${nativeHostInfo.size}, uninstallHelper=${uninstallHelperInfo.size}, zip=${zipInfo.size}\n`,
);
