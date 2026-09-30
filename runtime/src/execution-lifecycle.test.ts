import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withExecution } from './execution-lifecycle.ts';
import { runWithRecovery } from './run-recovery.ts';

test('model recovery remains inside one acquisition and one final checkpoint', async () => {
  const calls: string[] = [];
  await withExecution({
    sandbox: { async create() { calls.push('create'); return 'owned'; }, async destroy() { calls.push('release'); } },
    completion: { async complete() { calls.push('commit'); return 'receipt'; }, async cancel() { calls.push('cancel'); } },
    runId: 'run', workspaceId: 'workspace',
  }, async () => runWithRecovery({ signal: new AbortController().signal, onRecover() {},
    async run(recovery) {
      calls.push(recovery ? 'recover' : 'initial');
      if (!recovery) throw new Error('AI gateway response was truncated before completion');
      return 'result';
    },
  }));
  assert.deepEqual(calls, ['create', 'initial', 'recover', 'commit', 'release']);
});

test('completion is awaited before release and returning work', async () => {
  const calls: string[] = [];
  const result = await withExecution({
    sandbox: { async create(run: string, workspace: string) { calls.push(`${run}:${workspace}`); return 'sandbox'; },
      async destroy() { calls.push('release'); } },
    completion: { async complete() { calls.push('commit'); return { revision_id: 'revision' }; },
      async cancel() { assert.fail('cancel after success'); } },
    runId: 'run', workspaceId: 'real-workspace',
  }, async id => { assert.equal(id, 'sandbox'); calls.push('work'); return 42; });
  assert.deepEqual(calls, ['run:real-workspace', 'work', 'commit', 'release']);
  assert.deepEqual(result, { value: 42, receipt: { revision_id: 'revision' } });
});

test('operation or completion failure cancels before release, retaining every failure', async () => {
  for (const phase of ['work', 'commit']) {
    const original = new Error(phase);
    const cancel = new Error('cancel unavailable');
    const release = new Error('release unavailable');
    const calls: string[] = [];
    await assert.rejects(withExecution({
      sandbox: { async create() { return 'sandbox'; }, async destroy() { calls.push('release'); throw release; } },
      completion: { async complete() { throw original; }, async cancel() { calls.push('cancel'); throw cancel; } },
      runId: 'run', workspaceId: 'workspace',
    }, async () => { if (phase === 'work') throw original; return 1; }), error => {
      assert.ok(error instanceof AggregateError);
      assert.deepEqual(error.errors, [original, cancel, release]);
      return true;
    });
    assert.deepEqual(calls, ['cancel', 'release']);
  }
});

test('failed acquisition cancels the reserved execution without inventing a sandbox ID', async () => {
  const original = new Error('acquisition failed');
  let cancelled = false;
  await assert.rejects(withExecution({
    sandbox: { async create() { throw original; }, async destroy() { assert.fail('unacquired release'); } },
    completion: { async complete() { assert.fail('unacquired completion'); }, async cancel() { cancelled = true; } },
    runId: 'run', workspaceId: 'workspace',
  }, async () => assert.fail('unacquired work')), error => error === original);
  assert.equal(cancelled, true);
});
