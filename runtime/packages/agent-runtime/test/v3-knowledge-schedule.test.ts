import { describe, expect, it, vi } from 'vitest';

import {
  dueV3KnowledgeScheduleOccurrence,
  V3KnowledgeScheduler,
  type V3KnowledgeScheduledWork,
} from '../src/v3-knowledge-schedule.ts';

interface LeaseState {
  ownerId: string | null;
  expiresAt: number;
  terminal: boolean;
}

class DeterministicLeaseRepository {
  readonly work: V3KnowledgeScheduledWork<string> = { runId: 'recoverable-run', jobs: ['compile'] };
  readonly successfulFinishes: string[] = [];
  readonly renewals: string[] = [];
  readonly claims: string[] = [];
  private readonly lease: LeaseState = { ownerId: null, expiresAt: 0, terminal: false };

  async listEnabledScheduleCandidates() {
    return [];
  }

  async claimScheduleRun() {
    return null;
  }

  async claimRecoverableScheduleRuns(ownerId: string, leaseDurationMs: number) {
    if (this.lease.terminal || (this.lease.ownerId !== null && this.lease.expiresAt > Date.now())) return [];
    this.lease.ownerId = ownerId;
    this.lease.expiresAt = Date.now() + leaseDurationMs;
    this.claims.push(ownerId);
    return [this.work];
  }

  async renewScheduleRunLease(runId: string, ownerId: string, leaseDurationMs: number) {
    if (
      runId !== this.work.runId ||
      this.lease.terminal ||
      this.lease.ownerId !== ownerId ||
      this.lease.expiresAt <= Date.now()
    ) {
      return false;
    }
    this.lease.expiresAt = Date.now() + leaseDurationMs;
    this.renewals.push(ownerId);
    return true;
  }

  async finishScheduleRun(runId: string, ownerId: string, _failureDetail: string | null) {
    if (
      runId !== this.work.runId ||
      this.lease.terminal ||
      this.lease.ownerId !== ownerId ||
      this.lease.expiresAt <= Date.now()
    ) {
      return false;
    }
    this.lease.terminal = true;
    this.lease.ownerId = null;
    this.lease.expiresAt = 0;
    this.successfulFinishes.push(ownerId);
    return true;
  }
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((completion) => {
    resolve = completion;
  });
  return { promise, resolve };
}

