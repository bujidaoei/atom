import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { clearTimeout, setTimeout } from 'node:timers';
import { setTimeout as delay } from 'node:timers/promises';

import { extractFile } from '@electron/asar';
import { fetch, WebSocket } from 'undici';

if (process.platform !== 'win32') {
  throw new Error('The standalone-window verifier requires a native Windows host.');
}

const MAX_INTERACTIVE_WINDOW_MS = 3_000;
const NATIVE_LEASE_CONTENTION_PROOF_MS = 31_000;
const BROWSER_NATIVE_PROCESS_LEASE_PATH = '\\\\.\\pipe\\QoderWake.BrowserNativeLifecycle';
const BROWSER_NATIVE_LIFECYCLE_FILE = 'browser-connector-native-lifecycle.json';
const BROWSER_NATIVE_REGISTRY_KEY =
  'HKCU:\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.workdude.browser_connector';

const executable = resolve(
  process.argv.find((value) => value.startsWith('--executable='))?.slice('--executable='.length) ??
    'apps/desktop/out/QoderWake-win32-x64/QoderWake.exe',
);

const expectedVersion =
  process.argv
    .find((value) => value.startsWith('--expected-version='))
    ?.slice('--expected-version='.length) ??
  JSON.parse(await readFile(resolve('apps/desktop/package.json'), 'utf8')).version;
const packagedManifest = JSON.parse(
  extractFile(join(dirname(executable), 'resources', 'app.asar'), 'package.json').toString('utf8'),
);
if (packagedManifest.version !== expectedVersion) {
  throw new Error(
    `Standalone-window executable version mismatch: expected ${expectedVersion}, found ${String(packagedManifest.version)}.`,
  );
}

const fileSha256 = (path) =>
  new Promise((resolveHash, rejectHash) => {
    const hash = createHash('sha256');
    const stream = createReadStream(path);
    stream.once('error', rejectHash);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.once('end', () => resolveHash(hash.digest('hex')));
  });

const executableSha256 = await fileSha256(executable);

const reservePort = () =>
  new Promise((resolvePort, rejectPort) => {
    const server = createServer();
    server.once('error', rejectPort);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close();
        rejectPort(new Error('Unable to reserve a standalone-window port'));
        return;
      }
      server.close((error) => (error ? rejectPort(error) : resolvePort(address.port)));
    });
  });

const launch = (args, environment) => {
  const child = spawn(executable, args, {
    env: environment,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: false,
  });
  let stderr = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (chunk) => {
    stderr += chunk;
  });
  const exited = new Promise((resolveExit) => {
    child.once('error', (error) => resolveExit({ code: null, signal: null, error }));
    child.once('exit', (code, signal) => resolveExit({ code, signal }));
  });
  return { child, exited, stderr: () => stderr };
};

const waitForExit = async (launchResult, label, timeoutMs) => {
  const exit = await Promise.race([launchResult.exited, delay(timeoutMs, null)]);
  if (exit === null) throw new Error(`${label} did not exit within ${timeoutMs} ms.`);
  return exit;
};

const stopLaunch = async (launchResult, label) => {
  if (launchResult.child.exitCode === null && launchResult.child.signalCode === null) {
    launchResult.child.kill();
  }
  await waitForExit(launchResult, label, 10_000);
};

const tryAcquireBrowserNativePipe = async () => {
  const server = createServer((socket) => socket.destroy());
  try {
    await new Promise((resolveListen, rejectListen) => {
      server.once('error', rejectListen);
      server.listen(
        {
          path: BROWSER_NATIVE_PROCESS_LEASE_PATH,
          exclusive: true,
          readableAll: false,
          writableAll: false,
        },
        resolveListen,
      );
    });
    return true;
  } catch (cause) {
    if (cause?.code === 'EADDRINUSE') return false;
    throw cause;
  } finally {
    if (server.listening) {
      await new Promise((resolveClose, rejectClose) =>
        server.close((cause) => (cause ? rejectClose(cause) : resolveClose())),
      );
    }
  }
};

