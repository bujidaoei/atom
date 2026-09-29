import type { V3GroupRunQueueTransition } from '../../product-contracts/src/v3-ports.ts';

const V3_DISPATCH_KEY = /^(?:initial|plan-[1-9][0-9]*)$/u;

export interface V3RunExecutionLease {
  readonly executionClaim: { dispatchKey: string; claimId: string };
  assertOwned(): void;
  renewNow(): Promise<boolean>;
  close(): void;
}

export async function acquireV3RunExecutionLease(input: {
  runId: string;
  dispatchKey: string;
  claimId: string;
  claim(): Promise<boolean>;
  renew(): Promise<boolean>;
  leaseMs?: number;
  heartbeatMs?: number;
  onOwnershipLost?(cause: Error): void;
}): Promise<V3RunExecutionLease | null> {
  if (!V3_DISPATCH_KEY.test(input.dispatchKey)) throw new Error('Invalid Run execution dispatch key');
  if (!input.claimId.trim()) throw new Error('Run execution claim ID is required');
  const leaseMs = input.leaseMs ?? 30_000;
  const heartbeatMs = input.heartbeatMs ?? Math.max(1_000, Math.floor(leaseMs / 3));
  if (!Number.isInteger(leaseMs) || leaseMs < 1_000) throw new Error('Invalid Run execution lease');
  if (!Number.isInteger(heartbeatMs) || heartbeatMs <= 0 || heartbeatMs >= leaseMs) {
    throw new Error('Invalid Run execution heartbeat');
  }
  const claimedAt = performance.now();
  if (!(await input.claim())) return null;

  let state: 'owned' | 'lost' | 'closed' = 'owned';
  let renewing = false;
  let deadline = claimedAt + leaseMs;
  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  const loseOwnership = (cause: unknown): false => {
    if (state !== 'owned') return false;
    state = 'lost';
    clearTimeout(expiryTimer);
    const error =
      cause instanceof Error
        ? new Error(`Run execution claim was lost: ${cause.message}`, { cause })
        : new Error('Run execution claim was lost');
    input.onOwnershipLost?.(error);
    return false;
  };
  const expired = (): boolean => performance.now() >= deadline;
  const armExpiry = () => {
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(
      () => {
        loseOwnership(new Error('lease expired before renewal completed'));
      },
      Math.max(0, deadline - performance.now()),
    );
    expiryTimer.unref?.();
  };
  if (expired()) {
    loseOwnership(new Error('lease expired before claim completed'));
    return null;
  }
  armExpiry();
  const renewNow = async (): Promise<boolean> => {
    if (state !== 'owned') return false;
    if (expired()) return loseOwnership(new Error('lease expired'));
    const renewalStartedAt = performance.now();
    try {
      const renewed = await input.renew();
      if (state !== 'owned') return false;
      if (expired()) return loseOwnership(new Error('lease expired before renewal completed'));
      if (!renewed) return loseOwnership(new Error('lease renewal was rejected'));
      // Starting at request dispatch is conservative: network latency must not extend ownership.
      deadline = Math.max(deadline, renewalStartedAt + leaseMs);
      armExpiry();
      return true;
    } catch (cause) {
      return loseOwnership(cause);
    }
  };
  const timer = setInterval(() => {
    if (renewing || state !== 'owned') return;
    renewing = true;
    void renewNow().finally(() => {
      renewing = false;
    });
  }, heartbeatMs);
  timer.unref?.();

  return {
    executionClaim: { dispatchKey: input.dispatchKey, claimId: input.claimId },
    assertOwned() {
      if (state === 'owned' && expired()) loseOwnership(new Error('lease expired'));
      if (state !== 'owned') throw new Error('Run execution claim was lost');
    },
    renewNow,
    close() {
      if (state === 'closed') return;
      clearInterval(timer);
      clearTimeout(expiryTimer);
      state = 'closed';
    },
  };
}

export async function applyV3GroupRunQueueTransition(
  transition: V3GroupRunQueueTransition | null | undefined,
  operations: {
    publish(runId: string): Promise<void>;
    dispatch(runId: string, dispatchKey: 'initial'): Promise<void>;
  },
): Promise<void> {
  if (!transition) return;
  const publishRunIds = [
    ...new Set([...transition.preemptedRunIds, ...transition.affectedRunIds, ...transition.releasedRunIds]),
  ];
  for (const runId of publishRunIds) await operations.publish(runId);
  for (const runId of transition.dispatchRunIds) await operations.dispatch(runId, 'initial');
}
