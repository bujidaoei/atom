import { describe, expect, it, vi } from 'vitest';
import { createV3GroupMessagingSandbox } from '../src/v3-group-messaging.ts';

describe('canonical Group CLI history', () => {
  it('projects authorized human and Waker messages without internal event fields', async () => {
    const messages = [
      {
        id: 'human-message',
        sequence: 221,
        type: 'user.message',
        occurredAt: '2026-09-20T05:19:49Z',
        payload: {
          actorId: 'internal-user',
          actorParticipantId: 'human-participant',
          content: 'Request',
          mentionedParticipantIds: ['leader-participant'],
          publicationHash: 'internal-hash',
        },
      },
      {
        id: 'private-message',
        sequence: 223,
        type: 'assistant.message',
        occurredAt: '2026-09-20T05:20:49Z',
        payload: {
          actorParticipantId: 'leader-participant',
          content: 'Private reply',
          mentionedParticipantIds: [],
          privateParticipantIds: ['reader-participant'],
          toolCallId: 'internal-call',
        },
      },
    ];
    const onList = vi.fn(async () => messages);
    const sandbox = createV3GroupMessagingSandbox({
      conversationId: 'conversation',
      sandbox: { create: vi.fn(), exec: vi.fn(), destroy: vi.fn() },
      onList,
      onDelivery: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', {
      toolCallId: 'list',
      timeoutMs: 1000,
      command: 'qoderwake messages list conversation --after-seq 220 --limit 5 --json',
    });
    expect(result.exitCode).toBe(0);
    expect(onList).toHaveBeenCalledWith(220, 5);
    expect(JSON.parse(result.stdout)).toEqual([
      {
        id: 'human-message',
        conversationId: 'conversation',
        seq: 221,
        senderParticipantId: 'human-participant',
        body: { type: 'text', text: 'Request' },
        audience: [{ participantId: 'leader-participant' }],
        intent: 'request_action',
        deliveryPolicy: 'wake',
        idempotencyKey: 'remote:human-message',
        createdAt: messages[0]!.occurredAt,
      },
      {
        id: 'private-message',
        conversationId: 'conversation',
        seq: 223,
        senderParticipantId: 'leader-participant',
        body: { type: 'text', text: 'Private reply' },
        audience: [],
        privateTo: [{ participantId: 'reader-participant' }],
        intent: 'chat',
        deliveryPolicy: 'store_only',
        idempotencyKey: 'remote:private-message',
        createdAt: messages[1]!.occurredAt,
      },
    ]);
  });
});
