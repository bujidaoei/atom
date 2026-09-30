import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runWithRecovery } from './run-recovery.ts';

const truncated = () => new Error('AI gateway response was truncated before completion.');
test('bounded recovery preserves recovery flag and returns only final result', async () => {
  const calls: boolean[] = [];
  const events: number[] = [];
  const result = await runWithRecovery({
    signal: new AbortController().signal,
    async run(recovery) { calls.push(recovery); if (calls.length < 3) throw truncated(); return 'done'; },
    onRecover(attempt) { events.push(attempt); },
  });
  assert.equal(result, 'done');
  assert.deepEqual(calls, [false, true, true]);
  assert.deepEqual(events, [1, 2]);
});
test('exhaustion, other errors and cancellation cannot retry forever', async () => {
  for (const mode of ['exhausted', 'other', 'cancelled']) {
    const controller = new AbortController();
    let calls = 0;
    await assert.rejects(runWithRecovery({
      signal: controller.signal,
      async run() {
        calls++;
        if (mode === 'cancelled') controller.abort();
        throw mode === 'other' ? new Error('tool failed') : truncated();
      },
      onRecover() {},
    }));
    assert.equal(calls, mode === 'exhausted' ? 3 : 1);
  }
});
