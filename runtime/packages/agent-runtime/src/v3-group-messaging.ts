import { isAbsolute } from 'node:path';
import { executeGroupShell } from './group-shell-bridge.ts';
import { V3GroupTodoNotFoundError } from '../../product-contracts/src/v3-group-todo.ts';
import type {
  V3GroupTodo,
  V3GroupTodoCommand,
  V3GroupTodoStatus,
} from '../../product-contracts/src/v3-group-todo.ts';
import type {
  V3ConversationGoalState,
  V3GoalMutation,
  V3GoalPauseReason,
} from '../../product-contracts/src/v3-conversation-goal.ts';

import type {
  SandboxClient,
  SandboxExecRequest,
  SandboxExecResult,
} from '../../product-contracts/src/index.ts';
import type { V3Event } from '../../product-contracts/src/v3.ts';
import { executeV3GroupSopAuthoring, readV3SopTemplate } from './v3-group-sop-authoring.ts';
import {
  sopCatalogEntries,
  type V3SopRelease,
  type V3SopTemplate,
  type V3GroupSopSelection,
  type V3GroupSopReplacement,
  type V3GroupSopBindings,
} from '../../product-contracts/src/v3-group-sop.ts';

export interface V3GroupMessageDelivery {
  filePath?: string;
  text: string;
  mentionTarget: string | null;
  privateTargets?: string[];
}

export interface V3GroupAttachmentDownload {
  messageId: string;
  attachmentId: string;
  outputPath?: string;
}

function attachmentDownloadCommand(command: string, conversationId: string): V3GroupAttachmentDownload {
  const tokens = commandTokens(command);
  if (
    tokens.slice(0, 4).join(' ') !== 'qoderwake messages attachment download' ||
    tokens[4] !== conversationId
  )
    throw new Error('Attachment command is outside the current conversation authority');
  const messageId = tokens[5];
  const attachmentId = tokens[6];
  if (
    !messageId ||
    !attachmentId ||
    [messageId, attachmentId].some((id) => id.startsWith('--') || id.length > 256)
  )
    throw new Error('Attachment message and attachment identities are required');
  let outputPath: string | undefined;
  let json = false;
  for (let index = 7; index < tokens.length; index++) {
    if (tokens[index] === '--json' && !json) {
      json = true;
      continue;
    }
    if (tokens[index] === '--out' && outputPath === undefined && tokens[index + 1]) {
      outputPath = tokens[++index]!;
      if (!isAbsolute(outputPath)) throw new Error('Attachment output path must be absolute');
      continue;
    }
    throw new Error('Invalid or duplicate attachment download argument');
  }
  return { messageId, attachmentId, ...(outputPath ? { outputPath } : {}) };
}

/** Shell syntax must go through the existing sandbox bridge, not the host CLI parser. */
export function isDirectV3GroupControlCommand(command: string): boolean {
  try {
    return commandTokens(command)[0] === 'qoderwake';
  } catch {
    return false;
  }
}

function commandTokens(command: string): string[] {
  if (!command.trim() || command.includes('\0')) {
    throw new Error('Invalid QoderWake message command');
  }
  const tokens: string[] = [];
  let token = '';
  let tokenStarted = false;
  let quote: 'single' | 'double' | 'ansi' | undefined;
  let escaped = false;
  const push = () => {
    if (!tokenStarted) return;
    tokens.push(token);
    token = '';
    tokenStarted = false;
  };
  const source = command.trim();
  for (let index = 0; index < source.length; index++) {
    const character = source[index]!;
    if (escaped) {
      tokenStarted = true;
      if (quote === 'ansi') {
        if (character === 'n') token += '\n';
        else if (character === '\\' || character === "'") token += character;
        else throw new Error('Unsupported QoderWake ANSI-C escape');
      } else if (quote === 'double' && !['$', '`', '"', '\\', '\n'].includes(character)) {
        token += `\\${character}`;
      } else if (character !== '\n') token += character;
      escaped = false;
      continue;
    }
    if (!quote && character === '$' && source[index + 1] === "'") {
      tokenStarted = true;
      quote = 'ansi';
      index++;
      continue;
    }
    if (character === '\\' && quote !== 'single') {
      escaped = true;
      continue;
    }
    if (character === "'" && quote !== 'double') {
      tokenStarted = true;
      quote = quote === 'single' || quote === 'ansi' ? undefined : 'single';
      continue;
    }
    if (character === '"' && quote !== 'single' && quote !== 'ansi') {
      tokenStarted = true;
      quote = quote === 'double' ? undefined : 'double';
      continue;
    }
    if (!quote && /[\r\n;&|<>`$()*?[\]{}~#]/u.test(character)) {
      throw new Error('QoderWake message command cannot contain shell control operators');
    }
    if (quote === 'double' && /[$`]/u.test(character)) {
      throw new Error('QoderWake message command requires shell evaluation');
    }
    if (!quote && /\s/u.test(character)) {
      push();
      continue;
    }
    tokenStarted = true;
    token += character;
  }
  if (escaped || quote) throw new Error('Unterminated QoderWake message command');
  push();
  return tokens;
}

