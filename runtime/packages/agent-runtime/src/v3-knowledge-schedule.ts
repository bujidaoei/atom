import { randomUUID } from 'node:crypto';

import { CronExpressionParser } from 'cron-parser';

import { redactKnowledgeFailureDetail } from '../../product-contracts/src/provider-correlation.ts';
import { knowledgeFailureDetail } from './run-failure.ts';

export interface V3KnowledgeScheduleOccurrenceInput {
  schedule: string;
  timezone: string;
  createdAt: string;
  lastRunAt: string | null;
}

export interface V3KnowledgeScheduledWork<TJob> {
  runId: string;
  jobs: TJob[];
}

export interface V3KnowledgeScheduleRuntimeRepository<TJob> {
  listEnabledScheduleCandidates(): Promise<Array<V3KnowledgeScheduleOccurrenceInput & { id: string }>>;
  claimScheduleRun(
    scheduleId: string,
    scheduledFor: string,
    ownerId: string,
    leaseDurationMs: number,
  ): Promise<V3KnowledgeScheduledWork<TJob> | null>;
  claimRecoverableScheduleRuns(
    ownerId: string,
    leaseDurationMs: number,
    limit: number,
  ): Promise<Array<V3KnowledgeScheduledWork<TJob>>>;
  renewScheduleRunLease(runId: string, ownerId: string, leaseDurationMs: number): Promise<boolean>;
  finishScheduleRun(runId: string, ownerId: string, failureDetail: string | null): Promise<boolean>;
}

export interface V3KnowledgeSchedulerOptions<TJob> {
  repository: V3KnowledgeScheduleRuntimeRepository<TJob>;
  process: (job: TJob, signal: AbortSignal) => Promise<void>;
  pollingIntervalMs?: number;
  ownerId?: string;
  leaseDurationMs?: number;
  heartbeatIntervalMs?: number;
  recoveryBatchSize?: number;
  now?: () => Date;
  onError?: (error: unknown) => void;
}

export class V3KnowledgeScheduleLeaseLostError extends Error {
  constructor(runId: string, options: ErrorOptions = {}) {
    super(`Knowledge schedule run lease was lost: ${runId}`, options);
    this.name = 'V3KnowledgeScheduleLeaseLostError';
  }
}

/**
 * Returns the latest eligible cron occurrence. The persisted unique
 * (scheduled task, scheduled time) key is the final exactly-once guard.
 */
export function dueV3KnowledgeScheduleOccurrence(
  input: V3KnowledgeScheduleOccurrenceInput,
  now = new Date(),
): string | undefined {
  if (!Number.isFinite(now.getTime())) throw new Error('Invalid Knowledge scheduler time');
  const expression = CronExpressionParser.parse(input.schedule, {
    currentDate: new Date(now.getTime() + 1),
    tz: input.timezone,
  });
  const occurrence = expression.prev().toDate();
  const lowerBound = Math.max(
    Date.parse(input.createdAt),
    input.lastRunAt === null ? Number.NEGATIVE_INFINITY : Date.parse(input.lastRunAt),
  );
  if (!Number.isFinite(lowerBound) || occurrence.getTime() <= lowerBound || occurrence > now) {
    return undefined;
  }
  return occurrence.toISOString();
}

export class V3KnowledgeScheduler<TJob> {
  private readonly pollingIntervalMs: number;
  private readonly ownerId: string;
  private readonly leaseDurationMs: number;
  private readonly heartbeatIntervalMs: number;
  private readonly recoveryBatchSize: number;
  private readonly activeExecutions = new Set<AbortController>();
  private timer: NodeJS.Timeout | undefined;
  private running = false;

