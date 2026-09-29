import { describe, expect, it, vi } from 'vitest';
import { createV3GroupMessagingSandbox } from '../src/v3-group-messaging.ts';
import { createSandboxExecTool } from '../src/sandbox-tool.ts';
import { compileV3ToolPolicy } from '../src/v3-policy.ts';

const group = {
  id: 'group',
  workspaceId: 'workspace',
  surfaceKind: 'group' as const,
  title: 'Group',
  defaultConversationId: 'conversation',
  revision: 7,
  status: 'active' as const,
  createdAt: '2026-09-20T00:00:00.000Z',
  updatedAt: '2026-09-20T00:00:00.000Z',
};

function fixture() {
  const exec = vi.fn();
  const onSopBindings = vi.fn(async () => ({ group, systemSkills: [] }));
  const sandbox = createV3GroupMessagingSandbox({
    sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
    conversationId: 'conversation',
    onSopBindings,
    onDelivery: vi.fn(),
    onList: vi.fn(),
    onGoalGet: vi.fn(),
    onGoalMutate: vi.fn(),
  });
  const run = (command: string, signal?: AbortSignal) =>
    sandbox.exec('sandbox', { command, toolCallId: 'binding', timeoutMs: 1000 }, signal);
  return { sandbox, run, exec, onSopBindings };
}

describe('observed Group SOP commands', () => {
  it('reads revision then replaces the complete ordered selection without a shell', async () => {
    const { run, onSopBindings, exec } = fixture();
    expect(
      (await run('qoderwake group sop set group --sop profile-b@1.0.0 --json --sop profile-a@2.0.0'))
        .exitCode,
    ).toBe(0);
    expect(onSopBindings.mock.calls).toEqual([
      ['group'],
      [
        'group',
        {
          expectedVersion: 7,
          selections: [
            { profileId: 'profile-b', version: '1.0.0' },
            { profileId: 'profile-a', version: '2.0.0' },
          ],
        },
      ],
    ]);
    expect(exec).not.toHaveBeenCalled();
  });
  it.each([
    'set group',
    'set group --sop profile',
    'set group --sop profile@1.0.0 --sop profile@2.0.0',
    'list group --sop profile@1.0.0',
    'list group --json --json',
    'set group --sop profile@1.0.0 --unknown',
    'set group --sop profile@1.0.0; whoami',
    'set group --sop profile@$(whoami)',
    'list',
  ])('rejects malformed or unsafe arguments before lookup: %s', async (suffix) => {
    const { run, onSopBindings, exec } = fixture();
    expect((await run('qoderwake group sop ' + suffix)).exitCode).not.toBe(0);
    expect(onSopBindings).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
  });
  it('does not retry a rejected version or write after cancellation', async () => {
    const { run, onSopBindings } = fixture();
    onSopBindings.mockRejectedValueOnce(new Error('claim expired'));
    expect((await run('qoderwake group sop set group --sop profile@1.0.0')).stderr).toBe('claim expired');
    expect(onSopBindings).toHaveBeenCalledTimes(1);
    const abort = new AbortController();
    onSopBindings.mockImplementationOnce(async () => {
      abort.abort();
      return { group, systemSkills: [] };
    });
    await expect(run('qoderwake group sop set group --sop profile@1.0.0', abort.signal)).rejects.toThrow();
    expect(onSopBindings).toHaveBeenCalledTimes(2);
  });
  it('enforces effective Bash denial for both list and set', async () => {
    const { sandbox, onSopBindings } = fixture();
    const tool = createSandboxExecTool({
      runId: 'run',
      sandboxId: 'sandbox',
      workspacePath: process.cwd(),
      sandbox,
      approvals: { request: vi.fn() },
      policy: compileV3ToolPolicy(process.cwd(), [{ id: 'deny', version: 1, decisions: { Bash: 'deny' } }]),
    });
    const list = await tool.execute('list', { command: 'qoderwake group sop list group --json' }, undefined);
    expect(list.content).toEqual([{ type: 'text', text: '权限策略禁止执行该沙箱命令。' }]);
    const set = await tool.execute(
      'set',
      { command: 'qoderwake group sop set group --sop profile@1.0.0' },
      undefined,
    );
    expect(set.content).toEqual([{ type: 'text', text: '权限策略禁止执行该沙箱命令。' }]);
    expect(onSopBindings).not.toHaveBeenCalled();
  });
});
