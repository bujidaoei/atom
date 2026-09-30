import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { ProductAgentRuntime } from '../packages/agent-runtime/src/product-agent-runtime.ts';
import { LocalSandboxClient } from './local-sandbox.ts';
import { withSandbox } from '../packages/agent-runtime/src/sandbox-lifecycle.ts';
import type { SandboxClient } from '../packages/product-contracts/src/index.ts';

function fixture(overrides: Partial<SandboxClient> = {}) {
  const calls: string[] = [];
  const client: SandboxClient = {
    async create(run, workspace) { calls.push(`create:${run}:${workspace}`); return 'owned'; },
    async destroy(id) { calls.push(`destroy:${id}`); },
    async exec() { throw new Error('not used in ownership contract'); },
    ...overrides,
  };
  return { client, calls };
}

test('runtime rejects mutated external scope before filesystem initialization', async () => {
  const root = await mkdtemp(join(tmpdir(), 'atom-external-scope-'));
  const { client, calls } = fixture();
  const scope = { runId: 'run', workspaceId: 'workspace', sandboxId: 'owned' };
  const runtime = new ProductAgentRuntime({ sandboxScope: scope, sandbox: client,
    agentDir: join(root, 'agent'), aiGateway: { baseUrl: 'http://127.0.0.1:1/v1', masterKey: 'test', model: 'test' },
    approvals: { request: async () => 'approved' }, events: { async emit() {} },
  });
  scope.runId = 'other';
  try {
    await assert.rejects(runtime.run({ runId: 'other', prompt: 'unused', workspacePath: join(root, 'workspace'),
      sessionPath: join(root, 'sessions', 'session.jsonl') }), /scope mismatch/);
    const { readdir } = await import('node:fs/promises');
    assert.deepEqual(await readdir(root), []);
    assert.deepEqual(calls, []);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('successful operation awaits exactly one release before returning', async () => {
  let release: () => void = () => { throw new Error('release has not started'); };
  const calls: string[] = [];
  const { client } = fixture({ async destroy(id) {
    calls.push(id);
    await new Promise<void>(resolve => { release = resolve; });
  } });
  let settled = false;
  const promise = withSandbox(client, 'run', true, async id => { assert.equal(id, 'owned'); return 42; })
    .then(value => { settled = true; return value; });
  await new Promise<void>(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['owned']);
  assert.equal(settled, false);
  release();
  assert.equal(await promise, 42);
});

test('operation failure and cancellation each release once and retain exact cause', async () => {
  for (const cause of [new Error('initialization or disposal fault'), new DOMException('cancelled', 'AbortError'), undefined]) {
    const { client, calls } = fixture();
    let caught = false;
    try {
      await withSandbox(client, 'run', true, async () => { throw cause; });
    } catch (error) {
      caught = true;
      assert.equal(error, cause);
    }
    assert.equal(caught, true);
    assert.deepEqual(calls, ['create:run:run', 'destroy:owned']);
  }
});

test('failed acquisition never guesses a resource ID or invokes work', async () => {
  const failure = new Error('unknown acquisition outcome');
  const { client, calls } = fixture({ async create() { throw failure; } });
  await assert.rejects(withSandbox(client, 'run', true, async () => assert.fail('work after failed create')),
    error => error === failure);
  assert.deepEqual(calls, []);
});

test('tools disabled executes without acquisition or release', async () => {
  const { client, calls } = fixture();
  assert.equal(await withSandbox(client, 'run', false, async id => { assert.equal(id, undefined); return 'done'; }), 'done');
  assert.deepEqual(calls, []);
});

test('external scope rejects another run and leaves cleanup to its owner on failure', async () => {
  const { client, calls } = fixture();
  const scope = { runId: 'run', workspaceId: 'workspace', sandboxId: 'already-owned' };
  await assert.rejects(withSandbox(client, 'other', true, async () => assert.fail('wrong scope work'), scope), /scope mismatch/);
  const failure = new Error('operation failed');
  await assert.rejects(withSandbox(client, 'run', true, async id => {
    assert.equal(id, 'already-owned'); throw failure;
  }, scope), error => error === failure);
  assert.deepEqual(calls, []);
});

test('release failure prevents success without retrying', async () => {
  const failure = new Error('termination not confirmed');
  let releases = 0;
  const { client } = fixture({ async destroy() { releases++; throw failure; } });
  await assert.rejects(withSandbox(client, 'run', true, async () => 'result'), error => error === failure);
  assert.equal(releases, 1);
});

test('dual failure preserves both exact causes with fixed outer message', async () => {
  for (const operationFailure of [new Error('private operation details'), undefined]) {
    const releaseFailure = new Error('private release details');
    let releases = 0;
    const { client } = fixture({ async destroy() { releases++; throw releaseFailure; } });
    await assert.rejects(withSandbox(client, 'run', true, async () => { throw operationFailure; }), error => {
      assert.ok(error instanceof AggregateError);
      assert.equal(error.message, 'Sandbox operation and release failed');
      assert.deepEqual(error.errors, [operationFailure, releaseFailure]);
      return true;
    });
    assert.equal(releases, 1);
  }
});

test('actual runtime releases acquired sandbox when model initialization throws', { timeout: 30_000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'atom-lifecycle-'));
  const workspacePath = join(root, 'workspace');
  const local = new LocalSandboxClient({ resolveWorkspace: () => workspacePath });
  const failure = new Error('synthetic model initialization failure');
  let created = 0;
  let destroyed = 0;
  try {
    const runtime = new ProductAgentRuntime({
      agentDir: join(root, 'agent'),
      aiGateway: { baseUrl: 'http://127.0.0.1:1/v1', masterKey: 'synthetic-key', get model(): string { throw failure; } },
      sandbox: {
        async create(runId, workspaceId) { created++; return local.create(runId, workspaceId); },
        async destroy(id) { destroyed++; await local.destroy(id); },
        exec: local.exec.bind(local), fileOperation: local.fileOperation.bind(local),
      },
      approvals: { request: async () => 'approved' }, events: { async emit() {} },
    });
    await assert.rejects(runtime.run({ runId: 'initialization-failure', prompt: 'unused', workspacePath,
      sessionPath: join(root, 'session.jsonl') }), error => error === failure);
    assert.equal(created, 1);
    assert.equal(destroyed, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('actual Pi session setup failure retains release failure and calls destroy once', { timeout: 30_000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'atom-lifecycle-session-'));
  const workspacePath = join(root, 'workspace');
  const local = new LocalSandboxClient({ resolveWorkspace: () => workspacePath });
  const workFailure = new Error('synthetic event sink failure');
  const releaseFailure = new Error('synthetic adapter release failure');
  let releases = 0;
  try {
    const runtime = new ProductAgentRuntime({
      agentDir: join(root, 'agent'),
      aiGateway: { baseUrl: 'http://127.0.0.1:1/v1', masterKey: 'synthetic-key', model: 'synthetic-model', requestTimeoutMs: 5000 },
      sandbox: {
        create: local.create.bind(local), exec: local.exec.bind(local), fileOperation: local.fileOperation.bind(local),
        async destroy(id) { releases++; await local.destroy(id); throw releaseFailure; },
      },
      approvals: { request: async () => 'approved' },
      events: { async emit(type) { if (type === 'model.requested') throw workFailure; } },
    });
    await assert.rejects(runtime.run({ runId: 'session-failure', prompt: 'unused', workspacePath,
      sessionPath: join(root, 'session.jsonl') }), error => {
      assert.ok(error instanceof AggregateError);
      assert.deepEqual(error.errors, [workFailure, releaseFailure]);
      return true;
    });
    assert.equal(releases, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
