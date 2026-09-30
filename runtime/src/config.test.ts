import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { randomBytes } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

const token = randomBytes(32).toString('hex');

async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as { port: number }).port;
  await new Promise<void>(resolve => server.close(() => resolve()));
  return port;
}

function launch(port: number, overrides: NodeJS.ProcessEnv = {}) {
  const child = spawn(process.execPath, ['--import', 'tsx', 'src/server.ts'], {
    cwd: process.cwd(), windowsHide: true,
    env: { ...process.env, ATOM_ENVIRONMENT: 'test', ATOM_RUNTIME_HOST: '127.0.0.1',
      ATOM_RUNTIME_PORT: String(port), ATOM_RUNTIME_TOKEN: token, ...overrides },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const done = new Promise<number | null>((resolve, reject) => {
    child.once('error', reject); child.once('exit', resolve);
  });
  return { child, done, output: () => output };
}

async function boundedExit(run: ReturnType<typeof launch>): Promise<number | null> {
  let timer: ReturnType<typeof setTimeout>;
  try {
    return await Promise.race([run.done, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error('startup did not fail within 8 seconds')), 8000);
    })]);
  } finally { clearTimeout(timer!); }
}

test('runtime refuses invalid configuration before listening', { timeout: 60000 }, async () => {
  for (const overrides of [
    { ATOM_RUNTIME_TOKEN: '' }, { ATOM_RUNTIME_TOKEN: 'change-me' },
    { ATOM_RUNTIME_TOKEN: 'do-not-echo-secret-with-newline-123456\n' },
    { ATOM_ENVIRONMENT: 'production', ATOM_SANDBOX_MODE: 'local' },
    { ATOM_SANDBOX_MODE: 'broker' }, { ATOM_SANDBOX_MODE: 'invalid' },
    { ATOM_ENVIRONMENT: 'typo' }, { ATOM_RUNTIME_PORT: 'NaN' },
    { ATOM_RUNTIME_PORT: '0' }, { ATOM_RUNTIME_PORT: '65536' },
    { ATOM_ENVIRONMENT: 'production', ATOM_RUNTIME_HOST: '0.0.0.0' },
  ]) {
    const run = launch(await freePort(), overrides);
    try {
      assert.notEqual(await boundedExit(run), 0);
      assert.ok(!run.output().includes('listening on'));
      assert.ok(!run.output().includes(token));
      assert.ok(!run.output().includes('do-not-echo-secret'));
    } finally { if (run.child.exitCode === null) run.child.kill(); await run.done; }
  }
});

test('actual runtime HTTP surface requires service authentication', { timeout: 20000 }, async () => {
  const port = await freePort();
  const run = launch(port, { ATOM_ENVIRONMENT: 'production', ATOM_SANDBOX_MODE: 'broker', ATOM_BROKER_ORIGIN: 'http://127.0.0.1:8766', ATOM_EXECUTION_ORIGIN: 'http://127.0.0.1:8765' });
  try {
    const deadline = Date.now() + 8000;
    while (!run.output().includes('listening on')) {
      if (run.child.exitCode !== null || Date.now() > deadline) throw new Error('runtime failed to become ready');
      await delay(50);
    }
    for (const [method, path] of [['GET', '/healthz'], ['GET', '/v1/roles'], ['POST', '/v1/runs'], ['POST', '/v1/runs/probe/cancel']]) {
      for (const authorization of ['', 'Bearer wrong-value']) {
        const response = await fetch(`http://127.0.0.1:${port}${path}`, {
          method, headers: { authorization }, signal: AbortSignal.timeout(3000),
        });
        assert.equal(response.status, 401, path);
        await response.text();
      }
    }
    for (const path of ['/healthz', '/v1/roles']) {
      const response = await fetch(`http://127.0.0.1:${port}${path}`, {
        headers: { authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(3000),
      });
      assert.equal(response.status, 200);
      await response.json();
    }
  } finally { run.child.kill(); await boundedExit(run); }
});
