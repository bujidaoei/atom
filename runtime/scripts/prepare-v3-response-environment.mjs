import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const root = process.cwd();
const environmentFile = resolve(root, '.env');
if (!existsSync(environmentFile)) {
  throw new Error('The protected .env file is required for the real response E2E gate.');
}

const compose = spawnSync(
  'docker',
  [
    'compose',
    '--env-file',
    environmentFile,
    '-f',
    resolve(root, 'deploy/compose/compose.yaml'),
    'up',
    '-d',
    '--build',
  ],
  { cwd: root, env: process.env, stdio: 'inherit' },
);
if (compose.error) throw compose.error;
if (compose.status !== 0) {
  throw new Error(`V3 response environment failed to start (exit ${compose.status ?? 1}).`);
}

const origin = process.env.WORKDUDE_V3_WEB_ORIGIN ?? 'http://127.0.0.1:8080';
const deadline = Date.now() + 180_000;
let lastFailure;
let ready = false;
while (Date.now() < deadline) {
  try {
    const response = await globalThis.fetch(origin);
    if (response.ok) {
      await response.body?.cancel();
      console.log(`[v3-response] Web deployment is ready at ${origin}.`);
      ready = true;
      break;
    }
    lastFailure = new Error(`HTTP ${response.status}`);
    await response.body?.cancel();
  } catch (cause) {
    lastFailure = cause;
  }
  await delay(1_000);
}
if (!ready) {
  throw new Error('V3 response environment did not become ready.', { cause: lastFailure });
}
