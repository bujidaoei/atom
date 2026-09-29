import { describe, expect, it, vi } from 'vitest';
import { createV3GroupMessagingSandbox, parseV3GroupGoalCommand } from '../src/v3-group-messaging.ts';

describe('current-conversation Goal commands', () => {
  it('parses the observed read, active update, pause and result-reference forms', () => {
    expect(parseV3GroupGoalCommand('qoderwake goal get conversation', 'conversation')).toEqual({
      kind: 'get',
    });
    expect(
      parseV3GroupGoalCommand(
        'qoderwake goal mutate conversation --action update --goal-id goal --generation 3 --revision 5 --content "目标说明" --turn-limit 10 --json',
        'conversation',
      ),
    ).toEqual({
      kind: 'mutate',
      input: {
        action: 'update',
        goalId: 'goal',
        generation: 3,
        revision: 5,
        content: '目标说明',
        turnLimit: 10,
      },
    });
    expect(
      parseV3GroupGoalCommand(
        'qoderwake goal mutate conversation --action complete --goal-id goal --generation 3 --revision 6 --result-message result --json',
        'conversation',
      ),
    ).toMatchObject({ input: { action: 'complete', resultMessageId: 'result' } });
    expect(
      parseV3GroupGoalCommand(
        'qoderwake goal mutate conversation --action pause --goal-id goal --generation 3 --revision 6 --reason awaiting_user',
        'conversation',
      ),
    ).toMatchObject({ input: { action: 'pause', reason: 'awaiting_user' } });
  });
  it.each([
    'qoderwake goal get other',
    'qoderwake goal get conversation; whoami',
    'qoderwake goal get conversation --action pause',
    'qoderwake goal mutate conversation --action create --content test --turn-limit 0',
    'qoderwake goal mutate conversation --action create --content test --turn-limit 1 --turn-limit 2',
    'qoderwake goal mutate conversation --action pause --goal-id goal --generation 1 --revision 1 --reason invented',
    'qoderwake goal mutate conversation --action complete --goal-id goal --generation 1 --revision 1',
    'qoderwake goal mutate conversation --action create --content test --turn-limit 1 --result-message forged',
  ])('rejects unsupported or out-of-scope commands: %s', (command) => {
    expect(() => parseV3GroupGoalCommand(command, 'conversation')).toThrow();
  });
  it('never delegates malformed Goal commands to a shell or reports a rejected write as success', async () => {
    const exec = vi.fn();
    const get = vi.fn(async () => null);
    const mutate = vi.fn(async () => {
      throw new Error('Goal changed; read the latest Goal before updating it');
    });
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery: vi.fn(),
      onList: vi.fn(),
      onGoalGet: get,
      onGoalMutate: mutate,
    });
    const request = (command: string) => ({ toolCallId: 'goal-tool', command, timeoutMs: 1000 });
    expect(await sandbox.exec('sandbox', request('qoderwake goal get conversation --json'))).toMatchObject({
      exitCode: 1,
      stderr: "error: unknown option '--json'",
    });
    expect(get).not.toHaveBeenCalled();
    expect(await sandbox.exec('sandbox', request('qoderwake goal get other'))).toMatchObject({ exitCode: 1 });
    expect(get).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
    expect(
      await sandbox.exec(
        'sandbox',
        request(
          'qoderwake goal mutate conversation --action pause --goal-id goal --generation 1 --revision 1 --reason awaiting_user',
        ),
      ),
    ).toMatchObject({ exitCode: 1, stderr: expect.stringContaining('Goal changed') });
    const stopped = new AbortController();
    stopped.abort(new Error('Stopped'));
    await expect(
      sandbox.exec('sandbox', request('qoderwake goal get conversation'), stopped.signal),
    ).rejects.toThrow('Stopped');
    expect(get).not.toHaveBeenCalled();
    expect(await sandbox.exec('sandbox', request('qoderwake goal get conversation'))).toMatchObject({
      exitCode: 0,
      stdout: expect.stringContaining('"schema_version":1'),
    });
    expect(get).toHaveBeenCalledOnce();
  });
});