const assertBrowserNativePipeAvailable = async (label = 'Browser Native process lease') => {
  if (!(await tryAcquireBrowserNativePipe())) throw new Error(`${label} is already owned before launch.`);
};

const assertBrowserNativePipeHeld = async (label = 'Browser Native process lease') => {
  if (await tryAcquireBrowserNativePipe())
    throw new Error(`${label} was not retained by the primary Desktop.`);
};

const waitForStderrMarker = async (launchResult, marker, timeoutMs) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const earlyExit = await Promise.race([launchResult.exited, delay(0, null)]);
    if (earlyExit !== null) {
      throw new Error(
        `Desktop exited before ${marker}: ${JSON.stringify(earlyExit)}\n${launchResult.stderr()}`,
      );
    }
    if (launchResult.stderr().includes(marker)) return;
    await delay(100);
  }
  throw new Error(`Desktop did not report ${marker} within ${timeoutMs} ms.`);
};

const waitForActiveNativeGeneration = async (userData, priorGeneration, launchResult) => {
  const path = join(userData, BROWSER_NATIVE_LIFECYCLE_FILE);
  const deadline = Date.now() + 45_000;
  let lastError;
  while (Date.now() < deadline) {
    const earlyExit = await Promise.race([launchResult.exited, delay(0, null)]);
    if (earlyExit !== null) {
      throw new Error(
        `Desktop exited before Browser Native generation activation: ${JSON.stringify(earlyExit)}\n${launchResult.stderr()}`,
      );
    }
    try {
      const record = JSON.parse(await readFile(path, 'utf8'));
      if (
        record?.schemaVersion === 1 &&
        record.state === 'active' &&
        typeof record.generationId === 'string' &&
        /^[0-9a-f]{8}-[0-9a-f-]{27}$/iu.test(record.generationId) &&
        record.generationId !== priorGeneration
      ) {
        return record.generationId;
      }
      lastError = new Error('Browser Native generation was not active or unique');
    } catch (cause) {
      lastError = cause;
    }
    await delay(100);
  }
  throw new Error(`Browser Native active generation was unavailable: ${String(lastError)}`);
};

const powershell = async (script) => {
  const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk) => (stdout += chunk));
  child.stderr.on('data', (chunk) => (stderr += chunk));
  const result = await Promise.race([
    new Promise((resolveExit, rejectExit) => {
      child.once('error', rejectExit);
      child.once('exit', (code, signal) => resolveExit({ code, signal }));
    }),
    delay(10_000, null),
  ]);
  if (result === null) {
    child.kill();
    throw new Error('Windows window probe timed out.');
  }
  if (result.code !== 0) throw new Error(`Windows window probe failed: ${stderr}`);
  return stdout.trim();
};

const powershellLiteral = (value) => `'${value.replaceAll("'", "''")}'`;

const readBrowserNativeRegistryManifest = async () => {
  const output = await powershell(
    `if(-not(Test-Path -LiteralPath ${powershellLiteral(BROWSER_NATIVE_REGISTRY_KEY)})){ 'absent'; exit 0 };` +
      `$value=(Get-ItemProperty -LiteralPath ${powershellLiteral(BROWSER_NATIVE_REGISTRY_KEY)} -Name '(default)').'(default)';` +
      `if($null -eq $value){ 'empty' } else { [string]$value }`,
  );
  return output === 'absent' ? undefined : output;
};

const assertStandaloneRegistryAuthority = async () => {
  const manifestPath = await readBrowserNativeRegistryManifest();
  if (manifestPath !== undefined) {
    throw new Error(
      `Standalone-window verifier requires an absent Browser Native registry; existing manifest is ${manifestPath}`,
    );
  }
};

const assertNoVerifierProcesses = async (rootPath) => {
  const output = await powershell(
    `$root=${powershellLiteral(rootPath)};` +
      `$matches=@(Get-CimInstance Win32_Process | Where-Object {` +
      ` $_.Name -eq 'QoderWake.exe' -and ([string]$_.CommandLine).Contains($root)` +
      `}); if($matches.Count -ne 0){$matches.ProcessId -join ','; exit 3}; 'none'`,
  );
  if (output !== 'none') throw new Error(`Verifier QoderWake descendants remained: ${output}`);
};