class GroupMessageConfirmationRequired extends Error {
  constructor() {
    super(
      "[qoderwake] --not-mention wakes nobody. Before confirming, evaluate the Conversation's overall task, not only your local step:\n- Is the overall Conversation task truly complete? Do not treat completion of your local step as completion of the overall task.\n- Does this message ask anyone to act, choose, decide, confirm, aggregate, close, or reply? If yes, use --mention <member>.\n- If the overall task is unfinished, has the concrete next actor already been woken, or will this Run send a waking handoff before completing this Run? If not, use --mention <member> now.\n- Only if this message is intentionally context-only and requires no recipient action, rerun with --not-mention --yes. No message was sent.",
    );
  }
}

/** Official `qoderwake messages send --help`, limited to the options this host accepts. */
export const V3_GROUP_MESSAGE_SEND_HELP = `Usage: qoderwake messages send [options] <convId>

send a message to a conversation

Arguments:
  convId                   conversation id

Options:
  --text <text>            message text (required)
  --mention <idOrName>     wake a conversation member
  --not-mention            send without waking anyone
  --yes                    deprecated compatibility flag; has no effect
  --private-to <idOrName>  restrict visibility to sender + listed members
  --reply-to <seqOrId>     quote an earlier message by seq or message id
  --file <path>            attach a local file via the upload flow
  --json                   output raw JSON
  -h, --help               display help for command
`;

function messageSendSyntaxError(reason: string): Error {
  return new Error(
    `${reason}. Attach files with --file <path>. Run qoderwake messages send --help for supported arguments. No message was sent.`,
  );
}

export function parseV3GroupMessageSendCommand(
  command: string,
  authority: { conversationId: string },
): V3GroupMessageDelivery & { json?: true } {
  const tokens = commandTokens(command);
  if (tokens.length < 6) {
    throw messageSendSyntaxError('QoderWake message command has an invalid argument count');
  }
  if (
    tokens[0] !== 'qoderwake' ||
    tokens[1] !== 'messages' ||
    tokens[2] !== 'send' ||
    tokens[3] !== authority.conversationId
  ) {
    throw new Error('QoderWake message command is outside the current conversation authority');
  }
  const argumentsByName = new Map<string, string>();
  const switches = new Set<string>();
  for (let index = 4; index < tokens.length; index++) {
    const flag = tokens[index]!;
    if (['--not-mention', '--yes', '--json'].includes(flag)) {
      if (switches.has(flag)) throw messageSendSyntaxError('Duplicate QoderWake message argument');
      switches.add(flag);
      continue;
    }
    if (
      !['--text', '--mention', '--reply-to', '--private-to', '--file'].includes(flag) ||
      argumentsByName.has(flag) ||
      !tokens[index + 1]
    )
      throw messageSendSyntaxError('QoderWake message command has invalid or duplicate arguments');
    argumentsByName.set(flag, tokens[++index]!);
  }
  const text = argumentsByName.get('--text')?.trim() ?? '';
  if (!text || text.length > 64 * 1024) throw new Error('QoderWake message text is invalid');
  if (switches.has('--not-mention') && argumentsByName.has('--mention'))
    throw new Error('--not-mention and --mention cannot be combined');
  if (switches.has('--yes') && !switches.has('--not-mention'))
    throw new Error('--yes requires --not-mention');
  if (switches.has('--not-mention') && !switches.has('--yes')) throw new GroupMessageConfirmationRequired();
  // The observed official cloud send accepts reply-to (including absent IDs),
  // but neither its receipt nor canonical history exposes a quote or route.
  const privateTarget = argumentsByName.get('--private-to');
  if (privateTarget !== undefined && (!privateTarget.trim() || privateTarget.length > 256))
    throw new Error('QoderWake private message route is invalid');
  const filePath = argumentsByName.get('--file');
  const format = {
    ...(filePath ? { filePath } : {}),
    ...(switches.has('--json') ? { json: true as const } : {}),
    ...(privateTarget ? { privateTargets: [privateTarget] } : {}),
  };
  if (!argumentsByName.has('--mention')) return { text, mentionTarget: null, ...format };
  const mentionTarget = argumentsByName.get('--mention')!;
  if (!mentionTarget.trim() || mentionTarget.length > 256)
    throw new Error('QoderWake message route is invalid');
  return { text, mentionTarget, ...format };
}

