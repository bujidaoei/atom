import { describe, expect, it, vi } from 'vitest';
import { createV3GroupMessagingSandbox } from '../src/v3-group-messaging.ts';
import { createSandboxExecTool } from '../src/sandbox-tool.ts';
import { compileV3ToolPolicy } from '../src/v3-policy.ts';
import { V3GroupTodoNotFoundError } from '../../product-contracts/src/v3-group-todo.ts';

function fixture() {
  const onTodos = vi.fn(async () => []);
  const exec = vi.fn();
  const sandbox = createV3GroupMessagingSandbox({
    sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
    conversationId: 'current-conversation',
    onTodos,
    onDelivery: vi.fn(),
    onList: vi.fn(),
    onGoalGet: vi.fn(),
    onGoalMutate: vi.fn(),
  });
  return {
    onTodos,
    exec,
    sandbox,
    run: (command: string, signal?: AbortSignal) =>
      sandbox.exec('current-sandbox', { command, toolCallId: 'todo-call', timeoutMs: 1000 }, signal),
  };
}

describe('observed Group todo commands', () => {
  it('preserves the official missing-item error and exit status', async () => {
    const { run, onTodos, exec } = fixture();
    onTodos.mockRejectedValueOnce(new V3GroupTodoNotFoundError());
    expect(
      await run('qoderwake todo update 00000000-0000-4000-8000-000000000000 --status completed --json'),
    ).toMatchObject({ exitCode: 1, stderr: '[qoderwake] todo not found', stdout: '' });
    expect(onTodos).toHaveBeenCalledTimes(1);
    expect(exec).not.toHaveBeenCalled();
  });
  it.each([
    ['list --json', { action: 'list', all: false }],
    ['list --all --json', { action: 'list', all: true }],
    ['add --content "two lines\nquoted text" --json', { action: 'add', content: 'two lines\nquoted text' }],
    [
      'update actual-id --status in_progress --json',
      { action: 'update', todoId: 'actual-id', status: 'in_progress' },
    ],
    [
      'update actual-id --content "new text" --json',
      { action: 'update', todoId: 'actual-id', content: 'new text' },
    ],
    [
      'update actual-id --status completed --json',
      { action: 'update', todoId: 'actual-id', status: 'completed' },
    ],
    [
      'update actual-id --status cancelled --json',
      { action: 'update', todoId: 'actual-id', status: 'cancelled' },
    ],
  ])('routes %s through the host rather than a shell', async (suffix, command) => {
    const { run, onTodos, exec } = fixture();
    expect(await run('qoderwake todo ' + suffix)).toMatchObject({ exitCode: 0, stdout: '[]' });
    expect(onTodos).toHaveBeenCalledExactlyOnceWith(command);
    expect(exec).not.toHaveBeenCalled();
  });
  it.each([
    'list --all --all --json',
    'list --participant-id foreign --json',
    'add --content first --content second --json',
    'add --status completed --content text --json',
    'update actual-id --status unknown --json',
    'update actual-id --json',
    'update --status completed --json',
    'list --json; whoami',
    'add --content $(whoami) --json',
    'list --json --json',
  ])('rejects %s before any callback', async (suffix) => {
    const { run, onTodos, exec } = fixture();
    expect((await run('qoderwake todo ' + suffix)).exitCode).not.toBe(0);
    expect(onTodos).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
  });
  it('does not retry uncertain mutations or invoke a cancelled request', async () => {
    const { run, onTodos } = fixture();
    onTodos.mockRejectedValueOnce(new Error('claim expired'));
    expect((await run('qoderwake todo add --content text --json')).stderr).toBe('claim expired');
    const abort = new AbortController();
    abort.abort();
    await expect(run('qoderwake todo add --content text --json', abort.signal)).rejects.toThrow();
    expect(onTodos).toHaveBeenCalledTimes(1);
  });
  it.each(['allow', 'deny'] as const)(
    'honors underlying Bash policy %s for own-todo controls',
    async (decision) => {
      const { sandbox, onTodos, exec } = fixture();
      const approvals = { request: vi.fn() };
      const tool = createSandboxExecTool({
        runId: 'run',
        sandboxId: 'current-sandbox',
        workspacePath: process.cwd(),
        sandbox,
        approvals,
        policy: compileV3ToolPolicy(process.cwd(), [
          { id: 'todo-policy', version: 1, decisions: { Bash: decision } },
        ]),
      });
      await tool.execute('todo-call', { command: 'qoderwake todo list --json' }, undefined);
      expect(onTodos).toHaveBeenCalledTimes(decision === 'allow' ? 1 : 0);
      expect(approvals.request).not.toHaveBeenCalled();
      if (decision === 'deny') {
        for (const command of [
          'echo unexpected',
          'qoderwake todo list --participant-id foreign --json',
          'qoderwake todo list --json; whoami',
        ])
          await tool.execute('invalid', { command }, undefined);
        expect(onTodos).not.toHaveBeenCalled();
        expect(exec).not.toHaveBeenCalled();
      }
    },
  );
});