const assertBrowserNativeRegistryAbsent = async () => {
  const output = await powershell(
    `if(Test-Path -LiteralPath ${powershellLiteral(BROWSER_NATIVE_REGISTRY_KEY)}){'present'}else{'absent'}`,
  );
  if (output !== 'absent') throw new Error('Browser Native registry residue remained after cleanup.');
};

const cleanupVerifierOwnedBrowserNativeRegistry = async (userDataPath) => {
  const expectedManifest = join(userDataPath, 'browser-connector-native-host.json');
  const output = await powershell(
    `$subKey='Software\\Google\\Chrome\\NativeMessagingHosts\\com.workdude.browser_connector';` +
      `$expected=${powershellLiteral(expectedManifest)};` +
      `$key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($subKey,$true);` +
      `if($null-eq$key){'absent';exit 0};` +
      `try{$names=@($key.GetValueNames());$children=@($key.GetSubKeyNames());` +
      `$value=[string]$key.GetValue('', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames);` +
      `if($names.Count-ne 1-or$names[0]-ne''-or$children.Count-ne 0-or-not$value.Equals($expected,[StringComparison]::OrdinalIgnoreCase)){exit 4}}finally{$key.Dispose()};` +
      `[Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($subKey,$false);'removed'`,
  );
  if (output !== 'removed' && output !== 'absent') {
    throw new Error(`Verifier-owned Browser Native registry cleanup failed: ${output}`);
  }
};

const windowState = async (processId) => {
  const output = await powershell(
    `$p=Get-Process -Id ${Number(processId)} -ErrorAction Stop;` +
      `[ordered]@{Handle=[int64]$p.MainWindowHandle;Title=$p.MainWindowTitle;Responding=$p.Responding}|ConvertTo-Json -Compress`,
  );
  const parsed = JSON.parse(output);
  return {
    handle: Number(parsed.Handle),
    title: String(parsed.Title),
    responding: parsed.Responding === true,
  };
};

const waitForWindow = async (processId, predicate, label, timeoutMs = 30_000) => {
  const deadline = Date.now() + timeoutMs;
  let state;
  while (Date.now() < deadline) {
    state = await windowState(processId);
    if (predicate(state)) return state;
    await delay(250);
  }
  throw new Error(`${label} timed out: ${JSON.stringify(state)}`);
};

const evaluateRenderer = (webSocketDebuggerUrl, expression) =>
  new Promise((resolveEvaluation, rejectEvaluation) => {
    const socket = new WebSocket(webSocketDebuggerUrl);
    const timeout = setTimeout(() => finish(new Error('Desktop Renderer CDP evaluation timed out.')), 10_000);
    let settled = false;
    const finish = (cause, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      socket.close();
      if (cause) rejectEvaluation(cause);
      else resolveEvaluation(value);
    };
    socket.addEventListener('error', () => finish(new Error('Desktop Renderer CDP connection failed.')));
    socket.addEventListener('open', () => {
      socket.send(
        JSON.stringify({
          id: 1,
          method: 'Runtime.evaluate',
          params: { expression, awaitPromise: true, returnByValue: true },
        }),
      );
    });
    socket.addEventListener('message', (event) => {
      let message;
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (message.id !== 1) return;
      if (message.error || message.result?.exceptionDetails) {
        finish(new Error('Desktop Renderer CDP evaluation failed.'));
        return;
      }
      finish(undefined, message.result?.result?.value);
    });
  });

