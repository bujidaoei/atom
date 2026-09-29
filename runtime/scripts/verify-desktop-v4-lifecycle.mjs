import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import { lstat, mkdir, mkdtemp, realpath, rm } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

import { fetch } from 'undici';
import {
  readExistingBrowserNativeManifest,
  cleanupVerifierOwnedBrowserNativeRegistry,
} from './windows-verifier-native-registry.mjs';

const TEMPORARY_PREFIX = 'workdude-v4-lifecycle-';
const CHILD_EXIT_TIMEOUT_MS = 5_000;
const SUCCESS_OUTPUT =
  [
    'Verified V4 Windows desktop lifecycle subset:',
    '- packaged launch binds an authenticated loopback product surface',
    '- the shared Renderer and loopback transport are present',
    '- a second launch exits while the resident instance remains alive',
    '- a second authenticated management request succeeds while the resident service remains alive',
    'Pending by design: first-login, tray menu labels, notifications, shortcuts, update, upgrade, uninstall, retention-after-uninstall.',
  ].join('\n') + '\n';

async function freeLoopbackPort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close();
        reject(new Error('Unable to reserve a desktop product port'));
        return;
      }
      server.close((error) => (error ? reject(error) : resolvePort(address.port)));
    });
  });
}

function launch(executable, args, environment) {
  const child = spawn(executable, args, {
    env: environment,
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
  const started = new Promise((resolveStarted, rejectStarted) => {
    child.once('spawn', resolveStarted);
    child.once('error', rejectStarted);
  });
  let exitResult;
  const exited = new Promise((resolveExit) => {
    const settle = (result) => {
      if (exitResult) return;
      exitResult = result;
      resolveExit(result);
    };
    child.once('error', (error) => settle({ code: null, signal: null, error }));
    child.once('exit', (code, signal) => settle({ code, signal }));
  });
  return {
    child,
    started,
    exited,
    get exitResult() {
      return exitResult;
    },
    output: () => ({ stdout, stderr }),
  };
}

async function openSession(url, fetchImplementation, wait) {
  const deadline = Date.now() + 30_000;
  let lastError;
  while (Date.now() < deadline) {
    let response;
    try {
      response = await fetchImplementation(url, { redirect: 'manual' });
      if (response.status !== 302 || response.headers.get('location') !== '/management') {
        throw new Error(`Unexpected desktop session response: ${response.status}`);
      }
      const cookie = response.headers.get('set-cookie')?.split(';')[0];
      if (!cookie?.startsWith('workdude_session=')) {
        throw new Error('Desktop session did not issue its HttpOnly cookie');
      }
      return cookie;
    } catch (cause) {
      lastError = cause;
      await wait(250);
    } finally {
      await response?.body?.cancel().catch(() => undefined);
    }
  }
  throw new Error('Desktop loopback product did not become ready', { cause: lastError });
}

function samePath(left, right) {
  const normalizedLeft = resolve(left);
  const normalizedRight = resolve(right);
  return process.platform === 'win32'
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

async function captureOwnedTemporaryRoot(candidate, temporaryBase, dependencies) {
  const root = resolve(candidate);
  const base = resolve(await dependencies.realpathPath(resolve(temporaryBase)));
  const stats = await dependencies.lstatPath(root);
  const resolvedRoot = resolve(await dependencies.realpathPath(root));
  const name = basename(resolvedRoot);
  if (
    !stats.isDirectory() ||
    stats.isSymbolicLink() ||
    !samePath(root, resolvedRoot) ||
    !samePath(dirname(resolvedRoot), base) ||
    !name.startsWith(TEMPORARY_PREFIX) ||
    name.length === TEMPORARY_PREFIX.length
  ) {
    throw new Error('Desktop lifecycle temporary root is unsafe');
  }
  return { path: root, realPath: resolvedRoot, device: stats.dev, inode: stats.ino };
}

async function verifyOwnedTemporaryRoot(identity, temporaryBase, dependencies) {
  const current = await captureOwnedTemporaryRoot(identity.path, temporaryBase, dependencies);
  if (
    !samePath(current.realPath, identity.realPath) ||
    current.device !== identity.device ||
    current.inode !== identity.inode
  ) {
    throw new Error('Desktop lifecycle temporary root identity changed');
  }
  return current.path;
}

async function terminateOwnedChild(label, launched, wait) {
  if (launched.exitResult || launched.child.exitCode !== null || launched.child.signalCode !== null) {
    await launched.exited;
    return;
  }
  launched.child.kill();
  if (launched.child.exitCode !== null) {
    await launched.exited;
    return;
  }
  const exit = await Promise.race([
    launched.exited.then((result) => ({ exited: true, result })),
    wait(CHILD_EXIT_TIMEOUT_MS, null),
  ]);
  if (exit === null) throw new Error(`${label} did not exit after termination.`);
}

function mergeDependencies(overrides = {}) {
  const fetchImplementation = overrides.fetchImplementation ?? fetch;
  const wait = overrides.wait ?? delay;
  return {
    temporaryDirectory: overrides.temporaryDirectory ?? tmpdir,
    createTemporaryDirectory: overrides.createTemporaryDirectory ?? mkdtemp,
    lstatPath: overrides.lstatPath ?? lstat,
    realpathPath: overrides.realpathPath ?? realpath,
    makeDirectory: overrides.makeDirectory ?? ((path) => mkdir(path, { recursive: true })),
    reservePort: overrides.reservePort ?? freeLoopbackPort,
    createSessionSecret: overrides.createSessionSecret ?? (() => randomBytes(32).toString('base64url')),
    launchProcess: overrides.launchProcess ?? launch,
    readExistingBrowserNativeManifest:
      overrides.readExistingBrowserNativeManifest ?? readExistingBrowserNativeManifest,
    cleanupVerifierOwnedBrowserNativeRegistry:
      overrides.cleanupVerifierOwnedBrowserNativeRegistry ?? cleanupVerifierOwnedBrowserNativeRegistry,
    openSession: overrides.openSession ?? ((url) => openSession(url, fetchImplementation, wait)),
    fetchImplementation,
    wait,
    removeDirectory: overrides.removeDirectory ?? rm,
    writeOutput: overrides.writeOutput ?? ((value) => process.stdout.write(value)),
  };
}

async function captureCleanup(errors, label, action) {
  try {
    await action();
  } catch (cause) {
    errors.push(new Error(label, { cause }));
  }
}

function throwVerificationErrors(verificationError, cleanupErrors) {
  if (verificationError && cleanupErrors.length) {
    throw new AggregateError(
      [verificationError, ...cleanupErrors],
      'Desktop lifecycle verification and cleanup both failed.',
    );
  }
  if (verificationError) throw verificationError;
  if (cleanupErrors.length === 1) throw cleanupErrors[0];
  if (cleanupErrors.length > 1) {
    throw new AggregateError(cleanupErrors, 'Desktop lifecycle cleanup failed.');
  }
}

export async function verifyDesktopV4Lifecycle({
  executablePath,
  baseEnvironment = process.env,
  dependencies: dependencyOverrides,
}) {
  const executable = resolve(executablePath);
  const dependencies = mergeDependencies(dependencyOverrides);
  const temporaryBase = resolve(dependencies.temporaryDirectory());
  let root;
  let primary;
  let secondary;
  let baselineManifest;
  let baselineCaptured = false;
  let verificationError;
  const cleanupErrors = [];

  try {
    const candidate = await dependencies.createTemporaryDirectory(join(temporaryBase, TEMPORARY_PREFIX));
    root = await captureOwnedTemporaryRoot(candidate, temporaryBase, dependencies);
    const appData = join(root.path, 'Roaming');
    const localAppData = join(root.path, 'Local');
    await Promise.all([dependencies.makeDirectory(appData), dependencies.makeDirectory(localAppData)]);
    const port = await dependencies.reservePort();
    const sessionSecret = dependencies.createSessionSecret();
    const baseUrl = `http://127.0.0.1:${port}`;
    const args = [`--user-data-dir=${appData}`];
    const environment = {
      ...baseEnvironment,
      APPDATA: appData,
      LOCALAPPDATA: localAppData,
      ELECTRON_ENABLE_LOGGING: '1',
      WORKDUDE_AUTOMATION_WINDOW: 'hidden',
      WORKDUDE_AUTOMATION_SESSION_TOKEN: sessionSecret,
      WORKDUDE_LOCAL_UI_PORT: String(port),
    };

    baselineManifest = await dependencies.readExistingBrowserNativeManifest();
    baselineCaptured = true;
    primary = dependencies.launchProcess(executable, args, environment);
    await primary.started;
    const cookie = await dependencies.openSession(`${baseUrl}/__workdude/session/${sessionSecret}`);
    const headers = { cookie };
    const management = await dependencies.fetchImplementation(`${baseUrl}/management`, { headers });
    const html = await management.text();
    if (management.status !== 200 || !html.includes('/__workdude/bridge.js')) {
      throw new Error('Desktop management route did not serve the shared Renderer');
    }
    const bridge = await dependencies.fetchImplementation(`${baseUrl}/__workdude/bridge.js`, { headers });
    const bridgeSource = await bridge.text();
    if (bridge.status !== 200 || !bridgeSource.includes("transport: 'loopback'")) {
      throw new Error('Desktop loopback bridge is absent or not identified');
    }

    secondary = dependencies.launchProcess(executable, args, environment);
    await secondary.started;
    const secondaryExit = await Promise.race([
      secondary.exited,
      dependencies.wait(CHILD_EXIT_TIMEOUT_MS, null),
    ]);
    if (secondaryExit === null) {
      throw new Error('Second Desktop launch did not hand off to the resident single instance');
    }
    if (secondaryExit.error || secondaryExit.code !== 0 || secondaryExit.signal !== null) {
      throw new Error('Second Desktop launch failed instead of handing off to the resident single instance');
    }
    if (primary.exitResult || primary.child.exitCode !== null || primary.child.signalCode !== null) {
      const output = primary.output();
      throw new Error(
        `Resident Desktop exited after second launch.\nstdout:\n${output.stdout}\nstderr:\n${output.stderr}`,
      );
    }

    const reopened = await dependencies.fetchImplementation(`${baseUrl}/management`, { headers });
    if (reopened.status !== 200 || !(await reopened.text()).includes('/__workdude/bridge.js')) {
      throw new Error('Authenticated management reopen failed while the resident product was alive');
    }
  } catch (error) {
    verificationError = error;
  } finally {
    if (secondary) {
      const ownedSecondary = secondary;
      await captureCleanup(cleanupErrors, 'Secondary Desktop process cleanup failed.', () =>
        terminateOwnedChild('Secondary Desktop process', ownedSecondary, dependencies.wait),
      );
    }
    if (primary) {
      const ownedPrimary = primary;
      await captureCleanup(cleanupErrors, 'Primary Desktop process cleanup failed.', () =>
        terminateOwnedChild('Primary Desktop process', ownedPrimary, dependencies.wait),
      );
    }
    if (root && baselineCaptured && cleanupErrors.length === 0) {
      await captureCleanup(cleanupErrors, 'Desktop lifecycle native-registration cleanup failed.', () =>
        dependencies.cleanupVerifierOwnedBrowserNativeRegistry(join(root.path, 'Roaming'), baselineManifest),
      );
    }
    if (root) {
      const rootToRemove = root;
      await captureCleanup(cleanupErrors, 'Desktop lifecycle temporary-root cleanup failed.', async () => {
        const ownedRoot = await verifyOwnedTemporaryRoot(rootToRemove, temporaryBase, dependencies);
        if (cleanupErrors.length > 0) return;
        await dependencies.removeDirectory(ownedRoot, {
          recursive: true,
          force: true,
          maxRetries: 20,
          retryDelay: 250,
        });
      });
    }
  }

  throwVerificationErrors(verificationError, cleanupErrors);
  dependencies.writeOutput(SUCCESS_OUTPUT);
}

async function runCli() {
  if (process.platform !== 'win32') {
    throw new Error('The current verified QoderWake desktop reference is Windows-only.');
  }
  const executable = resolve('apps/desktop/out/QoderWake-win32-x64/QoderWake.exe');
  if (!existsSync(executable)) {
    throw new Error(`Packaged Desktop executable is required: ${executable}`);
  }
  await verifyDesktopV4Lifecycle({ executablePath: executable });
}

if (process.argv[1] && samePath(fileURLToPath(import.meta.url), process.argv[1])) {
  await runCli();
}