export type V3GroupInboxCommand =
  | { kind: 'claim'; limit?: number; cursor?: string; json: boolean }
  | { kind: 'read'; claimId: string; messageIds: string[]; json: boolean }
  | { kind: 'list'; afterSequence: number; limit: number; json: boolean };

export function parseV3GroupInboxCommand(command: string, conversationId: string): V3GroupInboxCommand {
  const tokens = commandTokens(command);
  const kind = tokens[2];
  if (
    tokens[0] !== 'qoderwake' ||
    tokens[1] !== 'messages' ||
    !['claim', 'read', 'list'].includes(kind ?? '') ||
    tokens[3] !== conversationId
  ) {
    throw new Error('Inbox command is outside the current conversation authority');
  }
  const values = new Map<string, string>();
  const messageIds: string[] = [];
  let json = false;
  for (let index = 4; index < tokens.length; index += 1) {
    const flag = tokens[index]!;
    if (flag === '--json') {
      json = true;
      continue;
    }
    const allowed =
      kind === 'read'
        ? ['--claim', '--message', '--format']
        : kind === 'claim'
          ? ['--limit', '--cursor', '--format']
          : ['--after-seq', '--limit', '--format'];
    if (!allowed.includes(flag) || !tokens[index + 1]) throw new Error('Invalid Inbox command argument');
    const value = tokens[++index]!;
    if (flag === '--message') messageIds.push(value);
    else {
      if (values.has(flag)) throw new Error('Duplicate Inbox command argument');
      values.set(flag, value);
    }
  }
  const format = values.get('--format');
  if (format && !['json', kind === 'claim' ? 'user-message' : 'table'].includes(format))
    throw new Error('Invalid Inbox output format');
  json ||= format === 'json';
  if (kind === 'read') {
    const claimId = values.get('--claim');
    if (!claimId || !messageIds.length) throw new Error('Read requires one claim and explicit message IDs');
    return { kind, claimId, messageIds, json };
  }
  const parseNumber = (raw: string, max: number, min: number) => {
    if (!/^\d+$/u.test(raw)) throw new Error('Invalid Inbox limit or sequence');
    const value = Number(raw);
    if (!Number.isSafeInteger(value) || value < min || value > max)
      throw new Error('Invalid Inbox limit or sequence');
    return value;
  };
  if (kind === 'claim')
    return {
      kind,
      json,
      ...(values.has('--limit') ? { limit: parseNumber(values.get('--limit')!, 50, 1) } : {}),
      ...(values.has('--cursor') ? { cursor: values.get('--cursor')! } : {}),
    };
  return {
    kind: 'list',
    json,
    afterSequence: parseNumber(values.get('--after-seq') ?? '0', Number.MAX_SAFE_INTEGER, 0),
    limit: parseNumber(values.get('--limit') ?? '20', 200, 1),
  };
}

