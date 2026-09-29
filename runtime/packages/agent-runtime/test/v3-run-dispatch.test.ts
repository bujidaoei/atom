import { describe, expect, it, vi } from 'vitest';

import { acquireV3RunExecutionLease, applyV3GroupRunQueueTransition } from '../src/v3-run-dispatch.ts';

describe('V3 durable Run dispatch', () => {
  it('extends expiry only after confirmed renewal and cancels expiry when closed', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance'],
    });
    const abort = vi.fn();
    const renew = vi.fn().mockResolvedValue(true);
    const lease = await acquireV3RunExecutionLease({
      runId: 'run-renewed',
      dispatchKey: 'initial',
      claimId: 'owner',
      leaseMs: 3_000,
      heartbeatMs: 1_000,
      claim: async () => true,
      renew,
      onOwnershipLost: abort,
    });
    try {
      await vi.advanceTimersByTimeAsync(10_000);
      expect(renew).toHaveBeenCalledTimes(10);
      lease!.assertOwned();
      lease!.close();
      await vi.advanceTimersByTimeAsync(5_000);
      expect(renew).toHaveBeenCalledTimes(10);
      expect(abort).not.toHaveBeenCalled();
    } finally {
      lease?.close();
      vi.useRealTimers();
    }
  });
  it('expires ownership while renewal is hung and never revives it on a late success', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance'],
    });
    let completeRenew!: (value: boolean) => void;
    const abort = vi.fn();
    const lease = await acquireV3RunExecutionLease({
      runId: 'run-hung-renewal',
      dispatchKey: 'initial',
      claimId: 'owner',
      leaseMs: 3_000,
      heartbeatMs: 1_000,
      claim: async () => true,
      renew: () =>
        new Promise<boolean>((resolve) => {
          completeRenew = resolve;
        }),
      onOwnershipLost: abort,
    });
    try {
      await vi.advanceTimersByTimeAsync(3_000);
      expect(abort).toHaveBeenCalledOnce();
      expect(() => lease!.assertOwned()).toThrow('claim was lost');
      completeRenew(true);
      await vi.advanceTimersByTimeAsync(0);
      expect(() => lease!.assertOwned()).toThrow('claim was lost');
      expect(abort).toHaveBeenCalledOnce();
    } finally {
      completeRenew?.(true);
      lease?.close();
      vi.useRealTimers();
    }
  });
  it('fails closed before any execution side effect when the dispatch key cannot be claimed', async () => {
    const renew = vi.fn();
    const lease = await acquireV3RunExecutionLease({
      runId: 'run-waiting',
      dispatchKey: 'initial',
      claimId: 'worker-claim',
      claim: vi.fn().mockResolvedValue(false),
      renew,
    });

    expect(lease).toBeNull();
    expect(renew).not.toHaveBeenCalled();
  });

  it('aborts the execution owner and rejects further work when lease renewal is lost', async () => {
    vi.useFakeTimers();
    const abort = vi.fn();
    const lease = await acquireV3RunExecutionLease({
      runId: 'run-active',
      dispatchKey: 'plan-2',
      claimId: 'worker-claim',
      leaseMs: 3_000,
      heartbeatMs: 1_000,
      claim: vi.fn().mockResolvedValue(true),
      renew: vi.fn().mockResolvedValue(false),
      onOwnershipLost: abort,
    });

    expect(lease).not.toBeNull();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(abort).toHaveBeenCalledOnce();
    expect(() => lease!.assertOwned()).toThrow('Run execution claim was lost');
    lease!.close();
    vi.useRealTimers();
  });

  it('publishes every transitioned Run before dispatching the released batch', async () => {
    const order: string[] = [];
    await applyV3GroupRunQueueTransition(
      {
        targetBatchId: 'waiting-batch',
        affectedRunIds: ['waiting-a', 'waiting-b'],
        preemptedRunIds: ['active-a'],
        releasedRunIds: ['waiting-a', 'waiting-b'],
        dispatchRunIds: ['waiting-a', 'waiting-b'],
      },
      {
        publish: async (runId) => {
          order.push(`publish:${runId}`);
        },
        dispatch: async (runId, dispatchKey) => {
          order.push(`dispatch:${runId}:${dispatchKey}`);
        },
      },
    );

    expect(order).toEqual([
      'publish:active-a',
      'publish:waiting-a',
      'publish:waiting-b',
      'dispatch:waiting-a:initial',
      'dispatch:waiting-b:initial',
    ]);
  });
});
