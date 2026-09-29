import { mkdirSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { resolve } from 'node:path';
import { URL } from 'node:url';

const root = process.cwd();
const temporaryDirectory = resolve(root, '.tmp', 'playwright');
mkdirSync(temporaryDirectory, { recursive: true });

const playwrightEntry = resolve(root, 'node_modules', '@playwright', 'test', 'cli.js');
const requestedTests = process.argv.slice(2);
const hasExplicitWorkers = requestedTests.some(
  (argument) => argument === '--workers' || argument.startsWith('--workers='),
);
const safeRequestedTests = hasExplicitWorkers ? requestedTests : [...requestedTests, '--workers=1'];

async function reservePort(kind) {
  return await new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close();
        reject(new Error(`Unable to reserve a Playwright ${kind} port.`));
        return;
      }
      server.close((error) => (error ? reject(error) : resolvePort(address.port)));
    });
  });
}

function portFromOrigin(rawOrigin) {
  if (!rawOrigin?.trim()) return undefined;
  try {
    const origin = new URL(rawOrigin);
    const port = Number(origin.port || (origin.protocol === 'https:' ? 443 : 80));
    return Number.isSafeInteger(port) && port >= 1 && port <= 65_535 ? String(port) : undefined;
  } catch {
    return undefined;
  }
}

const availableWebPort = process.env.PLAYWRIGHT_WEB_PORT ?? String(await reservePort('Web'));
const platformOriginOverride = process.env.WORKDUDE_DEV_PLATFORM_ORIGIN?.trim();
const availablePlatformPort =
  process.env.PLAYWRIGHT_PLATFORM_PORT ??
  portFromOrigin(platformOriginOverride) ??
  String(await reservePort('platform'));
const platformOrigin = platformOriginOverride ?? `http://127.0.0.1:${availablePlatformPort}`;
const e2eAuthMode = process.env.WORKDUDE_E2E_AUTH_MODE ?? 'legacy';
if (e2eAuthMode !== 'feishu' && e2eAuthMode !== 'legacy') {
  throw new Error('WORKDUDE_E2E_AUTH_MODE must be feishu or legacy');
}
const environment = {
  ...process.env,
  // Existing deterministic browser journeys use the isolated fixture owner.
  // Production builds and explicit Feishu auth tests must set these values to
  // `feishu` themselves; the runner never changes the production default.
  VITE_AUTH_MODE: process.env.VITE_AUTH_MODE ?? 'legacy',
  WORKDUDE_AUTH_MODE: e2eAuthMode,
  PLAYWRIGHT_WEB_PORT: availableWebPort,
  PLAYWRIGHT_PLATFORM_PORT: availablePlatformPort,
  WORKDUDE_DEV_PLATFORM_ORIGIN: platformOrigin,
  WORKDUDE_AUTOMATION_WINDOW: 'hidden',
  TEMP: temporaryDirectory,
  TMP: temporaryDirectory,
};
const run = (tests) =>
  spawnSync(process.execPath, [playwrightEntry, 'test', ...tests], {
    cwd: root,
    env: environment,
    stdio: 'inherit',
  });

if (requestedTests.length) {
  const result = run(safeRequestedTests);
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} else {
  const browserTests = readdirSync(resolve(root, 'tests', 'e2e'))
    .filter((name) => name.endsWith('.spec.ts'))
    .sort()
    .map((name) => `tests/e2e/${name}`);
  const result = run([...browserTests, '--workers=4']);
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
}