export function parseV3GroupGoalCommand(
  command: string,
  conversationId: string,
): { kind: 'get' } | { kind: 'mutate'; input: V3GoalMutation } {
  const tokens = commandTokens(command);
  if (tokens[0] !== 'qoderwake' || tokens[1] !== 'goal' || tokens[3] !== conversationId)
    throw new Error('Goal command is outside the current conversation authority');
  const flags = new Map<string, string>();
  let json = false;
  for (let index = 4; index < tokens.length; index++) {
    const flag = tokens[index]!;
    if (flag === '--json') {
      if (json) throw new Error('Duplicate Goal output flag');
      json = true;
      continue;
    }
    if (
      !flag.startsWith('--') ||
      flags.has(flag) ||
      !tokens[index + 1] ||
      tokens[index + 1]!.startsWith('--')
    )
      throw new Error('Invalid or duplicate Goal argument');
    flags.set(flag, tokens[++index]!);
  }
  if (tokens[2] === 'get' && json) throw new Error("error: unknown option '--json'");
  if (tokens[2] === 'get' && flags.size === 0) return { kind: 'get' };
  if (tokens[2] !== 'mutate') throw new Error('Unsupported Goal command');
  const take = (flag: string) => {
    const value = flags.get(flag);
    if (!value?.trim()) throw new Error(`Goal requires ${flag}`);
    flags.delete(flag);
    return value;
  };
  const integer = (flag: string, max = Number.MAX_SAFE_INTEGER) => {
    const raw = take(flag);
    const value = Number(raw);
    if (!/^\d+$/u.test(raw) || !Number.isSafeInteger(value) || value < 1 || value > max)
      throw new Error(`Invalid Goal ${flag}`);
    return value;
  };
  const action = take('--action');
  const version =
    action === 'create'
      ? undefined
      : { goalId: take('--goal-id'), generation: integer('--generation'), revision: integer('--revision') };
  let input: V3GoalMutation;
  if (action === 'create')
    input = { action, content: take('--content'), turnLimit: integer('--turn-limit', 96) };
  else if (action === 'update' || action === 'reopen')
    input = { action, ...version!, content: take('--content'), turnLimit: integer('--turn-limit', 96) };
  else if (action === 'complete') input = { action, ...version!, resultMessageId: take('--result-message') };
  else if (action === 'pause') {
    const reason = take('--reason');
    if (
      ![
        'user_stop',
        'awaiting_user',
        'turn_limit',
        'no_progress',
        'execution_error',
        'leader_unavailable',
      ].includes(reason)
    )
      throw new Error('Invalid Goal pause reason');
    input = { action, ...version!, reason: reason as V3GoalPauseReason };
  } else throw new Error('Unsupported Goal action');
  if (flags.size) throw new Error('Unsupported Goal argument');
  return { kind: 'mutate', input };
}

export function groupGoalJson(state: V3ConversationGoalState | null) {
  if (!state) return { goal: null, runtime: null, schema_version: 1 };
  const goal = state.goal;
  return {
    goal: {
      id: goal.id,
      status: goal.status,
      content: goal.content,
      generation: goal.generation,
      revision: goal.revision,
      turn_limit: goal.turnLimit,
      created_at: goal.createdAt,
      updated_at: goal.updatedAt,
      created_by: goal.createdBy,
      updated_by: goal.updatedBy,
      requested_by: goal.requestedBy,
      source_message_id: goal.sourceMessageId,
      last_human_message_id: goal.lastHumanMessageId,
      last_human_message_seq: goal.lastHumanMessageSequence,
      result_message_id: goal.resultMessageId,
      pause_reason: goal.pauseReason,
    },
    runtime: {
      check: null,
      turn_count: state.runtime.turnCount,
      last_business_message_seq: state.runtime.lastBusinessMessageSequence,
    },
    schema_version: 1,
  };
}