const contendedAgentRuntimeHealth = async (userData) => {
  const activePortPath = join(userData, 'DevToolsActivePort');
  const deadline = Date.now() + 15_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const [rawPort] = (await readFile(activePortPath, 'utf8')).split(/\r?\n/u);
      const port = Number(rawPort);
      if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
        throw new Error('Desktop DevTools port is invalid');
      }
      const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
      const page = targets.find(
        (target) =>
          target?.type === 'page' &&
          target.title === 'QoderWake' &&
          typeof target.webSocketDebuggerUrl === 'string',
      );
      if (!page) throw new Error('Desktop Renderer target is unavailable');
      const result = await evaluateRenderer(
        page.webSocketDebuggerUrl,
        `(async () => {
          const result = await window.workdude.v3.invoke('listRoleTemplates', { limit: 1 });
          return {
            bridge: typeof window.workdude === 'object',
            itemCount: Array.isArray(result?.items) ? result.items.length : -1,
          };
        })()`,
      );
      if (result?.bridge !== true || !Number.isInteger(result.itemCount) || result.itemCount < 1) {
        throw new Error('Contended Desktop Agent Runtime RPC is unhealthy.');
      }
      return { bridge: true, roleTemplateCount: result.itemCount };
    } catch (cause) {
      lastError = cause;
      await delay(250);
    }
  }
  throw new Error(`Contended Desktop Agent Runtime RPC is unhealthy: ${String(lastError)}`);
};

