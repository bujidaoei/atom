import { describe, expect, it } from 'vitest';

import { createSandboxExecTool } from '../src/sandbox-tool.ts';

describe('sandbox_exec policy', () => {
  it.each([
    { exitCode: 7, timedOut: false, status: 'Command exited with code 7' },
    { exitCode: 124, timedOut: true, status: 'Command timed out after 1 seconds (exit code 124)' },
    { exitCode: 0, timedOut: true, status: 'Command timed out after 1 seconds (exit code 0)' },
  ])('rejects failed commands for Pi while retaining output: $status', async (result) => {
    const tool = createSandboxExecTool({
      runId: crypto.randomUUID(),
      sandboxId: 'sandbox-id',
      workspacePath: '/workspace',
      sandbox: {
        async create() {
          return 'sandbox-id';
        },
        async exec(_id, request) {
          return {
            ...result,
            toolCallId: request.toolCallId,
            stdout: 'partial output',
            stderr: 'diagnostic',
            truncated: false,
          };
        },
        async destroy() {},
      },
      approvals: {
        async request() {
          return 'approved';
        },
      },
    });
    await expect(tool.execute('failure', { command: 'exit 7', timeoutMs: 1_000 }, undefined)).rejects.toThrow(
      `partial output\ndiagnostic\n\n${result.status}`,
    );
  });

  it('registers the product-owned Docker command tool', () => {
    const tool = createSandboxExecTool({
      runId: crypto.randomUUID(),
      sandboxId: 'sandbox-id',
      workspacePath: '/workspace',
      sandbox: {
        async create() {
          return 'sandbox-id';
        },
        async exec(_sandboxId, request) {
          return {
            toolCallId: request.toolCallId,
            exitCode: 0,
            stdout: 'ok',
            stderr: '',
            timedOut: false,
            truncated: false,
          };
        },
        async destroy() {},
      },
      approvals: {
        async request() {
          return 'approved';
        },
      },
    });

    expect(tool.name).toBe('sandbox_exec');
    expect(tool.executionMode).toBe('sequential');
    expect(tool.promptGuidelines?.join(' ')).toContain('Docker Socket');
  });

  it('passes the Pi cancellation signal into the Docker client', async () => {
    let receivedSignal: AbortSignal | undefined;
    const tool = createSandboxExecTool({
      runId: crypto.randomUUID(),
      sandboxId: 'sandbox-id',
      workspacePath: '/workspace',
      sandbox: {
        async create() {
          return 'sandbox-id';
        },
        async exec(_sandboxId, request, signal) {
          receivedSignal = signal;
          return {
            toolCallId: request.toolCallId,
            exitCode: 0,
            stdout: 'ok',
            stderr: '',
            timedOut: false,
            truncated: false,
          };
        },
        async destroy() {},
      },
      approvals: {
        async request() {
          return 'approved';
        },
      },
    });
    const cancellation = new AbortController();

    const result = await tool.execute(
      'call-1',
      { command: 'pwd' },
      cancellation.signal,
      undefined,
      undefined as never,
    );
    expect(result.content).toEqual([{ type: 'text', text: 'ok' }]);

    expect(receivedSignal).toBe(cancellation.signal);
  });
});
