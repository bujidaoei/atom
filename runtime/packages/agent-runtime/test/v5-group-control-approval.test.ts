import { expect, it, vi } from 'vitest';
import type { ApprovalAdapter } from '../../product-contracts/src/index.ts';
import { createV3GroupMessagingSandbox } from '../src/v3-group-messaging.ts';
import { compileV3ToolPolicy } from '../src/v3-policy.ts';
import { createSandboxExecTool } from '../src/sandbox-tool.ts';

it.each(['approved', 'rejected'] as const)(
  'waits for real Bash approval before pure Group history (%s)',
  async (decision) => {
    const onList = vi.fn(async () => []);
    const exec = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      conversationId: 'conversation',
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      onDelivery: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
      onList,
    });
    let resolveApproval!: (value: 'approved' | 'rejected') => void;
    const request = vi.fn<ApprovalAdapter['request']>(
      () =>
        new Promise<'approved' | 'rejected'>((resolve) => {
          resolveApproval = resolve;
        }),
    );
    const evidence = vi.fn();
    const tool = createSandboxExecTool({
      runId: 'run',
      sandboxId: 'sandbox',
      workspacePath: process.cwd(),
      sandbox,
      approvals: { request },
      onPolicyDecision: evidence,
      policy: compileV3ToolPolicy(process.cwd(), [
        { id: 'waker-bash', version: 7, decisions: { Bash: 'ask' } },
      ]),
    });
    const command = 'qoderwake messages list conversation --after-seq 257 --limit 1 --json';
    const running = tool.execute('pure-list', { command }, undefined);
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce());
    expect(onList).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
    expect(request.mock.calls[0]![0]).toMatchObject({
      command,
      toolCallId: 'pure-list',
      policyVersions: [{ id: 'waker-bash', version: 7 }],
      requestHash: expect.stringMatching(/^[a-f0-9]{64}$/),
    });
    resolveApproval(decision);
    const result = await running;
    expect(onList).toHaveBeenCalledTimes(decision === 'approved' ? 1 : 0);
    if (decision === 'rejected')
      expect(result).toMatchObject({ isError: true, details: { approved: false, policyDecision: 'ask' } });
    expect(evidence).toHaveBeenCalledWith(
      expect.objectContaining({ decision: 'ask', policyVersions: [{ id: 'waker-bash', version: 7 }] }),
    );
    expect(exec).not.toHaveBeenCalled();
  },
);