describe('V3 Knowledge schedule occurrence', () => {
  it('honors the schedule timezone and never backfills before creation', () => {
    const input = {
      schedule: '0 9 * * 1-5',
      timezone: 'Asia/Shanghai',
      createdAt: '2026-08-14T00:00:00.000Z',
      lastRunAt: null,
    };
    expect(dueV3KnowledgeScheduleOccurrence(input, new Date('2026-08-17T01:00:20.000Z'))).toBe(
      '2026-08-17T01:00:00.000Z',
    );
    expect(
      dueV3KnowledgeScheduleOccurrence(
        { ...input, createdAt: '2026-08-17T01:00:10.000Z' },
        new Date('2026-08-17T01:00:20.000Z'),
      ),
    ).toBeUndefined();
  });

  it('returns only occurrences newer than the persisted last run', () => {
    const input = {
      schedule: '*/30 * * * *',
      timezone: 'Asia/Shanghai',
      createdAt: '2026-08-15T00:00:00.000Z',
      lastRunAt: '2026-08-15T10:30:00.000Z',
    };
    expect(dueV3KnowledgeScheduleOccurrence(input, new Date('2026-08-15T10:45:00.000Z'))).toBeUndefined();
    expect(dueV3KnowledgeScheduleOccurrence(input, new Date('2026-08-15T11:00:01.000Z'))).toBe(
      '2026-08-15T11:00:00.000Z',
    );
  });

  it('rejects invalid cron expressions instead of silently rescheduling them', () => {
    expect(() =>
      dueV3KnowledgeScheduleOccurrence(
        {
          schedule: 'not a cron value',
          timezone: 'Asia/Shanghai',
          createdAt: '2026-08-15T00:00:00.000Z',
          lastRunAt: null,
        },
        new Date('2026-08-15T10:00:00.000Z'),
      ),
    ).toThrow();
  });

  it('lets only one of two schedulers execute and finish the same recoverable run', async () => {
    const repository = new DeterministicLeaseRepository();
    const processed: string[] = [];
    const schedulerA = new V3KnowledgeScheduler({
      repository,
      ownerId: 'scheduler-a',
      process: async () => {
        processed.push('scheduler-a');
      },
    });
    const schedulerB = new V3KnowledgeScheduler({
      repository,
      ownerId: 'scheduler-b',
      process: async () => {
        processed.push('scheduler-b');
      },
    });

    await Promise.all([schedulerA.runOnce(), schedulerB.runOnce()]);

    expect(repository.claims).toHaveLength(1);
    expect(processed).toEqual([repository.claims[0]]);
    expect(repository.successfulFinishes).toEqual(repository.claims);
  });

  it('renews a live owner lease so another scheduler cannot take over a long run', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-23T00:00:00.000Z'));
    try {
      const repository = new DeterministicLeaseRepository();
      const longJob = deferred<void>();
      const processed: string[] = [];
      const schedulerA = new V3KnowledgeScheduler({
        repository,
        ownerId: 'scheduler-a',
        leaseDurationMs: 9_000,
        heartbeatIntervalMs: 3_000,
        process: async () => {
          processed.push('scheduler-a');
          await longJob.promise;
        },
      });
      const schedulerB = new V3KnowledgeScheduler({
        repository,
        ownerId: 'scheduler-b',
        leaseDurationMs: 9_000,
        heartbeatIntervalMs: 3_000,
        process: async () => {
          processed.push('scheduler-b');
        },
      });

      const runningA = schedulerA.runOnce();
      await vi.advanceTimersByTimeAsync(6_000);
      await schedulerB.runOnce();
      expect(repository.renewals).toHaveLength(3);
      expect(new Set(repository.renewals)).toEqual(new Set(['scheduler-a']));
      expect(processed).toEqual(['scheduler-a']);

      longJob.resolve();
      await runningA;
      expect(repository.successfulFinishes).toEqual(['scheduler-a']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('rejects stale renewal and finish after expiry, then lets a new owner recover', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-23T00:00:00.000Z'));
    try {
      const repository = new DeterministicLeaseRepository();
      await expect(repository.claimRecoverableScheduleRuns('scheduler-a', 9_000)).resolves.toHaveLength(1);
      await vi.advanceTimersByTimeAsync(9_001);
      await expect(repository.renewScheduleRunLease('recoverable-run', 'scheduler-a', 9_000)).resolves.toBe(
        false,
      );
      await expect(repository.finishScheduleRun('recoverable-run', 'scheduler-a', null)).resolves.toBe(false);

      const processed: string[] = [];
      const schedulerB = new V3KnowledgeScheduler({
        repository,
        ownerId: 'scheduler-b',
        leaseDurationMs: 9_000,
        heartbeatIntervalMs: 3_000,
        process: async () => {
          processed.push('scheduler-b');
        },
      });
      await schedulerB.runOnce();

      expect(processed).toEqual(['scheduler-b']);
      expect(repository.successfulFinishes).toEqual(['scheduler-b']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('aborts processing and never finishes when heartbeat renewal loses ownership', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-23T00:00:00.000Z'));
    try {
      const aborted = deferred<void>();
      const finishScheduleRun = vi.fn(async () => true);
      const onError = vi.fn();
      const renewScheduleRunLease = vi.fn().mockResolvedValueOnce(true).mockResolvedValue(false);
      const process = vi.fn(async (currentJob: string, signal: AbortSignal) => {
        if (currentJob === 'first') {
          signal.addEventListener('abort', () => aborted.resolve(), { once: true });
          await aborted.promise;
          signal.throwIfAborted();
        }
      });
      const scheduler = new V3KnowledgeScheduler({
        ownerId: 'scheduler-a',
        leaseDurationMs: 9_000,
        heartbeatIntervalMs: 3_000,
        repository: {
          async claimRecoverableScheduleRuns() {
            return [{ runId: 'lost-run', jobs: ['first', 'second'] }];
          },
          async listEnabledScheduleCandidates() {
            return [];
          },
          async claimScheduleRun() {
            return null;
          },
          renewScheduleRunLease,
          finishScheduleRun,
        },
        process,
        onError,
      });

      const running = scheduler.runOnce();
      await vi.advanceTimersByTimeAsync(3_000);
      await running;

      expect(finishScheduleRun).not.toHaveBeenCalled();
      expect(process).toHaveBeenCalledTimes(1);
      expect(process).toHaveBeenCalledWith('first', expect.any(AbortSignal));
      expect(onError).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'V3KnowledgeScheduleLeaseLostError' }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('preserves a renewal exception as the lease-loss cause and stops all later work', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-23T00:00:00.000Z'));
    try {
      const renewalFailure = new Error('lease database unavailable');
      const aborted = deferred<void>();
      const finishScheduleRun = vi.fn(async () => true);
      const onError = vi.fn();
      const renewScheduleRunLease = vi.fn().mockResolvedValueOnce(true).mockRejectedValueOnce(renewalFailure);
      let processingSignal: AbortSignal | undefined;
      const process = vi.fn(async (currentJob: string, signal: AbortSignal) => {
        processingSignal = signal;
        if (currentJob === 'first') {
          signal.addEventListener('abort', () => aborted.resolve(), { once: true });
          await aborted.promise;
          signal.throwIfAborted();
        }
      });
      const scheduler = new V3KnowledgeScheduler({
        ownerId: 'scheduler-a',
        leaseDurationMs: 9_000,
        heartbeatIntervalMs: 3_000,
        repository: {
          async claimRecoverableScheduleRuns() {
            return [{ runId: 'renewal-error-run', jobs: ['first', 'second'] }];
          },
          async listEnabledScheduleCandidates() {
            return [];
          },
          async claimScheduleRun() {
            return null;
          },
          renewScheduleRunLease,
          finishScheduleRun,
        },
        process,
        onError,
      });

      const running = scheduler.runOnce();
      await vi.advanceTimersByTimeAsync(3_000);
      await running;

      expect(processingSignal).toMatchObject({ aborted: true });
      expect(process).toHaveBeenCalledTimes(1);
      expect(finishScheduleRun).not.toHaveBeenCalled();
      expect(onError).toHaveBeenCalledOnce();
      expect(onError.mock.calls[0]![0]).toMatchObject({
        name: 'V3KnowledgeScheduleLeaseLostError',
        cause: renewalFailure,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('stops heartbeat renewal before the final fence and successful finish', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-23T00:00:00.000Z'));
    try {
      const processing = deferred<void>();
      const heartbeatRenewal = deferred<boolean>();
      const finalRenewal = deferred<boolean>();
      const finishScheduleRun = vi.fn(async () => true);
      const onError = vi.fn();
      const renewScheduleRunLease = vi
        .fn()
        .mockResolvedValueOnce(true)
        .mockImplementationOnce(async () => heartbeatRenewal.promise)
        .mockImplementationOnce(async () => finalRenewal.promise)
        .mockResolvedValue(false);
      const scheduler = new V3KnowledgeScheduler({
        ownerId: 'scheduler-a',
        leaseDurationMs: 9_000,
        heartbeatIntervalMs: 3_000,
        repository: {
          async claimRecoverableScheduleRuns() {
            return [{ runId: 'finish-race-run', jobs: ['only-job'] }];
          },
          async listEnabledScheduleCandidates() {
            return [];
          },
          async claimScheduleRun() {
            return null;
          },
          renewScheduleRunLease,
          finishScheduleRun,
        },
        process: async () => processing.promise,
        onError,
      });

      const running = scheduler.runOnce();
      await vi.advanceTimersByTimeAsync(3_000);
      expect(renewScheduleRunLease).toHaveBeenCalledTimes(2);

      processing.resolve();
      heartbeatRenewal.resolve(true);
      await vi.advanceTimersByTimeAsync(0);
      expect(renewScheduleRunLease).toHaveBeenCalledTimes(3);

      await vi.advanceTimersByTimeAsync(3_000);
      expect(renewScheduleRunLease).toHaveBeenCalledTimes(3);
      finalRenewal.resolve(true);
      await running;
      await vi.advanceTimersByTimeAsync(30_000);

      expect(renewScheduleRunLease).toHaveBeenCalledTimes(3);
      expect(finishScheduleRun).toHaveBeenCalledOnce();
      expect(onError).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('records real processing failures after attempting every job while the lease remains live', async () => {
    const completed: Array<[string, string, string | null]> = [];
    const scheduler = new V3KnowledgeScheduler({
      ownerId: 'scheduler-a',
      repository: {
        async claimRecoverableScheduleRuns() {
          return [{ runId: 'failed-run', jobs: ['first', 'second'] }];
        },
        async listEnabledScheduleCandidates() {
          return [];
        },
        async claimScheduleRun() {
          return null;
        },
        async renewScheduleRunLease() {
          return true;
        },
        async finishScheduleRun(runId: string, ownerId: string, failure: string | null) {
          completed.push([runId, ownerId, failure]);
          return true;
        },
      },
      process: async (job) => {
        throw new Error(`${job} failed key=${job}-secret`);
      },
    });
    await scheduler.runOnce();
    expect(completed).toEqual([
      ['failed-run', 'scheduler-a', 'first failed key=[REDACTED] second failed key=[REDACTED]'],
    ]);
  });
});
