import type { SandboxClient } from '../../product-contracts/src/index.ts';

/** Own one successful acquisition through every operation and cleanup exit.
 * Adapter release must itself enforce deadlines and verify external termination.
 */
export async function withSandbox<T>(
  client: SandboxClient,
  runId: string,
  enabled: boolean,
  operation: (sandboxId: string | undefined) => Promise<T>,
): Promise<T> {
  if (!enabled) return operation(undefined);
  const sandboxId = await client.create(runId, runId);
  let failed = false;
  let operationError: unknown;
  try {
    return await operation(sandboxId);
  } catch (error) {
    failed = true;
    operationError = error;
    throw error;
  } finally {
    try {
      await client.destroy(sandboxId);
    } catch (releaseError) {
      if (failed) {
        throw new AggregateError([operationError, releaseError], 'Sandbox operation and release failed');
      }
      throw releaseError;
    }
  }
}
