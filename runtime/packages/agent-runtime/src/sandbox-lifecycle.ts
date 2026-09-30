import type { SandboxClient } from '../../product-contracts/src/index.ts';

/** Supplied only by trusted outer execution ownership, never model input. */
export interface ExternalSandboxScope {
  readonly runId: string;
  readonly workspaceId: string;
  readonly sandboxId: string;
}

export function validateSandboxScope(scope: ExternalSandboxScope | undefined, runId: string): void {
  if (scope && (scope.runId !== runId || typeof scope.workspaceId !== 'string' || !scope.workspaceId
      || typeof scope.sandboxId !== 'string' || !scope.sandboxId)) throw new Error('Sandbox execution scope mismatch');
}

/** Own one successful acquisition through every operation and cleanup exit.
 * Adapter release must itself enforce deadlines and verify external termination.
 */
export async function withSandbox<T>(
  client: SandboxClient,
  runId: string,
  enabled: boolean,
  operation: (sandboxId: string | undefined) => Promise<T>,
  scope?: ExternalSandboxScope,
): Promise<T> {
  validateSandboxScope(scope, runId);
  if (!enabled) return operation(undefined);
  if (scope) return operation(scope.sandboxId);
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
