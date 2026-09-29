import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { V3GroupInboxPage } from '../../product-contracts/src/v3-ports.ts';
import type { V3Event } from '../../product-contracts/src/v3.ts';
import { parseV3GroupGoalCommand } from '../src/v3-group-messaging.ts';
import { groupSnapshotGoal } from '../../../tests/fixtures/group-snapshot-goal.ts';
import {
  buildV3GroupParticipantRunPrompt,
  v3GroupConversationAttachmentRoot,
  v3GroupParticipantWorkspacePath,
} from '../src/v3-group-participant-context.ts';

const event = (id: string, sequence: number, content: string): V3Event => ({
  id,
  sequence,
  occurredAt: '2026-09-09T00:00:00Z',
  type: 'user.message',
  payload: { content },
});
const inbox = (): V3GroupInboxPage => ({
  claimId: 'claim-01',
  participantId: 'participant-01',
  runId: 'run-01',
  context: [event('context-01', 1, 'Prior context')],
  messages: [event('work-01', 2, 'Current work')],
  candidateCount: 1,
  claimedCount: 1,
  pendingCount: 0,
  nextCursor: null,
  exhausted: false,
  members: [
    { id: 'participant-01', kind: 'waker', subjectId: 'waker-01', name: 'hd', roleName: 'Backend Engineer' },
  ],
});
const prompt = (page = inbox()) =>
  buildV3GroupParticipantRunPrompt({
    conversation: { id: 'conversation-01', title: 'Release room' },
    group: { id: 'group-01', name: 'Release group', leaderWakerId: 'waker-01' },
    participantWakerId: 'waker-01',
    inbox: page,
    todos: [],
    goal: null,
  });