function parseGroupTodoTokens(tokens: string[]): V3GroupTodoCommand {
  const action = tokens[2];
  const flags = new Map<string, string | true>();
  const todoId = action === 'update' ? tokens[3] : undefined;
  if (action === 'update' && (!todoId || todoId.startsWith('--')))
    throw new Error('Expected todo update <todo-id>.');
  for (let index = action === 'update' ? 4 : 3; index < tokens.length; index++) {
    const flag = tokens[index]!;
    if (flags.has(flag)) throw new Error('Duplicate todo argument.');
    if (flag === '--json' || (action === 'list' && flag === '--all')) flags.set(flag, true);
    else if (
      ((action === 'add' || action === 'update') && flag === '--content') ||
      (action === 'update' && flag === '--status')
    ) {
      const value = tokens[++index];
      if (value === undefined || value.startsWith('--')) throw new Error('Missing todo argument value.');
      flags.set(flag, value);
    } else throw new Error('Unsupported todo argument.');
  }
  if (!flags.has('--json')) throw new Error('Expected todo command --json.');
  if (action === 'list') return { action, all: flags.has('--all') };
  const content = flags.get('--content');
  if (action === 'add' && typeof content === 'string') return { action, content };
  if (action === 'update') {
    const status = flags.get('--status');
    if (
      status !== undefined &&
      !['pending', 'in_progress', 'completed', 'cancelled'].includes(String(status))
    )
      throw new Error('Unsupported todo status.');
    if (content === undefined && status === undefined) throw new Error('Expected a todo change.');
    return {
      action,
      todoId: todoId!,
      ...(typeof content === 'string' ? { content } : {}),
      ...(typeof status === 'string' ? { status: status as V3GroupTodoStatus } : {}),
    };
  }
  throw new Error('Expected todo list, add or update.');
}

function commandResult(
  request: SandboxExecRequest,
  input: { exitCode: number; stdout?: string; stderr?: string },
): SandboxExecResult {
  return {
    toolCallId: request.toolCallId,
    exitCode: input.exitCode,
    stdout: input.stdout ?? '',
    stderr: input.stderr ?? '',
    timedOut: false,
    truncated: false,
  };
}

function canonicalGroupMessage(message: V3Event, conversationId: string) {
  const audience = (message.payload.mentionedParticipantIds ?? []) as string[];
  const privateReaders = message.payload.privateParticipantIds as string[] | undefined;
  return {
    id: message.id,
    conversationId,
    seq: message.sequence,
    senderParticipantId: message.payload.actorParticipantId,
    body: { type: 'text', text: message.payload.content },
    ...(Array.isArray(message.payload.attachments) && message.payload.attachments.length
      ? {
          attachments: message.payload.attachments.map((file, ordinal) => ({
            attachment: {
              id: file.id,
              conversationId,
              ...(typeof file.creatorParticipantId === 'string'
                ? { creatorParticipantId: file.creatorParticipantId, kind: 'artifact' }
                : {}),
              filename: file.fileName,
              mimeType: file.mediaType,
              sizeBytes: file.sizeBytes,
              sha256: file.sha256,
              ...(typeof file.createdAt === 'string' ? { createdAt: file.createdAt } : {}),
              state: 'attached',
            },
            ordinal,
            ...(typeof file.associatedAt === 'string' ? { createdAt: file.associatedAt } : {}),
            ...(message.type === 'assistant.message' ? { role: 'output' } : {}),
          })),
        }
      : {}),
    audience: audience.map((participantId) => ({ participantId })),
    ...(privateReaders?.length
      ? { privateTo: privateReaders.map((participantId) => ({ participantId })) }
      : {}),
    intent: audience.length ? 'request_action' : 'chat',
    deliveryPolicy: audience.length ? 'wake' : 'store_only',
    idempotencyKey: `remote:${message.id}`,
    createdAt: message.occurredAt,
  };
}

function groupSendHelpRequested(tokens: string[]): boolean {
  for (let index = 3; index < tokens.length; index++) {
    if (['--text', '--mention', '--reply-to', '--private-to', '--file'].includes(tokens[index]!)) index++;
    else if (tokens[index] === '--help' || tokens[index] === '-h') return true;
  }
  return false;
}

