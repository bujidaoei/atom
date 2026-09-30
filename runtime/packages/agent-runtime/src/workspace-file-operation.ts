import { createHash } from 'node:crypto';
import type { WorkspaceFileOperation } from '../../product-contracts/src/index.ts';
import { guardSandboxOperation, type SandboxExecToolOptions, type GuardedSandboxCommand } from './sandbox-tool.ts';

export async function runWorkspaceFileOperation(
  options: SandboxExecToolOptions, toolCallId: string, operation: WorkspaceFileOperation, signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  if (!options.sandbox.fileOperation) throw new Error('Structured workspace file capability is unavailable.');
  const response = await options.sandbox.fileOperation(options.sandboxId, { toolCallId, operation }, signal);
  signal?.throwIfAborted();
  if (!response || response.toolCallId !== toolCallId || !response.data || typeof response.data !== 'object') {
    throw new Error('Invalid workspace file response.');
  }
  const data = response.data;
  if (operation.op === 'read_bytes') {
    if (!('base64' in data) || typeof data.base64 !== 'string' || data.base64.length > 11184812 || typeof data.sha256 !== 'string') {
      throw new Error('Invalid workspace read response.');
    }
    const bytes = Buffer.from(data.base64, 'base64');
    if (bytes.length > 8 * 1024 * 1024 || bytes.toString('base64') !== data.base64 || createHash('sha256').update(bytes).digest('hex') !== data.sha256) {
      throw new Error('Workspace read integrity check failed.');
    }
  } else if (operation.op === 'write') {
    if (!('bytes_written' in data) || data.bytes_written !== Buffer.byteLength(operation.content)
        || data.sha256 !== createHash('sha256').update(operation.content).digest('hex')) {
      throw new Error('Workspace write confirmation is invalid.');
    }
  } else if (!('text' in data) || typeof data.text !== 'string' || Buffer.byteLength(data.text) > 256 * 1024) {
    throw new Error('Invalid workspace text response.');
  }
  return data;
}

export async function executeGuardedWorkspaceFile(
  options: SandboxExecToolOptions, toolCallId: string, input: GuardedSandboxCommand,
  operation: WorkspaceFileOperation, signal?: AbortSignal,
) {
  const blocked = await guardSandboxOperation(options, toolCallId, input, signal);
  if (blocked) return blocked;
  const data = await runWorkspaceFileOperation(options, toolCallId, operation, signal);
  if (!('text' in data)) throw new Error('Workspace text operation returned non-text data.');
  return { content: [{ type: 'text' as const, text: data.text }], details: { toolCallId, operation: operation.op } };
}