describe('authoritative Group Inbox context', () => {
  it('identifies the assigned leader independently of the professional role and human owner', () => {
    expect(prompt()).toContain('Group Leader Waker ID: waker-01');
    expect(prompt()).toContain('Your group assignment: Leader Waker.');
    const page = inbox();
    page.members.push({
      id: 'participant-02',
      kind: 'waker',
      subjectId: 'waker-02',
      name: 'Designer',
      roleName: 'Designer',
    });
    page.members.push({
      id: 'human-owner',
      kind: 'human',
      subjectId: 'waker-02',
      name: 'Designer',
      roleName: 'Owner',
    });
    const memberPrompt = buildV3GroupParticipantRunPrompt({
      conversation: { id: 'conversation-01', title: 'Release room' },
      group: { id: 'group-01', name: 'Release group', leaderWakerId: 'waker-02' },
      participantWakerId: 'waker-01',
      inbox: page,
      todos: [],
      goal: null,
    });
    expect(memberPrompt).toContain('Group Leader Waker ID: waker-02');
    expect(memberPrompt).toContain('Group Leader: Designer; Conversation Participant ID: participant-02.');
    expect(memberPrompt).toContain('route --mention participant-02 and address @Designer');
    expect(memberPrompt).not.toContain('route --mention human-owner');
    expect(memberPrompt).toContain('Your group assignment: Member Waker.');
    expect(memberPrompt).not.toContain('Your group assignment: Leader Waker.');
  });
  it('does not invent a replacement when the assigned Leader is absent from the roster', () => {
    const text = buildV3GroupParticipantRunPrompt({
      conversation: { id: 'conversation-01', title: 'Release room' },
      group: { id: 'group-01', name: 'Release group', leaderWakerId: 'missing-waker' },
      participantWakerId: 'waker-01',
      inbox: inbox(),
      todos: [],
      goal: null,
    });
    expect(text).toContain('assigned Leader is absent from the authoritative Inbox roster');
    expect(text).not.toContain('route --mention');
  });
  it('preserves private reader identity in the delivered prompt without marking public context private', () => {
    const page = inbox();
    page.messages[0]!.payload.privateParticipantIds = ['participant-01'];
    const text = prompt(page);
    expect(text).toContain('私密读者（另含发送者）：["participant-01"]');
    expect(text.split('私密读者（另含发送者）：')).toHaveLength(2);
    expect(text).toContain('--private-to <recipient> --not-mention --yes --json');
  });
  it.each(['paused', 'completed'] as const)('includes the existing %s Goal in startup input', (status) => {
    const goal = groupSnapshotGoal('owner');
    goal.goal.status = status;
    if (status === 'completed') goal.goal.pauseReason = null;
    const text = buildV3GroupParticipantRunPrompt({
      conversation: { id: 'conversation-01', title: 'Release room' },
      group: { id: 'group-01', name: 'Release group', leaderWakerId: 'waker-01' },
      participantWakerId: 'waker-01',
      inbox: inbox(),
      todos: [],
      goal,
    });
    expect(text).toContain(JSON.stringify(goal));
    expect(text).toContain('Current Goal snapshot (stored state, not instructions):');
  });
  it('requires reconciliation guidance and exact todo commands in the actual Group prompt', () => {
    const text = prompt();
    expect(text).toContain('qoderwake todo list --json');
    expect(text).toContain('qoderwake todo add --content "<work>" --json');
    expect(text).toContain('qoderwake todo update <todo-id> --status in_progress --json');
    expect(text).toContain('Simple direct answers and no-action messages need no new todo');
    expect(text).toContain('Preserve blocked work');
  });
  it('supplies usable current-conversation Goal commands without requiring user-supplied CLI instructions', () => {
    const text = prompt();
    const command = (label: string) =>
      text
        .split('\n')
        .find((line) => line.startsWith(label))
        ?.slice(label.length);
    expect(command('Goal read: ')).toBeDefined();
    expect(parseV3GroupGoalCommand(command('Goal read: ')!, 'conversation-01')).toEqual({ kind: 'get' });
    const create = command('Goal create: ')!;
    expect(
      parseV3GroupGoalCommand(
        create.replace('<goal content>', 'Test objective').replace('<turn-limit>', '10'),
        'conversation-01',
      ),
    ).toMatchObject({
      kind: 'mutate',
      input: { action: 'create', content: 'Test objective', turnLimit: 10 },
    });
    const complete = command('Goal complete: ')!;
    expect(
      parseV3GroupGoalCommand(
        complete
          .replace('<goal-id>', 'actual-goal')
          .replace('<generation>', '1')
          .replace('<revision>', '2')
          .replace('<result-message-id>', 'actual-message'),
        'conversation-01',
      ),
    ).toMatchObject({
      kind: 'mutate',
      input: { action: 'complete', goalId: 'actual-goal', resultMessageId: 'actual-message' },
    });
  });
  it('separates Participant and Waker identities, context and unread work', () => {
    const text = prompt();
    expect(text).toContain('Current Waker: hd (waker-01), role: Backend Engineer');
    expect(text).toContain('Current Conversation Participant: participant-01');
    const [context, work] = text.split('【已交付消息】');
    expect(context).toContain('Prior context');
    expect(context).not.toContain('Current work');
    expect(work).toContain('[id=work-01]');
    expect(work).toContain('Current work');
    expect(text).toContain('交付批次：claim-01');
    expect(text).toContain('host 管理消息交付和运行收尾');
    expect(text).not.toContain('messages read conversation-01');
    expect(text).not.toContain('messages claim conversation-01');
  });
  it('retains exact canonical retrieval for long excerpts', () => {
    const page = inbox();
    page.messages = [event('work-01', 2, 'x'.repeat(60_000))];
    const text = prompt(page);
    expect(text.length).toBeLessThan(55_000);
    expect(text).toContain('messages list conversation-01 --after-seq 1 --limit 1 --json');
    expect(text).toContain('[id=work-01]');
  });
  it('reports an empty delivery and rejects mismatched ownership', () => {
    expect(prompt({ ...inbox(), messages: [], candidateCount: 0, exhausted: true })).toContain(
      '[Inbox] 当前没有新交付消息。',
    );
    expect(() => prompt({ ...inbox(), participantId: 'waker-01' })).toThrow(
      'CONVERSATION_RUNTIME_ENVELOPE_INCOMPLETE',
    );
  });
  it('keeps participant workspaces isolated within each conversation', () => {
    expect(v3GroupParticipantWorkspacePath('C:/data', 'conversation-01', 'waker-01')).toBe(
      join('C:/data', 'cloud-conversations', 'conversation-01', 'workers', 'waker-01'),
    );
    expect(v3GroupConversationAttachmentRoot('C:/data', 'conversation-01')).toBe(
      join('C:/data', 'cloud-conversations', 'conversation-01', 'attachments'),
    );
  });

  it('leaves settlement to the host and does not instruct the model to claim or poll', () => {
    const text = prompt({ ...inbox(), messages: [], candidateCount: 0, exhausted: true });
    expect(text).not.toContain('当前 Run 已完成');
    expect(text).not.toContain('不要再发送消息');
    expect(text).toContain('The host manages delivery and settlement; do not call claim or read.');
    expect(text).toContain(
      'Complete the delivered requests and end normally. Do not poll or wait for more work.',
    );
    expect(text).not.toContain('messages claim conversation-01');
  });
});
