/** Own one reserved execution across the entire operation, including model recovery.
 * Completion and cancellation transports enforce their own independent deadlines.
 */
export class ExecutionInterrupted<R> extends Error {
  constructor(readonly outcome: 'cancelled' | 'timed_out', readonly receipt: R | null, options?: ErrorOptions) {
    super('Execution interrupted', options);
    this.name = 'ExecutionInterrupted';
  }
}

export async function withExecution<T, R>(options: {
  sandbox: { create(runId: string, workspaceId: string): Promise<string>; destroy(id: string): Promise<void> };
  completion: { complete(): Promise<R>; cancel(): Promise<unknown>;
    partial?(outcome: 'cancelled' | 'timed_out'): Promise<{ outcome: 'cancelled' | 'timed_out'; receipt: R | null }> };
  signal?: AbortSignal;
  runId: string;
  workspaceId: string;
}, operation: (sandboxId: string) => Promise<T>): Promise<{ value: T; receipt: R }> {
  let sandboxId: string | undefined;
  let operationDone = false;
  let result: { value: T; receipt: R } | undefined;
  const failures: unknown[] = [];
  try {
    sandboxId = await options.sandbox.create(options.runId, options.workspaceId);
    const value = await operation(sandboxId);
    operationDone = true;
    const receipt = await options.completion.complete();
    result = { value, receipt };
  } catch (error) {
    let interrupted = false;
    if (sandboxId !== undefined && !operationDone && options.signal?.aborted && options.completion.partial) {
      const outcome = options.signal.reason?.name === 'TimeoutError' ? 'timed_out' : 'cancelled';
      try {
        const partial = await options.completion.partial(outcome);
        if (partial.outcome !== outcome) throw new Error('Partial outcome mismatch');
        failures.push(new ExecutionInterrupted(outcome, partial.receipt, { cause: error }));
        interrupted = true;
      } catch (partialError) { failures.push(error, partialError); }
    } else failures.push(error);
    if (!interrupted) {
      try { await options.completion.cancel(); }
      catch (cancelError) { failures.push(cancelError); }
    }
  } finally {
    if (sandboxId !== undefined) {
      try { await options.sandbox.destroy(sandboxId); }
      catch (releaseError) { failures.push(releaseError); }
    }
  }
  if (failures.length === 1) throw failures[0];
  if (failures.length > 1) throw new AggregateError(failures, 'Execution and cleanup failed');
  return result!;
}
