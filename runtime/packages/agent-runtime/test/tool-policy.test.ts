import { describe, expect, it, vi } from 'vitest';

import { compileToolPolicy } from '../src/tool-policy.ts';
import { createSandboxExecTool } from '../src/sandbox-tool.ts';

function toolHarness(decision: 'allow' | 'ask' | 'deny') {
  const request = vi.fn(async () => 'approved' as const);
  const exec = vi.fn(async (_sandboxId: string, input: { toolCallId: string }) => ({
    toolCallId: input.toolCallId,
    exitCode: 0,
    stdout: 'ok',
    stderr: '',
    timedOut: false,
    truncated: false,
  }));
  const tool = createSandboxExecTool({
    runId: crypto.randomUUID(),
    sandboxId: 'sandbox-id',
    workspacePath: '/workspace',
    sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
    approvals: { request },
    policy: { evaluate: () => decision },
  });
  return { tool, request, exec };
}

describe('tool permission policy', () => {
  it('compiles allow/ask/deny decisions with safe ask fallback', () => {
    const policy = compileToolPolicy({ enabled: true, decisions: { Bash: 'deny', Read: 'allow' } });

    expect(policy.evaluate({ tool: 'Bash', operation: 'execute', target: '/workspace' })).toBe('deny');
    expect(policy.evaluate({ tool: 'Read', operation: 'read', target: '/workspace/a.txt' })).toBe('allow');
    expect(policy.evaluate({ tool: 'Unknown', operation: 'execute', target: '/workspace' })).toBe('ask');
  });

  it('escalates access to a sensitive path even when a tool is allowed', () => {
    const policy = compileToolPolicy({
      enabled: true,
      decisions: { Read: 'allow' },
      sensitivePaths: ['/workspace/secret'],
    });

    expect(policy.evaluate({ tool: 'Read', operation: 'read', target: '/workspace/secret/key.txt' })).toBe(
      'ask',
    );
    expect(policy.evaluate({ tool: 'Read', operation: 'read', target: '/workspace/public.txt' })).toBe(
      'allow',
    );
  });

  it('enforces deny without approval or sandbox execution', async () => {
    const { tool, request, exec } = toolHarness('deny');
    const output = await tool.execute('call-1', { command: 'pwd' }, undefined, undefined, undefined as never);

    expect(output.terminate).toBe(true);
    expect(request).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
  });

  it('runs allow directly and routes ask through approval', async () => {
    const allowed = toolHarness('allow');
    await allowed.tool.execute('call-1', { command: 'pwd' }, undefined, undefined, undefined as never);
    expect(allowed.request).not.toHaveBeenCalled();
    expect(allowed.exec).toHaveBeenCalledOnce();

    const asked = toolHarness('ask');
    await asked.tool.execute('call-2', { command: 'pwd' }, undefined, undefined, undefined as never);
    expect(asked.request).toHaveBeenCalledOnce();
    expect(asked.exec).toHaveBeenCalledOnce();
  });

  it('returns rejected approval to Pi without executing or ending the model turn', async () => {
    const exec = vi.fn();
    const request = vi.fn(async () => 'rejected' as const);
    const tool = createSandboxExecTool({
      runId: crypto.randomUUID(),
      sandboxId: 'sandbox-id',
      workspacePath: '/workspace',
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      approvals: { request },
      policy: { evaluate: () => 'ask' },
    });
    const output = await tool.execute('rejected-call', { command: 'echo fixed' }, undefined);
    expect(output).toMatchObject({ isError: true, details: { approved: false, policyDecision: 'ask' } });
    expect(output.terminate).not.toBe(true);
    expect(exec).not.toHaveBeenCalled();
    expect(request).toHaveBeenCalledOnce();
  });
});
