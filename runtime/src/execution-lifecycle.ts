/** Own one reserved execution across the entire operation, including model recovery.
 * Completion and cancellation transports enforce their own independent deadlines.
 */
export async function withExecution<T, R>(options: {
  sandbox: { create(runId: string, workspaceId: string): Promise<string>; destroy(id: string): Promise<void> };
  completion: { complete(): Promise<R>; cancel(): Promise<unknown> };
  runId: string;
  workspaceId: string;
}, operation: (sandboxId: string) => Promise<T>): Promise<{ value: T; receipt: R }> {
  let sandboxId: string | undefined;
  let result: { value: T; receipt: R } | undefined;
  const failures: unknown[] = [];
  try {
    sandboxId = await options.sandbox.create(options.runId, options.workspaceId);
    const value = await operation(sandboxId);
    const receipt = await options.completion.complete();
    result = { value, receipt };
  } catch (error) {
    failures.push(error);
    try { await options.completion.cancel(); }
    catch (cancelError) { failures.push(cancelError); }
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
