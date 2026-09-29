import { describe, expect, it, vi } from 'vitest';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createV3GroupMessagingSandbox, parseV3GroupMessageSendCommand } from '../src/v3-group-messaging.ts';
import { readV3SharedWorkspaceFile } from '../src/v3-group-mission-runner.ts';

describe('Group generated file send', () => {
  it('routes the observed file option to the host and includes the committed attachment in JSON', async () => {
    const filePath = join(tmpdir(), 'generated file.txt');
    const command = `qoderwake messages send conversation --text "file result" --file "${filePath}" --not-mention --yes --json`;
    expect(parseV3GroupMessageSendCommand(command, { conversationId: 'conversation' })).toMatchObject({
      filePath,
      text: 'file result',
    });
    const exec = vi.fn();
    const onDelivery = vi.fn(async () => ({
      message: {
        id: 'message',
        sequence: 2,
        type: 'assistant.message',
        occurredAt: '2026-09-21T00:00:00Z',
        payload: {
          content: 'file result',
          actorParticipantId: 'sender',
          mentionedParticipantIds: [],
          attachments: [
            {
              id: 'file',
              creatorParticipantId: 'original-uploader',
              fileName: 'generated file.txt',
              mediaType: 'text/plain',
              sizeBytes: 4,
              sha256: 'a'.repeat(64),
              createdAt: '2026-08-01T01:02:03.123456Z',
              associatedAt: '2026-09-21T00:00:00.010Z',
            },
          ],
        },
      },
      replayed: false,
    }));
    const onList = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      conversationId: 'conversation',
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      onDelivery,
      onList,
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', { command, toolCallId: 'send-file', timeoutMs: 1000 });
    expect(result.exitCode).toBe(0);
    expect(onDelivery).toHaveBeenCalledWith(
      { text: 'file result', mentionTarget: null, filePath },
      'send-file',
    );
    expect(JSON.parse(result.stdout).message.attachments).toEqual([
      {
        attachment: {
          id: 'file',
          conversationId: 'conversation',
          creatorParticipantId: 'original-uploader',
          kind: 'artifact',
          filename: 'generated file.txt',
          mimeType: 'text/plain',
          sizeBytes: 4,
          sha256: 'a'.repeat(64),
          createdAt: '2026-08-01T01:02:03.123456Z',
          state: 'attached',
        },
        ordinal: 0,
        createdAt: '2026-09-21T00:00:00.010Z',
        role: 'output',
      },
    ]);
    expect(exec).not.toHaveBeenCalled();
    const committed = await onDelivery.mock.results[0]!.value;
    onList.mockResolvedValue([committed.message]);
    const history = await sandbox.exec('sandbox', {
      command: 'qoderwake messages list conversation --after-seq 1 --limit 1 --json',
      toolCallId: 'list-file',
      timeoutMs: 1000,
    });
    expect(history.exitCode).toBe(0);
    expect(JSON.parse(history.stdout)).toEqual([JSON.parse(result.stdout).message]);
    expect(onDelivery).toHaveBeenCalledTimes(1);
  });

  it('returns a failure without a shell fallback when host file upload fails', async () => {
    const exec = vi.fn();
    const onDelivery = vi.fn().mockRejectedValue(new Error('Group file upload is unavailable'));
    const sandbox = createV3GroupMessagingSandbox({
      conversationId: 'conversation',
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', {
      command:
        'qoderwake messages send conversation --text result --file result.txt --not-mention --yes --json',
      toolCallId: 'failed-file-send',
      timeoutMs: 1000,
    });
    expect(result.exitCode).not.toBe(0);
    expect(result.stderr).toContain('Group file upload is unavailable');
    expect(result.stdout).toBe('');
    expect(onDelivery).toHaveBeenCalledTimes(1);
    expect(exec).not.toHaveBeenCalled();
  });
  it('bounds generated file reads before returning bytes and observes cancellation', async () => {
    const root = await mkdtemp(join(tmpdir(), 'group-send-read-'));
    try {
      await writeFile(join(root, 'result.txt'), '12345');
      await expect(readV3SharedWorkspaceFile(root, 'result.txt', { maxBytes: 4 })).rejects.toThrow('limit');
      await expect(readV3SharedWorkspaceFile(root, 'result.txt', { maxBytes: 5 })).resolves.toEqual(
        Buffer.from('12345'),
      );
      const controller = new AbortController();
      controller.abort();
      await expect(
        readV3SharedWorkspaceFile(root, 'result.txt', { maxBytes: 5, signal: controller.signal }),
      ).rejects.toThrow();
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
