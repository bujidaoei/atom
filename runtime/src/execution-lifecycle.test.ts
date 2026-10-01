import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ExecutionInterrupted, withExecution } from './execution-lifecycle.ts';
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

test('abort checkpoints once before release and preserves an incomplete receipt', async () => {
  for (const reason of [new DOMException('stop', 'AbortError'), new DOMException('budget', 'TimeoutError')]) {
    const controller = new AbortController();
    const calls: string[] = [];
    const expected = reason.name === 'TimeoutError' ? 'timed_out' : 'cancelled';
    await assert.rejects(withExecution({
      sandbox: { async create() { calls.push('create'); return 'owned'; },
        async destroy() { calls.push('release'); } },
      completion: { async complete() { assert.fail('complete after abort'); },
        async cancel() { assert.fail('cancel after confirmed partial'); },
        async partial(outcome) { calls.push(`partial:${outcome}`); return { outcome, receipt: 'saved' }; } },
      signal: controller.signal, runId: 'run', workspaceId: 'workspace',
    }, async () => { controller.abort(reason); controller.signal.throwIfAborted(); return 'impossible'; }), error => {
      assert.ok(error instanceof ExecutionInterrupted);
      assert.equal(error.outcome, expected);
      assert.equal(error.receipt, 'saved');
      return true;
    });
    assert.deepEqual(calls, ['create', `partial:${expected}`, 'release']);
  }
});

test('provider error uses cancel and an unknown partial response is never replayed', async () => {
  const controller = new AbortController();
  let partialCalls = 0;
  let cancels = 0;
  const completion = { async complete() { assert.fail('complete after failure'); },
    async cancel() { cancels++; }, async partial() { partialCalls++; throw new Error('unknown'); } };
  await assert.rejects(withExecution({ sandbox: { async create() { return 'owned'; }, async destroy() {} },
    completion, signal: controller.signal, runId: 'run', workspaceId: 'workspace',
  }, async () => { throw new Error('provider'); }), /provider/);
  assert.equal(partialCalls, 0);
  controller.abort(new DOMException('budget', 'TimeoutError'));
  await assert.rejects(withExecution({ sandbox: { async create() { return 'owned'; }, async destroy() {} },
    completion, signal: controller.signal, runId: 'run', workspaceId: 'workspace',
  }, async () => { controller.signal.throwIfAborted(); return 'impossible'; }), AggregateError);
  assert.equal(partialCalls, 1);
  assert.equal(cancels, 2);
});