  constructor(private readonly options: V3KnowledgeSchedulerOptions<TJob>) {
    this.pollingIntervalMs = options.pollingIntervalMs ?? 30_000;
    this.ownerId = options.ownerId?.trim() || randomUUID();
    this.leaseDurationMs = options.leaseDurationMs ?? 90_000;
    this.heartbeatIntervalMs = options.heartbeatIntervalMs ?? 30_000;
    this.recoveryBatchSize = options.recoveryBatchSize ?? 100;
    if (!Number.isInteger(this.pollingIntervalMs) || this.pollingIntervalMs < 1_000) {
      throw new Error('Knowledge scheduler polling interval must be at least one second');
    }
    if (this.ownerId.length > 200) throw new Error('Knowledge scheduler owner identity is invalid');
    if (!Number.isInteger(this.leaseDurationMs) || this.leaseDurationMs < 3_000) {
      throw new Error('Knowledge scheduler lease duration must be at least three seconds');
    }
    if (
      !Number.isInteger(this.heartbeatIntervalMs) ||
      this.heartbeatIntervalMs < 1_000 ||
      this.heartbeatIntervalMs >= this.leaseDurationMs / 2
    ) {
      throw new Error('Knowledge scheduler heartbeat must be shorter than half the lease duration');
    }
    if (
      !Number.isInteger(this.recoveryBatchSize) ||
      this.recoveryBatchSize < 1 ||
      this.recoveryBatchSize > 1_000
    ) {
      throw new Error('Knowledge scheduler recovery batch size is invalid');
    }
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => void this.runOnce(), this.pollingIntervalMs);
    this.timer.unref();
    void this.runOnce();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
    for (const cancellation of this.activeExecutions) {
      cancellation.abort(new Error('Knowledge scheduler stopped'));
    }
  }

  async runOnce(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      for (const work of await this.options.repository.claimRecoverableScheduleRuns(
        this.ownerId,
        this.leaseDurationMs,
        this.recoveryBatchSize,
      )) {
        await this.execute(work);
      }
      const now = this.options.now?.() ?? new Date();
      for (const schedule of await this.options.repository.listEnabledScheduleCandidates()) {
        const scheduledFor = dueV3KnowledgeScheduleOccurrence(schedule, now);
        if (!scheduledFor) continue;
        const work = await this.options.repository.claimScheduleRun(
          schedule.id,
          scheduledFor,
          this.ownerId,
          this.leaseDurationMs,
        );
        if (work) await this.execute(work);
      }
    } catch (error) {
      this.options.onError?.(error);
      if (!this.options.onError) throw error;
    } finally {
      this.running = false;
    }
  }

  private async execute(work: V3KnowledgeScheduledWork<TJob>): Promise<void> {
    const failures: string[] = [];
    const cancellation = new AbortController();
    this.activeExecutions.add(cancellation);
    let leaseLost: V3KnowledgeScheduleLeaseLostError | undefined;
    let renewal: Promise<void> | undefined;
    let heartbeat: NodeJS.Timeout | undefined;
    const loseLease = (cause?: unknown) => {
      if (leaseLost) return;
      leaseLost = new V3KnowledgeScheduleLeaseLostError(work.runId, {
        ...(cause === undefined ? {} : { cause }),
      });
      cancellation.abort(leaseLost);
    };
    const renew = async () => {
      try {
        const owned = await this.options.repository.renewScheduleRunLease(
          work.runId,
          this.ownerId,
          this.leaseDurationMs,
        );
        if (!owned) loseLease();
      } catch (error) {
        loseLease(error);
      }
    };
    try {
      await renew();
      if (leaseLost) throw leaseLost;
      heartbeat = setInterval(() => {
        if (renewal || cancellation.signal.aborted) return;
        renewal = renew().finally(() => {
          renewal = undefined;
        });
      }, this.heartbeatIntervalMs);
      heartbeat.unref();
      for (const job of work.jobs) {
        cancellation.signal.throwIfAborted();
        try {
          await this.options.process(job, cancellation.signal);
        } catch (error) {
          if (cancellation.signal.aborted) throw leaseLost ?? error;
          failures.push(knowledgeFailureDetail(error));
        }
      }
      clearInterval(heartbeat);
      heartbeat = undefined;
      if (renewal) await renewal;
      cancellation.signal.throwIfAborted();
      await renew();
      if (leaseLost) throw leaseLost;
      const finished = await this.options.repository.finishScheduleRun(
        work.runId,
        this.ownerId,
        failures.length ? redactKnowledgeFailureDetail(failures.join('\n'), 2_000) : null,
      );
      if (!finished) throw new V3KnowledgeScheduleLeaseLostError(work.runId);
    } finally {
      if (heartbeat) clearInterval(heartbeat);
      if (renewal) await renewal;
      this.activeExecutions.delete(cancellation);
    }
  }
}
