import { describe, expect, it, vi } from 'vitest';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  createV3GroupMessagingSandbox,
  parseV3GroupMessageSendCommand,
  isDirectV3GroupControlCommand,
} from '../src/v3-group-messaging.ts';

const members = [
  { id: '10000000-0000-4000-8000-000000000001', name: 'qd' },
  { id: '10000000-0000-4000-8000-000000000002', name: 'hd' },
  { id: '10000000-0000-4000-8000-000000000003', name: 'fe' },
];

describe('V3 current Group message control plane', () => {
  it('explains rejected attachment syntax without delivering or executing it', async () => {
    const onDelivery = vi.fn();
    const exec = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', {
      toolCallId: 'wrong-attachment',
      timeoutMs: 1000,
      command: 'qoderwake messages send conversation --text file --attachment shared/result.txt',
    });
    expect(result.exitCode).not.toBe(0);
    expect(result.stderr).toContain('--file <path>');
    expect(result.stderr).toContain('qoderwake messages send --help');
    expect(onDelivery).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
    expect(
      parseV3GroupMessageSendCommand(
        'qoderwake messages send conversation --text file --file shared/result.txt',
        { conversationId: 'conversation' },
      ),
    ).toEqual({ text: 'file', mentionTarget: null, filePath: 'shared/result.txt' });
  });
  it.each([
    ['qoderwake messages send --help', true],
    ["'qoderwake' messages send --help", true],
    ["qoderwake messages send conversation --text 'literal 2>&1 ; $HOME'", true],
    ['qoderwake messages send --help 2>&1', false],
    ['qoderwake messages send --help && echo done', false],
    ['qoderwake messages send conversation --text "$HOME"', false],
    ['echo qoderwake', false],
  ])('routes shell syntax consistently for %s', (command, direct) => {
    expect(isDirectV3GroupControlCommand(command)).toBe(direct);
  });
  it.each([
    "qoderwake 'messages' 'send' conversation --text 'QUOTED --help LITERAL' --json",
    "'qoderwake' messages send conversation --text 'QUOTED --help LITERAL' --json",
    "qoderwake messages send conversation --text 'QUOTED --help LITERAL' --json",
  ])('dispatches command words and data by argument boundaries: %s', async (command) => {
    const onDelivery = vi.fn(async (delivery: { text: string }) => ({
      message: {
        id: 'sent',
        sequence: 1,
        type: 'assistant.message',
        occurredAt: '2026-09-23T00:00:00Z',
        payload: { content: delivery.text, actorParticipantId: 'sender', mentionedParticipantIds: [] },
      },
      replayed: false,
    }));
    const exec = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', { command, toolCallId: 'quoted', timeoutMs: 1000 });
    expect(result.exitCode).toBe(0);
    expect(onDelivery).toHaveBeenCalledExactlyOnceWith(
      { text: 'QUOTED --help LITERAL', mentionTarget: null },
      'quoted',
    );
    expect(JSON.parse(result.stdout).message.body.text).toBe('QUOTED --help LITERAL');
    expect(exec).not.toHaveBeenCalled();
  });

  it('does not silently discard empty positional arguments', () => {
    expect(() =>
      parseV3GroupMessageSendCommand("qoderwake '' messages send conversation --text OK", {
        conversationId: 'conversation',
      }),
    ).toThrow();
  });
  it.each([false, true])(
    'passes attachment identities and explicit destination without shell execution: %s',
    async (explicit) => {
      const outputPath = join(tmpdir(), 'attachment download.txt');
      const receipt = { path: outputPath, sizeBytes: 20, messageId: 'message', attachmentId: 'attachment' };
      const onAttachmentDownload = vi.fn(async () => receipt);
      const exec = vi.fn();
      const sandbox = createV3GroupMessagingSandbox({
        sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
        conversationId: 'conversation',
        onDelivery: vi.fn(),
        onList: vi.fn(),
        onGoalGet: vi.fn(),
        onGoalMutate: vi.fn(),
        onAttachmentDownload,
      });
      const result = await sandbox.exec('sandbox', {
        toolCallId: 'download',
        timeoutMs: 1000,
        command: `qoderwake messages attachment download conversation message attachment ${explicit ? `--out "${outputPath}"` : ''} --json`,
      });
      expect(result.exitCode).toBe(0);
      expect(JSON.parse(result.stdout)).toEqual(receipt);
      expect(onAttachmentDownload).toHaveBeenCalledWith(
        { messageId: 'message', attachmentId: 'attachment', ...(explicit ? { outputPath } : {}) },
        undefined,
      );
      expect(exec).not.toHaveBeenCalled();
    },
  );
  it('answers messages send --help with the official usage, including --file', async () => {
    const onDelivery = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec: vi.fn(), destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', {
      toolCallId: 'help',
      timeoutMs: 1000,
      command: 'qoderwake messages send --help',
    });
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain('Usage: qoderwake messages send [options] <convId>');
    expect(result.stdout).toContain('--file <path>            attach a local file via the upload flow');
    expect(onDelivery).not.toHaveBeenCalled();
  });
  it.each([
    'other message attachment --json',
    'conversation message attachment --out relative.txt --json',
    'conversation message attachment --json --json',
    'conversation message attachment --json; echo extra',
    'conversation message --json',
  ])('rejects invalid attachment commands before download: %s', async (args) => {
    const onAttachmentDownload = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec: vi.fn(), destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery: vi.fn(),
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
      onAttachmentDownload,
    });
    expect(
      (
        await sandbox.exec('sandbox', {
          toolCallId: 'invalid-download',
          timeoutMs: 1000,
          command: `qoderwake messages attachment download ${args}`,
        })
      ).exitCode,
    ).not.toBe(0);
    expect(onAttachmentDownload).not.toHaveBeenCalled();
  });
  it.each([
    String.raw`$'text\nnext'; echo extra`,
    String.raw`$(echo substituted)`,
    String.raw`$'unterminated`,
    String.raw`$'nul\0byte'`,
  ])('rejects invalid quoted data without publishing or executing: %s', async (argument) => {
    const exec = vi.fn();
    const onDelivery = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', {
      command: `qoderwake messages send conversation --text ${argument} --not-mention --yes`,
      toolCallId: 'invalid-quoted',
      timeoutMs: 1000,
    });
    expect(result.exitCode).not.toBe(0);
    expect(onDelivery).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
  });
  it.each([
    [String.raw`"TEXT-DOUBLE-A\nTEXT-DOUBLE-B"`, String.raw`TEXT-DOUBLE-A\nTEXT-DOUBLE-B`],
    [String.raw`'TEXT-LITERAL-A\nTEXT-LITERAL-B'`, String.raw`TEXT-LITERAL-A\nTEXT-LITERAL-B`],
    [String.raw`$'TEXT-NEWLINE-A\nTEXT-NEWLINE-B'`, 'TEXT-NEWLINE-A\nTEXT-NEWLINE-B'],
  ])('preserves observed quoted text %s at the host callback', async (argument, expected) => {
    const exec = vi.fn();
    const onDelivery = vi.fn(async (delivery: { text: string; mentionTarget: string | null }) => ({
      message: {
        id: 'sent',
        sequence: 1,
        type: 'assistant.message',
        occurredAt: '2026-09-20T00:00:00Z',
        payload: { content: delivery.text, actorParticipantId: 'sender', mentionedParticipantIds: [] },
      },
      replayed: false,
    }));
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const result = await sandbox.exec('sandbox', {
      command: `qoderwake messages send conversation --text ${argument} --not-mention --yes --json`,
      toolCallId: 'quoted',
      timeoutMs: 1000,
    });
    expect(result.exitCode).toBe(0);
    expect(onDelivery.mock.calls[0]?.[0]).toMatchObject({ text: expected, mentionTarget: null });
    expect(JSON.parse(result.stdout).message.body.text).toBe(expected);
    expect(exec).not.toHaveBeenCalled();
  });
  it.each([
    'qoderwake messages claim conversation --format user-message',
    'qoderwake messages read conversation --claim 10000000-0000-4000-8000-000000000001 --message message',
  ])('rejects model-owned delivery commands under passive: %s', async (command) => {
    const exec = vi.fn();
    const onList = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery: vi.fn(),
      onList,
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    expect(await sandbox.exec('sandbox', { command, toolCallId: 'passive', timeoutMs: 1000 })).toMatchObject({
      exitCode: 1,
      stderr: '[qoderwake] the daemon manages claim/read for this Run',
    });
    expect(exec).not.toHaveBeenCalled();
    expect(onList).not.toHaveBeenCalled();
  });
  it.each([
    { audience: [], privateReaders: [] },
    { audience: ['resolved-participant'], privateReaders: [] },
    { audience: ['resolved-participant'], privateReaders: ['resolved-participant'] },
    { audience: [], privateReaders: ['actual-sender'] },
  ])(
    'serializes the committed JSON receipt with audience $audience',
    async ({ audience, privateReaders }) => {
      const message = {
        id: 'canonical-message',
        sequence: 42,
        type: 'assistant.message',
        occurredAt: '2026-09-20T00:00:00.000Z',
        payload: {
          content: 'Committed body',
          actorParticipantId: 'actual-sender',
          mentionedParticipantIds: audience,
          ...(privateReaders.length ? { privateParticipantIds: privateReaders } : {}),
        },
      };
      const onDelivery = vi.fn(async (_delivery: { privateTargets?: string[] }) => ({
        message,
        replayed: true,
      }));
      const sandbox = createV3GroupMessagingSandbox({
        sandbox: { create: vi.fn(), exec: vi.fn(), destroy: vi.fn() },
        conversationId: 'conversation',
        onDelivery,
        onList: vi.fn(),
        onGoalGet: vi.fn(),
        onGoalMutate: vi.fn(),
      });
      const result = await sandbox.exec('sandbox', {
        toolCallId: 'receipt',
        timeoutMs: 1000,
        command: `qoderwake messages send conversation --text requested --json ${audience.length ? '--mention alias' : '--not-mention --yes'} ${privateReaders.length ? '--private-to reader-alias' : ''}`,
      });
      expect(result.exitCode).toBe(0);
      if (privateReaders.length)
        expect(onDelivery.mock.calls[0]?.[0]).toMatchObject({ privateTargets: ['reader-alias'] });
      expect(JSON.parse(result.stdout)).toEqual({
        message: {
          id: message.id,
          conversationId: 'conversation',
          seq: 42,
          senderParticipantId: 'actual-sender',
          body: { type: 'text', text: 'Committed body' },
          audience: audience.map((participantId) => ({ participantId })),
          ...(privateReaders.length
            ? { privateTo: privateReaders.map((participantId) => ({ participantId })) }
            : {}),
          intent: audience.length ? 'request_action' : 'chat',
          deliveryPolicy: audience.length ? 'wake' : 'store_only',
          idempotencyKey: 'remote:canonical-message',
          createdAt: message.occurredAt,
        },
        deliveries: [],
        replayed: true,
      });
    },
  );
  it.each(['cmsg_01m2xj5b9dafaqefve7enhphf1', 'cmsg_00000000000000000000000000'])(
    'accepts official reply-to input without inventing a visible quote or wake: %s',
    (reference) => {
      expect(
        parseV3GroupMessageSendCommand(
          `qoderwake messages send conversation --reply-to ${reference} --text FYI --not-mention --yes`,
          { conversationId: 'conversation' },
        ),
      ).toEqual({ text: 'FYI', mentionTarget: null });
    },
  );

  it('parses one exact visible message and one optional routed participant', () => {
    expect(
      parseV3GroupMessageSendCommand(
        'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text "API contract ready" --mention 10000000-0000-4000-8000-000000000002',
        { conversationId: '20000000-0000-4000-8000-000000000001' },
      ),
    ).toEqual({ text: 'API contract ready', mentionTarget: members[1]!.id });
    expect(
      parseV3GroupMessageSendCommand(
        "qoderwake messages send 20000000-0000-4000-8000-000000000001 --text 'Final Leader answer'",
        { conversationId: '20000000-0000-4000-8000-000000000001' },
      ),
    ).toEqual({ text: 'Final Leader answer', mentionTarget: null });
  });

  it.each([
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --mention hd --text "API contract ready"',
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text "API contract ready" --mention hd',
  ])('accepts the officially observed flag order: %s', (command) => {
    expect(
      parseV3GroupMessageSendCommand(command, { conversationId: '20000000-0000-4000-8000-000000000001' }),
    ).toEqual({ text: 'API contract ready', mentionTarget: 'hd' });
  });

  it.each([
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --mention hd --mention fe',
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text x --text y',
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text x --json --json',
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text x --reply-to a --reply-to b',
    'echo @hd',
    'qoderwake messages send wrong-conversation --text "x"',
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text "x" --mention 10000000-0000-4000-8000-000000000002 --mention 10000000-0000-4000-8000-000000000003',
    'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text "x"; echo forged',
  ])('does not derive a route from unsupported or ambiguous input: %s', (command) => {
    expect(() =>
      parseV3GroupMessageSendCommand(command, {
        conversationId: '20000000-0000-4000-8000-000000000001',
      }),
    ).toThrow();
  });

  it('acknowledges durable message receipts and never executes control commands in the generic sandbox', async () => {
    const exec = vi.fn();
    const onDelivery = vi.fn(async (_delivery, toolCallId: string) => ({
      message: {
        id: `message-${toolCallId}`,
        sequence: 7,
        type: 'assistant.message',
        occurredAt: '2026-09-20T00:00:00Z',
        payload: { mentionedParticipantIds: [] },
      },
      replayed: false,
    }));
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: {
        create: vi.fn(async () => 'sandbox-01'),
        exec,
        destroy: vi.fn(async () => undefined),
      },
      conversationId: '20000000-0000-4000-8000-000000000001',

      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });

    await expect(
      sandbox.exec('sandbox-01', {
        toolCallId: 'tool-01',
        command:
          'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text "handoff" --mention 10000000-0000-4000-8000-000000000002',
        timeoutMs: 10_000,
      }),
    ).resolves.toMatchObject({ exitCode: 0, stdout: 'Message sent. seq=7 id=message-tool-01', stderr: '' });
    expect(onDelivery).toHaveBeenCalledWith({ text: 'handoff', mentionTarget: members[1]!.id }, 'tool-01');
    expect(exec).not.toHaveBeenCalled();

    await expect(
      sandbox.exec('sandbox-01', {
        toolCallId: 'tool-02',
        command:
          'qoderwake messages send 20000000-0000-4000-8000-000000000001 --text "fanout" --mention 10000000-0000-4000-8000-000000000003',
        timeoutMs: 10_000,
      }),
    ).resolves.toMatchObject({ exitCode: 0, stdout: 'Message sent. seq=7 id=message-tool-02', stderr: '' });
    expect(onDelivery).toHaveBeenCalledTimes(2);
  });

  it('does not publish after cancellation or acknowledge a failed commit', async () => {
    const onDelivery = vi.fn(async () => {
      throw new Error('Commit unavailable');
    });
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec: vi.fn(), destroy: vi.fn() },
      conversationId: 'conversation',

      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const request = {
      toolCallId: 'tool-01',
      command: 'qoderwake messages send conversation --text "result"',
      timeoutMs: 1_000,
    };
    const cancellation = new AbortController();
    cancellation.abort(new Error('Stopped'));
    await expect(sandbox.exec('sandbox', request, cancellation.signal)).rejects.toThrow('Stopped');
    expect(onDelivery).not.toHaveBeenCalled();
    await expect(sandbox.exec('sandbox', request)).resolves.toMatchObject({
      exitCode: 2,
      stderr: 'Commit unavailable',
    });
  });

  it('does not publish explicit non-waking messages until the observed confirmation is supplied', async () => {
    const onDelivery = vi.fn(async () => ({
      message: {
        id: 'confirmed-message',
        sequence: 8,
        type: 'assistant.message',
        occurredAt: '2026-09-20T00:00:00Z',
        payload: { mentionedParticipantIds: [] },
      },
      replayed: false,
    }));
    const exec = vi.fn();
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
      conversationId: 'conversation',
      onDelivery,
      onList: vi.fn(),
      onGoalGet: vi.fn(),
      onGoalMutate: vi.fn(),
    });
    const request = {
      toolCallId: 'confirm',
      command: 'qoderwake messages send conversation --not-mention --text "FYI"',
      timeoutMs: 1000,
    };
    expect(await sandbox.exec('sandbox', request)).toMatchObject({
      exitCode: 1,
      stderr: expect.stringContaining('No message was sent.'),
    });
    expect(onDelivery).not.toHaveBeenCalled();
    expect(exec).not.toHaveBeenCalled();
    expect(await sandbox.exec('sandbox', { ...request, command: `${request.command} --yes` })).toMatchObject({
      exitCode: 0,
      stdout: 'Message sent. seq=8 id=confirmed-message',
    });
    expect(onDelivery).toHaveBeenCalledExactlyOnceWith({ text: 'FYI', mentionTarget: null }, 'confirm');
  });

  it.each([
    '--text FYI --mention hd --not-mention --yes',
    '--text FYI --not-mention --yes --yes',
    '--text FYI --not-mention --not-mention --yes',
    '--text FYI --yes',
  ])('rejects contradictory or duplicate non-waking flags: %s', (flags) => {
    expect(() =>
      parseV3GroupMessageSendCommand(`qoderwake messages send conversation ${flags}`, {
        conversationId: 'conversation',
      }),
    ).toThrow();
  });
});