function messageSendResult(
  request: SandboxExecRequest,
  conversationId: string,
  json: boolean | undefined,
  receipt: { message: V3Event; replayed: boolean },
) {
  return commandResult(request, {
    exitCode: 0,
    stdout: json
      ? JSON.stringify({
          message: canonicalGroupMessage(receipt.message, conversationId),
          deliveries: [],
          replayed: receipt.replayed,
        })
      : `Message sent. seq=${receipt.message.sequence} id=${receipt.message.id}`,
  });
}

/** Device file operations share the same parser and receipts on cloud hosts and remote desktops. */
export async function executeV3GroupDeviceCommand(
  request: SandboxExecRequest,
  options: {
    conversationId: string;
    sopWorkspacePath?: string;
    onSopCatalog?(input?: V3SopTemplate): Promise<V3SopRelease[]>;
    onFileDelivery?(
      delivery: V3GroupMessageDelivery & { filePath: string },
      toolCallId: string,
      signal?: AbortSignal,
    ): Promise<{ message: V3Event; replayed: boolean }>;
    onAttachmentDownload?(
      input: V3GroupAttachmentDownload,
      signal?: AbortSignal,
    ): Promise<{ path: string; sizeBytes: number; attachmentId: string; messageId: string }>;
  },
  signal?: AbortSignal,
): Promise<SandboxExecResult | undefined> {
  let tokens: string[];
  try {
    tokens = commandTokens(request.command);
  } catch {
    return undefined;
  }
  if (tokens[0] !== 'qoderwake') return undefined;
  const download = tokens.slice(1, 4).join(' ') === 'messages attachment download';
  const authoring = tokens[1] === 'sop' && ['init', 'validate'].includes(tokens[2] ?? '');
  const publishing = tokens[1] === 'sop' && tokens[2] === 'publish';
  const sending =
    Boolean(options.onFileDelivery) &&
    tokens[1] === 'messages' &&
    tokens[2] === 'send' &&
    tokens.includes('--file');
  if (!download && !authoring && !publishing && !sending) return undefined;
  try {
    signal?.throwIfAborted();
    if (sending) {
      if (groupSendHelpRequested(tokens))
        return commandResult(request, { exitCode: 0, stdout: V3_GROUP_MESSAGE_SEND_HELP });
      const delivery = parseV3GroupMessageSendCommand(request.command, {
        conversationId: options.conversationId,
      });
      if (!delivery.filePath) return undefined;
      const receipt = await options.onFileDelivery!(
        { ...delivery, filePath: delivery.filePath },
        request.toolCallId,
        signal,
      );
      signal?.throwIfAborted();
      return messageSendResult(request, options.conversationId, delivery.json, receipt);
    }
    if (download) {
      const input = attachmentDownloadCommand(request.command, options.conversationId);
      if (!options.onAttachmentDownload) throw new Error('Attachment download is unavailable');
      const result = await options.onAttachmentDownload(input, signal);
      signal?.throwIfAborted();
      return commandResult(request, { exitCode: 0, stdout: JSON.stringify(result) });
    }
    if (publishing) {
      if (!options.onSopCatalog) throw new Error('SOP catalog is unavailable.');
      let path: string | undefined;
      let json = false;
      for (let index = 3; index < tokens.length; index++) {
        if (tokens[index] === '--json' && !json) json = true;
        else if (tokens[index] === '--file' && !path && tokens[index + 1]) path = tokens[++index];
        else throw new Error('Expected sop publish --file <file> --json.');
      }
      if (!path || !options.sopWorkspacePath) throw new Error('SOP template file is required.');
      const document = await readV3SopTemplate(options.sopWorkspacePath, path, signal);
      signal?.throwIfAborted();
      const entries = sopCatalogEntries(await options.onSopCatalog(document));
      signal?.throwIfAborted();
      const catalog = entries.find((entry) => entry.skillId === document.skillId);
      if (!catalog?.releases.some((release) => release.version === document.version))
        throw new Error('Published SOP release is missing from the catalog receipt.');
      return commandResult(request, { exitCode: 0, stdout: JSON.stringify({ document, catalog }) });
    }
    if (!options.sopWorkspacePath) throw new Error('SOP workspace is unavailable.');
    const stdout = await executeV3GroupSopAuthoring(tokens, options.sopWorkspacePath, signal);
    return commandResult(request, { exitCode: 0, stdout });
  } catch (error) {
    if (signal?.aborted) throw error;
    return commandResult(request, {
      exitCode: download || error instanceof GroupMessageConfirmationRequired ? 1 : 2,
      stderr: error instanceof Error ? error.message : 'Invalid QoderWake file command',
    });
  }
}

