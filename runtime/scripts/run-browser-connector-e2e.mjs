import { spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { resolve } from 'node:path';

const root = process.cwd();
const platformPort = await new Promise((resolvePort, reject) => {
  const server = createServer();
  server.once('error', reject);
  server.listen(0, '127.0.0.1', () => {
    const address = server.address();
    if (!address || typeof address === 'string') {
      server.close();
      reject(new Error('Unable to reserve a Browser Connector platform test port.'));
      return;
    }
    server.close((error) => (error ? reject(error) : resolvePort(address.port)));
  });
});

const result = spawnSync(
  process.execPath,
  [
    resolve(root, 'scripts', 'run-playwright.mjs'),
    'tests/e2e/v3/skill-connector-visual.spec.ts',
    '--workers=1',
  ],
  {
    cwd: root,
    env: {
      ...process.env,
      PLAYWRIGHT_PLATFORM_PORT: String(platformPort),
      WORKDUDE_DEV_PLATFORM_ORIGIN: `http://127.0.0.1:${platformPort}`,
    },
    stdio: 'inherit',
  },
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