const waitForResidentServer = async (port, exited, stderr) => {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const earlyExit = await Promise.race([exited, delay(0, null)]);
    if (earlyExit !== null) {
      throw new Error(`Background Desktop exited early: ${JSON.stringify(earlyExit)}\n${stderr()}`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/management`);
      await response.body?.cancel();
      return;
    } catch {
      await delay(250);
    }
  }
  throw new Error('Background Desktop resident server did not become ready.');
};

const proveHealthyWindowForDuration = async (launchResult, port, durationMs) => {
  const startedAt = Date.now();
  const deadline = startedAt + durationMs;
  while (Date.now() < deadline) {
    const earlyExit = await Promise.race([launchResult.exited, delay(0, null)]);
    if (earlyExit !== null) {
      throw new Error(
        `Browser Native lease contention stopped the core Desktop: ${JSON.stringify(earlyExit)}\n${launchResult.stderr()}`,
      );
    }
    const state = await windowState(launchResult.child.pid);
    if (state.handle === 0 || state.title !== 'QoderWake' || !state.responding) {
      throw new Error(
        `Browser Native lease contention degraded the core Desktop window: ${JSON.stringify(state)}`,
      );
    }
    const response = await fetch(`http://127.0.0.1:${port}/management`);
    await response.body?.cancel();
    if (response.status !== 401) {
      throw new Error(`Contended Desktop product server returned ${response.status} instead of 401.`);
    }
    await delay(1_000);
  }
  return Date.now() - startedAt;
};

const durableStateFingerprint = async (userData) => {
  const databasePath = join(userData, 'workdude-v3.sqlite');
  const deadline = Date.now() + 30_000;
  let lastError;
  while (Date.now() < deadline) {
    let database;
    try {
      database = new DatabaseSync(databasePath, { readOnly: true });
      const templates = database
        .prepare('SELECT id, name, source, status, current_version FROM v3_role_templates ORDER BY id')
        .all();
      if (templates.length === 0) throw new Error('Desktop durable role-template state is empty');
      return {
        count: templates.length,
        digest: createHash('sha256').update(JSON.stringify(templates)).digest('hex'),
      };
    } catch (error) {
      lastError = error;
      await delay(250);
    } finally {
      database?.close();
    }
  }
  throw new Error(`Desktop durable state was unavailable: ${String(lastError)}`);
};

await assertStandaloneRegistryAuthority();
await assertBrowserNativePipeAvailable('Browser Native preflight process lease');

const root = await mkdtemp(join(tmpdir(), 'qoderwake-standalone-window-'));
const userData = join(root, 'user-data');
const contendedUserData = join(root, 'contended-user-data');
const port = await reservePort();
const contendedPort = await reservePort();
const args = [`--user-data-dir=${userData}`];
const environment = {
  ...process.env,
  WORKDUDE_LOCAL_UI_PORT: String(port),
};
delete environment.WORKDUDE_AUTOMATION_WINDOW;
let cold;
let primary;
let contended;
let coldInteractiveLatencyMs;
let nativeLeaseContentionSurvivedMs;
let contendedRuntimeHealth;
let operationFailure;
try {
  const coldStartedAt = Date.now();
  cold = launch(args, environment);
  await waitForWindow(
    cold.child.pid,
    (state) => state.handle !== 0 && state.title === 'QoderWake' && state.responding,
    'Cold interactive launch',
  );
  coldInteractiveLatencyMs = Date.now() - coldStartedAt;
  if (coldInteractiveLatencyMs > MAX_INTERACTIVE_WINDOW_MS) {
    throw new Error(
      `Cold interactive window exceeded ${MAX_INTERACTIVE_WINDOW_MS} ms: ${coldInteractiveLatencyMs} ms`,
    );
  }
  const coldDurableState = await durableStateFingerprint(userData);
  const coldGeneration = await waitForActiveNativeGeneration(userData, undefined, cold);
  await assertBrowserNativePipeHeld('Cold Desktop Browser Native process lease');
  await stopLaunch(cold, 'Cold Desktop');
  cold = undefined;
  await assertBrowserNativePipeAvailable('Browser Native process lease after cold Desktop shutdown');

  primary = launch([...args, '--background'], environment);
  await waitForResidentServer(port, primary.exited, primary.stderr);
  await waitForActiveNativeGeneration(userData, coldGeneration, primary);
  await assertBrowserNativePipeHeld('Primary Desktop Browser Native process lease');
  process.stdout.write('standalone-window: background-ready\n');
  const background = await windowState(primary.child.pid);
  if (background.handle !== 0 || background.title) {
    throw new Error(`Background launch exposed a window: ${JSON.stringify(background)}`);
  }
  const restartedDurableState = await durableStateFingerprint(userData);
  if (restartedDurableState.digest !== coldDurableState.digest) {
    throw new Error('Cold-start durable state changed after background process restart.');
  }

  let stableHandle;
  for (let index = 0; index < 10; index += 1) {
    const secondary = launch(args, environment);
    const exit = await Promise.race([secondary.exited, delay(5_000, null)]);
    if (exit === null || exit.error || exit.code !== 0 || exit.signal !== null) {
      throw new Error(`Interactive launch ${index + 1} did not hand off cleanly: ${JSON.stringify(exit)}`);
    }
    const visible = await waitForWindow(
      primary.child.pid,
      (state) => state.handle !== 0 && state.title === 'QoderWake' && state.responding,
      `Interactive launch ${index + 1}`,
    );
    stableHandle ??= visible.handle;
    if (visible.handle !== stableHandle) {
      throw new Error('Repeated interactive launch replaced the existing visible window.');
    }
    process.stdout.write(`standalone-window: interactive-${index + 1}\n`);
  }

  const contentionStartedAt = Date.now();
  contended = launch([`--user-data-dir=${contendedUserData}`, '--remote-debugging-port=0'], {
    ...environment,
    WORKDUDE_LOCAL_UI_PORT: String(contendedPort),
  });
  await waitForWindow(
    contended.child.pid,
    (state) => state.handle !== 0 && state.title === 'QoderWake' && state.responding,
    'Browser Native lease-contended launch',
  );
  await waitForResidentServer(contendedPort, contended.exited, contended.stderr);
  await waitForStderrMarker(
    contended,
    'Browser Connector native registration skipped:',
    NATIVE_LEASE_CONTENTION_PROOF_MS + 15_000,
  );
  await proveHealthyWindowForDuration(contended, contendedPort, 5_000);
  nativeLeaseContentionSurvivedMs = Date.now() - contentionStartedAt;
  if (nativeLeaseContentionSurvivedMs < NATIVE_LEASE_CONTENTION_PROOF_MS) {
    throw new Error(
      `Browser Native contention proof ended too early: ${nativeLeaseContentionSurvivedMs} ms.`,
    );
  }
  if (contended.stderr().includes('Desktop startup failed:')) {
    throw new Error('Browser Native lease contention escaped its subsystem boundary.');
  }
  await durableStateFingerprint(contendedUserData);
  contendedRuntimeHealth = await contendedAgentRuntimeHealth(contendedUserData);
  await stopLaunch(contended, 'Contended Desktop');
  contended = undefined;
  await assertBrowserNativePipeHeld('Primary Desktop Browser Native process lease after contention');
  process.stdout.write('standalone-window: native-lease-contention-isolated\n');

  const closeResult = await powershell(
    `$p=Get-Process -Id ${Number(primary.child.pid)} -ErrorAction Stop; if(-not $p.CloseMainWindow()){exit 2}`,
  );
  void closeResult;
  await waitForWindow(primary.child.pid, (state) => state.handle === 0, 'Standalone window close');
  process.stdout.write('standalone-window: closed\n');
  process.stdout.write('standalone-window: reopen-launch\n');
  const reopenStartedAt = Date.now();
  const reopen = launch(args, environment);
  const reopenExit = await Promise.race([reopen.exited, delay(5_000, null)]);
  process.stdout.write(`standalone-window: reopen-exit=${JSON.stringify(reopenExit)}\n`);
  if (reopenExit === null || reopenExit.error || reopenExit.code !== 0 || reopenExit.signal !== null) {
    throw new Error(`Standalone window reopen did not hand off cleanly: ${JSON.stringify(reopenExit)}`);
  }
  const reopened = await waitForWindow(
    primary.child.pid,
    (state) => state.handle !== 0 && state.title === 'QoderWake' && state.responding,
    'Standalone window reopen',
  );
  const reopenLatencyMs = Date.now() - reopenStartedAt;
  if (reopenLatencyMs > MAX_INTERACTIVE_WINDOW_MS) {
    throw new Error(`Reopened window exceeded ${MAX_INTERACTIVE_WINDOW_MS} ms: ${reopenLatencyMs} ms`);
  }
  process.stdout.write(`standalone-window: reopen-state=${JSON.stringify(reopened)}\n`);
  if (reopened.handle === stableHandle) {
    throw new Error('Closed standalone window was not recreated with a new native handle.');
  }
  const reopenedDurableState = await durableStateFingerprint(userData);
  if (reopenedDurableState.digest !== restartedDurableState.digest) {
    throw new Error('Closing and reopening the standalone window changed durable product state.');
  }
  process.stdout.write('standalone-window: reopened\n');
  process.stdout.write(
    `${JSON.stringify({
      status: 'passed',
      backgroundWindowCount: 0,
      interactiveLaunches: 10,
      processCount: 1,
      visibleWindowCount: 1,
      closeReopen: true,
      coldInteractiveLatencyMs,
      reopenLatencyMs,
      nativeLeaseContentionSurvivedMs,
      browserNativeLeaseContentionIsolated: true,
      contendedRuntimeHealth,
      executableVersion: expectedVersion,
      executableSha256,
      durableStatePreserved: true,
      durableRoleTemplateCount: reopenedDurableState.count,
    })}\n`,
  );
} catch (cause) {
  operationFailure = cause;
}

let cleanupFailure;
try {
  process.stdout.write('standalone-window: cleanup-start\n');
  if (contended) await stopLaunch(contended, 'Contended Desktop cleanup');
  if (cold) await stopLaunch(cold, 'Cold Desktop cleanup');
  if (primary) await stopLaunch(primary, 'Primary Desktop cleanup');
  await assertNoVerifierProcesses(root);
  await assertBrowserNativePipeAvailable('Browser Native process lease before verifier-owned cleanup');
  process.stdout.write('standalone-window: cleanup-primary-stopped\n');
  await cleanupVerifierOwnedBrowserNativeRegistry(userData);
  process.stdout.write('standalone-window: verifier-owned-registry-cleanup-finished\n');
  await assertBrowserNativeRegistryAbsent();
  await assertBrowserNativePipeAvailable('Browser Native process lease after verifier-owned cleanup');
  await rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 250 });
  process.stdout.write('standalone-window: cleanup-complete\n');
} catch (cause) {
  cleanupFailure = cause;
}

if (operationFailure && cleanupFailure) {
  throw new AggregateError(
    [operationFailure, cleanupFailure],
    'Standalone-window verification and cleanup both failed',
    { cause: cleanupFailure },
  );
}
if (operationFailure) throw operationFailure;
if (cleanupFailure) throw cleanupFailure;