export function createV3GroupMessagingSandbox(options: {
  sandbox: SandboxClient;
  /** The host sandbox image ships the Run-scoped qoderwake CLI. */
  shellBridge?: boolean;
  conversationId: string;
  onTodos?(command: V3GroupTodoCommand): Promise<V3GroupTodo | V3GroupTodo[]>;
  sopWorkspacePath?: string;
  onSopCatalog?(input?: V3SopTemplate): Promise<V3SopRelease[]>;
  onSopBindings?(groupHandle: string, input?: V3GroupSopReplacement): Promise<V3GroupSopBindings>;
  onSopMemberAvatar?(wakerId: string): Promise<string | undefined>;
  onDelivery(
    delivery: V3GroupMessageDelivery,
    toolCallId: string,
  ): Promise<{ message: V3Event; replayed: boolean }>;
  onList(afterSequence: number, limit: number): Promise<V3Event[]>;
  onAttachmentDownload?(
    input: V3GroupAttachmentDownload,
    signal?: AbortSignal,
  ): Promise<{ path: string; sizeBytes: number; attachmentId: string; messageId: string }>;
  onGoalGet(): Promise<V3ConversationGoalState | null>;
  onGoalMutate(input: V3GoalMutation): Promise<V3ConversationGoalState>;
}): SandboxClient {
  const client: SandboxClient = {
    create: (runId, workspaceId) => options.sandbox.create(runId, workspaceId),
    async exec(sandboxId, request, signal) {
      let tokens: string[] | undefined;
      try {
        tokens = commandTokens(request.command);
      } catch {
        // Expansions and compound commands require the real shell.
      }
      if (options.shellBridge && tokens?.[0] !== 'qoderwake') {
        return executeGroupShell(
          options.sandbox,
          sandboxId,
          request,
          (controlRequest, controlSignal) => client.exec(sandboxId, controlRequest, controlSignal),
          signal,
        );
      }
      if (tokens ? tokens[0] !== 'qoderwake' : !/^\s*qoderwake\b/u.test(request.command)) {
        return options.sandbox.exec(sandboxId, request, signal);
      }
      try {
        signal?.throwIfAborted();
        tokens ??= commandTokens(request.command);
        const deviceResult = await executeV3GroupDeviceCommand(request, options, signal);
        if (deviceResult) return deviceResult;
        if (tokens[1] === 'todo') {
          const command = parseGroupTodoTokens(tokens);
          if (!options.onTodos) throw new Error('Group todos are unavailable.');
          const result = await options.onTodos(command);
          return commandResult(request, { exitCode: 0, stdout: JSON.stringify(result) });
        }
        if (tokens[1] === 'group' && tokens[2] === 'sop') {
          const action = tokens[3];
          const groupHandle = tokens[4];
          if (!['list', 'set'].includes(action ?? '') || !groupHandle || groupHandle.startsWith('--'))
            throw new Error('Expected group sop list|set <group> [--sop <profile>@<version>] --json.');
          const selections: V3GroupSopSelection[] = [];
          let json = false;
          for (let index = 5; index < tokens.length; index++) {
            if (tokens[index] === '--json' && !json) json = true;
            else if (action === 'set' && tokens[index] === '--sop' && tokens[index + 1]) {
              const match = /^([^@\s]+)@([^@\s]+)$/u.exec(tokens[++index]!);
              if (!match) throw new Error('Expected --sop <profile>@<version>.');
              selections.push({ profileId: match[1]!, version: match[2]! });
            } else throw new Error('Unsupported group sop argument.');
          }
          if (action === 'set' && !selections.length)
            throw new Error('At least one --sop selection is required.');
          if (new Set(selections.map(({ profileId }) => profileId)).size !== selections.length)
            throw new Error('A SOP profile may only be bound once');
          if (!options.onSopBindings) throw new Error('Group SOP bindings are unavailable.');
          const current = await options.onSopBindings(groupHandle);
          signal?.throwIfAborted();
          const result =
            action === 'set'
              ? await options.onSopBindings(groupHandle, {
                  expectedVersion: current.group.revision,
                  selections,
                })
              : current;
          if (result.members && options.onSopMemberAvatar) {
            for (const member of result.members) {
              if (member.wakerRef.kind !== 'qoder/waker') continue;
              const avatar = await options.onSopMemberAvatar(member.wakerRef.id);
              if (avatar) member.avatar = avatar;
            }
          }
          return commandResult(request, {
            exitCode: 0,
            stdout: JSON.stringify(result),
          });
        }
        if (tokens[1] === 'sop' && tokens[2] === 'list') {
          if (!options.onSopCatalog) throw new Error('SOP catalog is unavailable.');
          if (tokens[2] === 'list') {
            if (tokens.length > 4 || (tokens.length === 4 && tokens[3] !== '--json'))
              throw new Error('Expected sop list --json.');
            return commandResult(request, {
              exitCode: 0,
              stdout: JSON.stringify(sopCatalogEntries(await options.onSopCatalog())),
            });
          }
        }
        if (tokens[1] === 'goal') {
          const command = parseV3GroupGoalCommand(request.command, options.conversationId);
          const result =
            command.kind === 'get'
              ? groupGoalJson(await options.onGoalGet())
              : { goal: groupGoalJson(await options.onGoalMutate(command.input)) };
          return commandResult(request, { exitCode: 0, stdout: JSON.stringify(result) });
        }
        if (tokens[1] === 'messages' && tokens[2] === 'send') {
          // Help is an option, never a substring of a message or an option value.
          if (groupSendHelpRequested(tokens))
            return commandResult(request, { exitCode: 0, stdout: V3_GROUP_MESSAGE_SEND_HELP });
          const next = parseV3GroupMessageSendCommand(request.command, {
            conversationId: options.conversationId,
          });
          const receipt = await options.onDelivery(
            {
              text: next.text,
              ...(next.filePath ? { filePath: next.filePath } : {}),
              mentionTarget: next.mentionTarget,
              ...(next.privateTargets ? { privateTargets: next.privateTargets } : {}),
            },
            request.toolCallId,
          );
          return messageSendResult(request, options.conversationId, next.json, receipt);
        }
        const input = parseV3GroupInboxCommand(request.command, options.conversationId);
        if (input.kind === 'claim' || input.kind === 'read')
          return commandResult(request, {
            exitCode: 1,
            stderr: '[qoderwake] the daemon manages claim/read for this Run',
          });
        const messages = await options.onList(input.afterSequence, input.limit);
        return commandResult(request, {
          exitCode: 0,
          stdout: JSON.stringify(
            messages.map((message) => canonicalGroupMessage(message, options.conversationId)),
          ),
        });
      } catch (error) {
        if (signal?.aborted) throw error;
        if (error instanceof V3GroupTodoNotFoundError)
          return commandResult(request, { exitCode: 1, stderr: `[qoderwake] ${error.message}` });
        return commandResult(request, {
          exitCode:
            error instanceof GroupMessageConfirmationRequired ||
            tokens?.slice(1, 4).join(' ') === 'messages attachment download' ||
            tokens?.[1] === 'goal'
              ? 1
              : 2,
          stderr: error instanceof Error ? error.message : 'Invalid QoderWake message command',
        });
      }
    },
    ...(options.sandbox.fileOperation
      ? {
          fileOperation: (sandboxId, request, signal) => options.sandbox.fileOperation!(sandboxId, request, signal),
        }
      : {}),
    destroy: (sandboxId) => options.sandbox.destroy(sandboxId),
  };
  return client;
}
