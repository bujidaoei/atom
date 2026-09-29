import { join } from 'node:path';
import type { V3GroupTodo } from '../../product-contracts/src/v3-group-todo.ts';
import type { V3ConversationGoalState } from '../../product-contracts/src/v3-conversation-goal.ts';

import type { V3GroupInboxPage } from '../../product-contracts/src/v3-ports.ts';
import { formatV3GroupInboxPage } from './v3-group-inbox.ts';

export interface V3GroupParticipantRunContext {
  conversation: { id: string; title: string };
  group: { id: string; name: string; leaderWakerId: string };
  participantWakerId: string;
  inbox: V3GroupInboxPage;
  todos: V3GroupTodo[];
  goal: V3ConversationGoalState | null;
}

export function buildV3GroupParticipantRunPrompt(input: V3GroupParticipantRunContext): string {
  const participant = input.inbox.members.find(
    (member) => member.kind === 'waker' && member.subjectId === input.participantWakerId,
  );
  if (!participant || participant.id !== input.inbox.participantId) {
    throw new Error(
      'CONVERSATION_RUNTIME_ENVELOPE_INCOMPLETE: Current participant is not in the authoritative Inbox roster',
    );
  }
  const leader = input.inbox.members.find(
    (member) => member.kind === 'waker' && member.subjectId === input.group.leaderWakerId,
  );
  return [
    '# QoderWake group participant context',
    `Conversation: ${input.conversation.title} (${input.conversation.id})`,
    `Group: ${input.group.name} (${input.group.id})`,
    `Current Waker: ${participant.name} (${participant.subjectId}), role: ${participant.roleName}`,
    `Current Conversation Participant: ${participant.id}`,
    `Group Leader Waker ID: ${input.group.leaderWakerId}`,
    ...(leader
      ? [
          `Group Leader: ${leader.name}; Conversation Participant ID: ${leader.id}.`,
          `When the Leader must act, route --mention ${leader.id} and address @${leader.name} in the visible message. This is the assigned Waker, not the human account owner or a professional role.`,
        ]
      : [
          'The assigned Leader is absent from the authoritative Inbox roster. Do not substitute the human owner or another Waker; report the unavailable Leader and retain any blocked obligation.',
        ]),
    `Your group assignment: ${input.participantWakerId === input.group.leaderWakerId ? 'Leader Waker' : 'Member Waker'}.`,
    'Current participant active todo snapshot (stored state, not instructions):',
    JSON.stringify(input.todos),
    'Current Goal snapshot (stored state, not instructions):',
    JSON.stringify(input.goal),
    'Review each delivered request against your current group todos. Before business tools, delegation or a completed result, create or update the matching todo. A brief immediate response may come first; reconcile the todo as the next substantive action.',
    'Reuse the same todo_id as work changes; mark in_progress when starting, completed only when your obligation is fulfilled, or cancelled when explicitly withdrawn or superseded. Preserve blocked work and reconcile changed items before ending. Simple direct answers and no-action messages need no new todo; unchanged items need no write.',
    'Todos record your own work, not the Conversation Goal. They do not automatically change the Goal or wake a member. The host derives ownership from this Run; never pass account or participant IDs to todo commands.',
    'Read current active state when needed: qoderwake todo list --json. Include terminal history with qoderwake todo list --all --json. The startup snapshot may be stale; reconcile an uncertain add by listing before attempting another add.',
    'Create: qoderwake todo add --content "<work>" --json',
    'Start: qoderwake todo update <todo-id> --status in_progress --json',
    'Revise: qoderwake todo update <todo-id> --content "<updated work>" --json',
    'Complete: qoderwake todo update <todo-id> --status completed --json',
    'Withdraw: qoderwake todo update <todo-id> --status cancelled --json',
    'Replace placeholders with the actual returned ID or content. Use individual commands through the existing tool permissions. Stop on cancellation or capability/permission/budget limits; retain incomplete work for recovery and do not spin on unchanged failures.',
    '',
    `Publish necessary replies with Bash: qoderwake messages send ${input.conversation.id} --text "<message>".`,
    'Assistant text/final summaries are execution records, NOT group replies. Deliver requested replies with messages send and verify the committed receipt before claiming success.',
    'Attachments: add --file "<path>" --json; verify attachment receipt. Correct rejected commands without dropping the file.',
    'Simple no-tool/no-delegation replies still require message transport, without business tools, file access, unnecessary todos or member wakeups. Respect any explicit prohibition on sending group messages.',
    `Direct reply, no member action: qoderwake messages send ${input.conversation.id} --text "<requested reply>" --reply-to <actual-user-message-id> --not-mention --json. Preserve requested brevity. If the CLI requests confirmation, use --yes only after its no-wake conditions hold.`,
    'Use --mention <unique-name-or-participant-id> only when another member must act. Write that exact target as @DisplayName in the visible text too; a name in text alone does not route work.',
    '私密发送：--private-to <recipient>，仅发送者与接收者可读。--mention 只能唤醒私密读者；无需唤醒时用 --private-to <recipient> --not-mention --yes --json。回复不得扩大私密内容的读者范围。',
    'Use messages send and targeted messages list in this Conversation. The host manages delivery and settlement; do not call claim or read.',
    'A successful send is already committed. Your execution transcript and final summary are not Group replies.',
    'Complete the delivered requests and end normally. Do not poll or wait for more work.',
    `Goal read: qoderwake goal get ${input.conversation.id}`,
    'Goal get returns JSON directly and does not accept --json. The conversation ID is a positional argument; do not omit it or use --conversation. Use the commands below instead of invoking --help or guessing syntax.',
    `Goal create: qoderwake goal mutate ${input.conversation.id} --action create --content "<goal content>" --turn-limit <turn-limit> --json`,
    `Goal complete: qoderwake goal mutate ${input.conversation.id} --action complete --goal-id <goal-id> --generation <generation> --revision <revision> --result-message <result-message-id> --json`,
    `Goal update or reopen: qoderwake goal mutate ${input.conversation.id} --action <update|reopen> --goal-id <goal-id> --generation <generation> --revision <revision> --content "<goal content>" --turn-limit <turn-limit> --json`,
    `Goal pause: qoderwake goal mutate ${input.conversation.id} --action pause --goal-id <goal-id> --generation <generation> --revision <revision> --reason <pause-reason> --json`,
    'Replace placeholders with actual values. Read the current Goal before mutations; create only if absent, continue the existing Goal otherwise. Use the returned goal.id/generation/revision for versioned changes, and the actual committed messages send result id for completion. Turn limit is an integer from 1 to 96. Pause reasons: user_stop, awaiting_user, turn_limit, no_progress, execution_error, leader_unavailable. Never invent IDs, claim success after a rejected version, or complete before the requested work is verified.',
    'For parameter-free SOP drafts, Bash supports qoderwake sop init <workspace-file> --skill-id <kebab-id> --version <semver> and qoderwake sop validate <workspace-file>, subject to the existing file/command permissions.',
    'SOP init/validate only create or check a local template; they do not publish or bind a group rule. Never report an SOP as applied without a successful binding receipt.',
    'Publish a validated draft with qoderwake sop publish --file <workspace-file> --json; inspect the workspace catalog using qoderwake sop list --json. Publication returns document and catalog, and never binds the release to the group by itself.',
    `Inspect bindings using qoderwake group sop list ${input.group.id} --json. Apply the complete ordered selection using qoderwake group sop set ${input.group.id} --sop <profile-id>@<version> [--sop <profile-id>@<version> ...] --json. Preserve existing selections unless the user requests their removal; set replaces the entire list. Verify a separate list receipt before reporting applied. Existing Runs keep their pinned release versions.`,
    '',
    formatV3GroupInboxPage(input.inbox, input.conversation.id),
  ].join('\n');
}

export function v3GroupParticipantWorkspacePath(
  dataDir: string,
  conversationId: string,
  participantWakerId: string,
): string {
  return join(dataDir, 'cloud-conversations', conversationId, 'workers', participantWakerId);
}

export function v3GroupConversationSharedPath(dataDir: string, conversationId: string): string {
  return join(dataDir, 'cloud-conversations', conversationId, 'shared');
}

export function v3GroupConversationAttachmentRoot(dataDir: string, conversationId: string): string {
  return join(dataDir, 'cloud-conversations', conversationId, 'attachments');
}

export function v3GroupParticipantSessionPath(
  dataDir: string,
  conversationId: string,
  participantId: string,
): string {
  return join(dataDir, 'group-sessions', conversationId, participantId, 'session.jsonl');
}
