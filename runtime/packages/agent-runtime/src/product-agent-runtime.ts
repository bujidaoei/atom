import { mkdir, rename, stat } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { v3SkillReferenceSource, v3SkillReferences } from '../../product-contracts/src/v3-skill-reference.ts';
import { resolveV3SkillReferencePrompt } from './v3-skill-references.ts';
import { recoveredRunUsage } from './recovered-run-usage.ts';
import { withSandbox, validateSandboxScope, type ExternalSandboxScope } from './sandbox-lifecycle.ts';

import type {
  AgentRunRequest,
  AgentRunReadableAttachment,
  ApprovalAdapter,
  ModelUsage,
  ProductEventSink,
  RunEventType,
  SandboxClient,
} from '../../product-contracts/src/index.ts';
import { redactProviderCorrelation } from '../../product-contracts/src/provider-correlation.ts';
import { ENTERPRISE_AI_GATEWAY_PROVIDER } from '../../product-contracts/src/server-configuration.ts';
import {
  extractAssistantText,
  accumulateModelUsage,
  extractModelUsage,
  normalizePiEvents,
  type NormalizedPiEvent,
} from './event-normalizer.ts';
import type { ToolPolicyEvaluator, ToolPolicyEvidence } from './tool-policy.ts';
import type { ToolDefinition } from './pi-runtime-types.ts';
import {
  createProductPiReadTool,
  createPolicyBoundPiEditTool,
  createPolicyBoundPiWriteTool,
  createWorkspaceTools,
  readIntegrityBoundResource,
  type ProductSkillDirectory,
} from './workspace-tools.ts';
import type { EnterpriseAiGatewayConfiguration } from './enterprise-ai-gateway.ts';
import {
  createImageGenTool,
  IMAGE_ARTIFACT_GUIDANCE,
  PRIVATE_WAKER_IMAGE_GUIDANCE,
} from './image-gen-tool.ts';
import {
  createPresentFilesTool,
  presentLinkedSessionFiles,
  SESSION_ARTIFACTS_OUTPUT_STYLE,
  type SessionArtifactSink,
} from './session-artifacts.ts';
import { trackSessionFileChanges } from './session-file-changes.ts';
import { GROUP_SHARED_DIRECTORY_GUIDANCE, GROUP_SHARED_DIRECTORY_NAME } from './group-shared-artifacts.ts';
import type { V3GroupInboxPage } from '../../product-contracts/src/v3-ports.ts';
import type { V3GroupTodo } from '../../product-contracts/src/v3-group-todo.ts';
import type { V3ConversationGoalState } from '../../product-contracts/src/v3-conversation-goal.ts';
import { formatV3GroupInboxPage } from './v3-group-inbox.ts';
import { createPluginAgentTool } from './plugin-agent-tool.ts';

export interface ProductAgentRuntimeOptions {
  aiGateway: EnterpriseAiGatewayConfiguration;
  agentDir: string;
  sandbox: SandboxClient;
  /** Trusted outer lifecycle owns acquisition/checkpoint/release across recovery. */
  sandboxScope?: ExternalSandboxScope;
  approvals: ApprovalAdapter;
  events: ProductEventSink;
  enableTools?: boolean;
  enableImageGeneration?: boolean;
  toolPolicy?: ToolPolicyEvaluator;
  onPolicyDecision?: (evidence: ToolPolicyEvidence) => Promise<void>;
  systemPrompt?: string;
  externalTools?: ToolDefinition[];
  /** Product-specific capability boundary; omitted preserves all workspace tools. */
  workspaceToolNames?: readonly string[];
  skillDirectories?: readonly ProductSkillDirectory[];
  resolveReadableAttachments?(): readonly AgentRunReadableAttachment[];
  /**
   * Session artifact persistence. Private conversations present files with
   * `present_files`; Group Runs (with `groupInbox`) deliver through message
   * attachments and the `shared/` finalization, so they only record file changes.
   */
  artifacts?: SessionArtifactSink;
  /** The Group workspace mounts the conversation shared directory at `shared/`. */
  groupSharedDirectory?: boolean;
  groupInbox?: {
    conversationId: string;
    initial: V3GroupInboxPage;
    next(phase: 'arrivals' | 'complete', signal: AbortSignal): Promise<V3GroupInboxPage>;
    snapshot(signal: AbortSignal): Promise<{ todos: V3GroupTodo[]; goal: V3ConversationGoalState | null }>;
  };
}

export interface ProductAgentRunResult {
  resultText: string;
  sessionFile: string | undefined;
  usage: ModelUsage | null;
  providerCorrelationId: string | null;
}

const SYSTEM_PROMPT = `You are QoderWake, an enterprise-grade general AI agent.
Plan before acting. Use read for explicitly attached files; use read_file, glob, and grep for workspace inspection. Use write for new files or complete rewrites, edit for targeted replacements in existing files, and sandbox_exec for shell commands, builds, and verification. Never claim host access.
Keep changes inside the assigned workspace, explain risky operations, and report concrete results.`;

const RECOVERY_PROMPT = `Continue the unfinished request after an Agent Host restart.
Resume the last user request directly and treat its wording and constraints as
authoritative. Use the durable session context as supporting context only.
Do not replace the original user's request, constraints, output format, or required
markers with a generic workspace inspection or a progress status update. Do not
restart completed work or repeat the original request as a new task. Continue from
the earliest incomplete step and provide one final answer.`;

const STREAM_BATCH_INTERVAL_MS = 40;
const STREAM_BATCH_MAX_CHARACTERS = 128;
type PiRuntimeLoader = typeof import('./pi-runtime-loader.mjs');
let piRuntimeLoader: Promise<PiRuntimeLoader> | undefined;
const SUPPORTED_AGENT_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
const MAX_AGENT_IMAGE_BYTES = 50 * 1024 * 1024;

function loadPiRuntime(): Promise<PiRuntimeLoader> {
  piRuntimeLoader ??= import('./pi-runtime-loader.mjs');
  return piRuntimeLoader;
}

function productAgentImages(images: AgentRunRequest['images']) {
  if (!images?.length) return undefined;
  if (images.length > 20) throw new Error('Agent image attachment count exceeds 20');
  let totalBytes = 0;
  return images.map((image) => {
    const mimeType = image.mimeType.trim().toLowerCase();
    if (!SUPPORTED_AGENT_IMAGE_TYPES.has(mimeType)) {
      throw new Error(`Agent image type is unsupported: ${image.mimeType}`);
    }
    const bytes = Buffer.from(image.data, 'base64');
    if (!bytes.length || bytes.byteLength > MAX_AGENT_IMAGE_BYTES) {
      throw new Error('Agent image attachment size is invalid');
    }
    totalBytes += bytes.byteLength;
    if (totalBytes > 250 * 1024 * 1024) throw new Error('Agent image attachments exceed 250 MB');
    return { type: 'image' as const, data: image.data, mimeType };
  });
}

export class ProductAgentRuntime {
  private readonly options: ProductAgentRuntimeOptions;

  constructor(options: ProductAgentRuntimeOptions) {
    this.options = { ...options, sandboxScope: options.sandboxScope ? Object.freeze({ ...options.sandboxScope }) : undefined };
  }

  async run(request: AgentRunRequest): Promise<ProductAgentRunResult> {
    validateSandboxScope(this.options.sandboxScope, request.runId);
    await mkdir(request.workspacePath, { recursive: true });
    await mkdir(dirname(request.sessionPath), { recursive: true });
    await mkdir(this.options.agentDir, { recursive: true });
    const {
      createAgentSessionRuntime,
      createAgentSessionFromServices,
      createAgentSessionServices,
      createEditToolDefinition,
      createReadToolDefinition,
      detectSupportedImageMimeType,
      createWriteToolDefinition,
      ModelRuntime,
      SessionManager,
    } = await loadPiRuntime();

    const existingSession = await stat(request.sessionPath).catch((error: NodeJS.ErrnoException) => {
      if (error.code === 'ENOENT') return undefined;
      throw error;
    });
    if (!existingSession && request.parentSessionPath) {
      const inherited = SessionManager.forkFrom(
        request.parentSessionPath,
        request.workspacePath,
        dirname(request.sessionPath),
      );
      const inheritedPath = inherited.getSessionFile();
      if (!inheritedPath) throw new Error('Pi did not persist the inherited conversation session');
      await rename(inheritedPath, request.sessionPath);
    }
    // A fresh fork contains the previous turn's completed assistant message. It
    // must never be mistaken for this Run's already-completed recovery result.
    const sessionManager = SessionManager.open(
      request.sessionPath,
      dirname(request.sessionPath),
      request.workspacePath,
    );
    const branch = sessionManager.getBranch();
    const runBoundary = branch.findLastIndex(
      (entry) =>
        entry.type === 'custom' &&
        entry.customType === 'workdude.run' &&
        (entry.data as { runId?: string } | undefined)?.runId === request.runId,
    );
    // Shared remote sessions contain multiple Runs. A reclaimed lease alone is
    // not proof that this Run started, nor may later turns supply its result.
    const recoveringSession = Boolean(request.recovery && existingSession && runBoundary >= 0);
    const nextBoundary = branch.findIndex(
      (entry, index) => index > runBoundary && entry.type === 'custom' && entry.customType === 'workdude.run',
    );
    const runBranch =
      runBoundary >= 0 ? branch.slice(runBoundary + 1, nextBoundary >= 0 ? nextBoundary : undefined) : [];
    if (runBoundary < 0) {
      sessionManager.appendCustomEntry('workdude.run', { runId: request.runId });
    }
    await this.options.events.emit('run.session', {
      sessionId: sessionManager.getSessionId(),
      ...(this.options.groupInbox
        ? {
            input: this.options.groupInbox.initial.messages
              .map(
                (message) =>
                  `[seq=${message.sequence}] [id=${message.id}]\n${String(message.payload.content ?? '')}`,
              )
              .join('\n\n'),
          }
        : {}),
    });
    const lastMessage = [...runBranch].reverse().find((entry) => entry.type === 'message');
    if (
      recoveringSession &&
      !this.options.groupInbox &&
      lastMessage?.type === 'message' &&
      lastMessage.message.role === 'assistant' &&
      lastMessage.message.stopReason === 'stop'
    ) {
      const responseId = lastMessage.message.responseId;
      return {
        resultText: extractAssistantText(lastMessage.message),
        sessionFile: sessionManager.getSessionFile(),
        usage: recoveredRunUsage(runBranch),
        providerCorrelationId: typeof responseId === 'string' ? redactProviderCorrelation(responseId) : null,
      };
    }

    const interruptedAssistantText =
      recoveringSession && lastMessage?.type === 'message' && lastMessage.message.role === 'assistant'
        ? extractAssistantText(lastMessage.message)
        : '';
    const enableTools = this.options.enableTools !== false;
    return withSandbox(this.options.sandbox, request.runId, enableTools, async (sandboxId) => {
      const modelRuntime = await ModelRuntime.create({
        modelsPath: null,
        refreshOnCreate: false,
        allowModelNetwork: false,
      });
      const modelId = request.model?.trim() || this.options.aiGateway.model;
      modelRuntime.registerProvider(ENTERPRISE_AI_GATEWAY_PROVIDER, {
        name: 'Enterprise AI Gateway',
        baseUrl: this.options.aiGateway.baseUrl,
        apiKey: this.options.aiGateway.masterKey,
        headers: this.options.aiGateway.requestHeaders,
        api: 'openai-completions',
        authHeader: true,
        models: [
          {
            id: modelId,
            name: modelId,
            api: 'openai-completions',
            reasoning: false,
            input: ['text', 'image'],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            contextWindow: 128_000,
            maxTokens: 8_192,
          },
        ],
      });
      await modelRuntime.setRuntimeApiKey(ENTERPRISE_AI_GATEWAY_PROVIDER, this.options.aiGateway.masterKey);
      const model = modelRuntime.getModel(ENTERPRISE_AI_GATEWAY_PROVIDER, modelId);
      if (!model) {
        throw new Error(`Configured AI gateway model not found: ${modelId}`);
      }

      const workspaceToolOptions = sandboxId
        ? {
            runId: request.runId,
            sandboxId,
            workspacePath: request.workspacePath,
            sandbox: this.options.sandbox,
            approvals: this.options.approvals,
            ...(this.options.toolPolicy ? { policy: this.options.toolPolicy } : {}),
            ...(this.options.onPolicyDecision ? { onPolicyDecision: this.options.onPolicyDecision } : {}),
          }
        : undefined;
      const productReadTools =
        workspaceToolOptions ||
        this.options.resolveReadableAttachments ||
        request.readableAttachments?.length ||
        this.options.skillDirectories?.length
          ? [
              createProductPiReadTool(
                {
                  workspacePath: request.workspacePath,
                  ...(workspaceToolOptions ? { workspace: workspaceToolOptions } : {}),
                  detectImageMimeType: detectSupportedImageMimeType,
                  attachments: this.options.resolveReadableAttachments ?? request.readableAttachments ?? [],
                  skillDirectories: this.options.skillDirectories ?? [],
                },
                createReadToolDefinition,
              ),
            ]
          : [];
      const allSandboxTools = workspaceToolOptions
        ? [
            ...createWorkspaceTools(workspaceToolOptions, productReadTools[0]),
            createPolicyBoundPiWriteTool(workspaceToolOptions, createWriteToolDefinition),
            createPolicyBoundPiEditTool(workspaceToolOptions, createEditToolDefinition),
          ]
        : [];
      const sandboxTools = this.options.workspaceToolNames
        ? allSandboxTools.filter(tool => this.options.workspaceToolNames!.includes(tool.name))
        : allSandboxTools;
      const workspaceTools = this.options.artifacts
        ? trackSessionFileChanges(sandboxTools, {
            workspacePath: request.workspacePath,
            sink: this.options.artifacts,
            ...(this.options.groupSharedDirectory ? { ignoredDirectories: [GROUP_SHARED_DIRECTORY_NAME] } : {}),
          })
        : sandboxTools;
      const imageTools = this.options.enableImageGeneration
        ? [
            createImageGenTool({
              gateway: this.options.aiGateway,
              runId: request.runId,
              workspacePath: request.workspacePath,
              approvals: this.options.approvals,
              ...(this.options.toolPolicy ? { policy: this.options.toolPolicy } : {}),
              ...(this.options.onPolicyDecision ? { onPolicyDecision: this.options.onPolicyDecision } : {}),
              ...(this.options.artifacts ? { artifacts: this.options.artifacts } : {}),
            }),
          ]
        : [];
      const presentationArtifacts = this.options.groupInbox ? undefined : this.options.artifacts;
      const artifactTools = presentationArtifacts
        ? [createPresentFilesTool({ workspacePath: request.workspacePath, sink: presentationArtifacts })]
        : [];
      const basePrompt = this.options.enableImageGeneration
        ? `${this.options.systemPrompt ?? SYSTEM_PROMPT}\n${PRIVATE_WAKER_IMAGE_GUIDANCE}`
        : (this.options.systemPrompt ?? SYSTEM_PROMPT);
      const systemPrompt = presentationArtifacts
        ? `${basePrompt}\n${this.options.enableImageGeneration ? `${IMAGE_ARTIFACT_GUIDANCE}\n` : ''}\n${SESSION_ARTIFACTS_OUTPUT_STYLE}`
        : this.options.groupSharedDirectory
          ? `${basePrompt}\n\n${GROUP_SHARED_DIRECTORY_GUIDANCE}`
          : basePrompt;
      const customTools = [
        ...imageTools,
        ...artifactTools,
        ...workspaceTools,
        ...productReadTools,
        ...(this.options.externalTools ?? []),
      ];
      let usage: ModelUsage | null =
        recoveringSession && !this.options.groupInbox ? recoveredRunUsage(runBranch) : null;
      const skillManifests = (this.options.skillDirectories ?? []).flatMap(({ files, commandPaths }) =>
        files.filter(({ path }) => basename(path) === 'SKILL.md' || commandPaths?.includes(path)),
      );
      for (const directory of this.options.skillDirectories ?? []) {
        for (const path of [...(directory.skillPaths ?? []), ...(directory.commandPaths ?? [])]) {
          if (!directory.files.some((file) => file.path === path))
            throw new Error('Plugin resource declaration is outside its verified inventory');
        }
      }
      for (const manifest of skillManifests) await readIntegrityBoundResource(manifest);
      const pluginAgent = await createPluginAgentTool({
        directories: this.options.skillDirectories ?? [],
        session: {
          cwd: request.workspacePath,
          agentDir: this.options.agentDir,
          modelRuntime,
          model,
          tools: customTools,
          requestTimeoutMs: this.options.aiGateway.requestTimeoutMs,
        },
        parentSystemPrompt: systemPrompt,
        onComplete: async (result) => {
          usage = accumulateModelUsage(usage, result.usage);
          if (usage) enqueueEvent('usage.updated', { usage });
        },
      });
      if (pluginAgent) customTools.push(pluginAgent);

      let loadedSkills: ReadonlyArray<{ name: string; filePath: string }> = [];
      const runtime = await createAgentSessionRuntime(
        async ({ cwd, agentDir, sessionManager: nextSessionManager, sessionStartEvent }) => {
          const services = await createAgentSessionServices({
            cwd,
            agentDir,
            modelRuntime,
            resourceLoaderOptions: {
              noExtensions: true,
              noSkills: true,
              additionalSkillPaths: (this.options.skillDirectories ?? [])
                .filter(({ pluginName }) => pluginName === undefined)
                .flatMap(({ files }) =>
                  files.filter(({ path }) => basename(path) === 'SKILL.md').map(({ path }) => path),
                ),
              pluginSkills: (this.options.skillDirectories ?? [])
                .filter(({ pluginName }) => pluginName !== undefined)
                .map(({ pluginName, files, skillPaths }) => ({
                  namespace: pluginName,
                  paths:
                    skillPaths ??
                    files.filter(({ path }) => basename(path) === 'SKILL.md').map(({ path }) => path),
                })),
              pluginCommands: (this.options.skillDirectories ?? [])
                .filter(({ pluginName, commandPaths }) => pluginName && commandPaths?.length)
                .map(({ pluginName, commandPaths }) => ({ namespace: pluginName, paths: commandPaths })),
              noPromptTemplates: true,
              noThemes: true,
              noContextFiles: true,
              systemPrompt,
            },
          });
          services.settingsManager.applyOverrides({ httpIdleTimeoutMs: this.options.aiGateway.requestTimeoutMs,
            retry: { provider: { timeoutMs: this.options.aiGateway.requestTimeoutMs } } });
          loadedSkills = services.getSkills();
          const created = await createAgentSessionFromServices({
            services,
            sessionManager: nextSessionManager,
            ...(sessionStartEvent ? { sessionStartEvent } : {}),
            model,
            thinkingLevel: 'off',
            tools: customTools.map(({ name }) => name),
            customTools,
          });
          return { ...created, services, diagnostics: services.diagnostics };
        },
        {
          cwd: request.workspacePath,
          agentDir: this.options.agentDir,
          sessionManager,
        },
      );

      let resultText = '';
      let providerCorrelationId: string | null = null;
      let terminalAssistantError: Error | undefined;
      let terminalAssistantTruncated = false;
      let eventDrain = Promise.resolve();
      let eventError: Error | undefined;
      let abortPromise: Promise<void> | undefined;
      const abort = () => {
        // Pi abort waits for idle. Never await it inside the event drain: completion hooks
        // may themselves be waiting for that drain before the session can become idle.
        abortPromise ??= runtime.session.abort().catch((cause: unknown) => {
          eventError ??= cause instanceof Error ? cause : new Error(String(cause));
        });
      };
      let bufferedDelta: { type: 'thinking.delta' | 'message.delta'; delta: string } | undefined;
      let deltaFlushTimer: ReturnType<typeof setTimeout> | undefined;
      const enqueueEvent = (type: RunEventType, payload: Record<string, unknown>) => {
        eventDrain = eventDrain
          .then(() => {
            if (eventError) return;
            // Pi cancels its transport, but previously queued text may still be
            // waiting for persistence. Do not extend a cancelled partial reply.
            if (
              request.signal?.aborted &&
              (type === 'message.delta' || type === 'thinking.delta' || type === 'message.completed')
            )
              return;
            return this.options.events.emit(type, payload);
          })
          .catch((cause: unknown) => {
            eventError ??= cause instanceof Error ? cause : new Error(String(cause));
            abort();
          });
      };
      const flushBufferedDelta = () => {
        if (deltaFlushTimer) clearTimeout(deltaFlushTimer);
        deltaFlushTimer = undefined;
        const buffered = bufferedDelta;
        bufferedDelta = undefined;
        if (buffered) enqueueEvent(buffered.type, { delta: buffered.delta });
      };
      const enqueueNormalizedEvent = (event: NormalizedPiEvent) => {
        if (event.type === 'thinking.delta' || event.type === 'message.delta') {
          const delta = typeof event.payload.delta === 'string' ? event.payload.delta : '';
          if (!delta) return;
          if (bufferedDelta && bufferedDelta.type !== event.type) flushBufferedDelta();
          bufferedDelta = {
            type: event.type,
            delta: `${bufferedDelta?.delta ?? ''}${delta}`,
          };
          if (bufferedDelta.delta.length >= STREAM_BATCH_MAX_CHARACTERS) {
            flushBufferedDelta();
          } else if (!deltaFlushTimer) {
            deltaFlushTimer = setTimeout(flushBufferedDelta, STREAM_BATCH_INTERVAL_MS);
          }
          return;
        }
        flushBufferedDelta();
        enqueueEvent(event.type, event.payload);
      };
      const unsubscribe = runtime.session.subscribe((event) => {
        if (event.type === 'message_end' && 'role' in event.message && event.message.role === 'assistant') {
          // Pi owns retry/recovery. Only the latest assistant response is terminal;
          // a recovered response must replace an earlier transient transport error.
          terminalAssistantError = undefined;
          terminalAssistantTruncated = event.message.stopReason === 'length';
          usage = accumulateModelUsage(usage, extractModelUsage(event.message));
          const responseId = (event.message as { responseId?: unknown }).responseId;
          if (typeof responseId === 'string') {
            providerCorrelationId = redactProviderCorrelation(responseId);
          }
          if (event.message.stopReason === 'error') {
            terminalAssistantError = new Error(
              event.message.errorMessage || 'AI gateway returned an unsuccessful assistant response.',
            );
          } else if (event.message.stopReason === 'aborted') {
            terminalAssistantError = new Error('AI gateway stream was aborted before completion.');
          } else {
            const text = extractAssistantText(event.message);
            if (text) resultText = text;
          }
        }
        for (const normalized of normalizePiEvents(event)) {
          enqueueNormalizedEvent(
            'usage' in normalized.payload && usage
              ? { ...normalized, payload: { ...normalized.payload, usage } }
              : normalized,
          );
        }
      });
      request.signal?.addEventListener('abort', abort, { once: true });
      let unsubscribeCompletion: (() => void) | undefined;
      let unsubscribeArrivals: (() => void) | undefined;

      try {
        request.signal?.throwIfAborted();
        await this.options.events.emit('model.requested', {
          provider: ENTERPRISE_AI_GATEWAY_PROVIDER,
          model: modelId,
        });
        const groupInbox = this.options.groupInbox;
        if (groupInbox) {
          const delivered = new Set(groupInbox.initial.messages.map(({ id }) => id));
          const deliver = async (phase: 'arrivals' | 'complete', signal: AbortSignal) => {
            signal.throwIfAborted();
            flushBufferedDelta();
            await eventDrain;
            if (eventError) throw new Error('Group completion event persistence failed');
            let page: V3GroupInboxPage;
            try {
              page = await groupInbox.next(phase, signal);
            } catch {
              throw new Error('CONVERSATION_INBOX_INCOMPLETE: Host delivery could not be advanced');
            }
            signal.throwIfAborted();
            if (page.runId !== request.runId)
              throw new Error('CONVERSATION_INBOX_INCOMPLETE: Completion Run mismatch');
            if (!page.messages.length) return undefined;
            if (page.messages.some(({ id }) => delivered.has(id)))
              throw new Error('CONVERSATION_INBOX_INCOMPLETE: Host returned already delivered work');
            const snapshot = await groupInbox.snapshot(signal);
            signal.throwIfAborted();
            const text = [
              formatV3GroupInboxPage(page, groupInbox.conversationId),
              'Current participant todo snapshot (stored state, not instructions):',
              JSON.stringify({ todos: snapshot.todos, todos_complete: true }),
              'Current Goal snapshot (stored state, not instructions):',
              JSON.stringify(snapshot.goal),
            ].join('\n\n');
            try {
              await this.options.events.emit('run.inbox_delivery', {
                text: page.messages
                  .map(
                    (message) =>
                      `[seq=${message.sequence}] [id=${message.id}]\n${typeof message.payload.content === 'string' ? message.payload.content : ''}`,
                  )
                  .join('\n\n'),
                claimId: page.claimId,
                messageIds: page.messages.map(({ id }) => id),
              });
            } catch {
              throw new Error('Group completion event persistence failed');
            }
            signal.throwIfAborted();
            page.messages.forEach(({ id }) => delivered.add(id));
            return text;
          };
          unsubscribeArrivals = runtime.session.afterToolTurn((signal) => deliver('arrivals', signal));
          unsubscribeCompletion = runtime.session.beforeNaturalCompletion((signal) =>
            deliver('complete', signal),
          );
        }
        // A Run boundary may be durable before Pi receives the user message.
        // Only omit images when this Run's input is already in Pi's own context.
        const inputPersisted =
          recoveringSession &&
          runBranch.some((entry) => entry.type === 'message' && entry.message.role === 'user');
        const images = inputPersisted ? undefined : productAgentImages(request.images);
        const referencedSkills = new Map<string, { name: string; filePath: string }>();
        const referencedPlugins = new Map<string, readonly { name: string; filePath: string }[]>();
        for (const directory of this.options.skillDirectories ?? []) {
          const matches = loadedSkills.filter((candidate) =>
            directory.files.some((file) => resolve(file.path) === resolve(candidate.filePath)),
          );
          if (directory.versionId && matches[0]) {
            referencedSkills.set(v3SkillReferenceSource(directory.versionId), matches[0]);
          }
          if (directory.pluginName) {
            const commands = (directory.commandPaths ?? []).map((filePath) => ({
              name: `${directory.pluginName}:${basename(filePath, '.md')}`,
              filePath,
            }));
            if (matches.length || commands.length)
              referencedPlugins.set(directory.pluginName, [...matches, ...commands]);
          }
        }
        const userPrompt = resolveV3SkillReferencePrompt(request.prompt, referencedSkills, referencedPlugins);
        const prompt =
          recoveringSession && runBranch.length > 0
            ? `${RECOVERY_PROMPT}\n\nOriginal user request to continue verbatim:\n${userPrompt}${
                interruptedAssistantText
                  ? `\n\nPartial assistant output preserved before interruption:\n${interruptedAssistantText}`
                  : ''
              }`
            : userPrompt;
        const references = v3SkillReferences(request.prompt);
        if (references.length) {
          await this.options.events.emit('run.session', {
            sessionId: sessionManager.getSessionId(),
            skillReferences: references.map(({ sourceId }) => ({
              sourceId,
              name: referencedSkills.get(sourceId)!.name,
            })),
          });
        }
        for (const manifest of skillManifests) await readIntegrityBoundResource(manifest);
        await runtime.session.prompt(prompt, images ? { images } : undefined);
        request.signal?.throwIfAborted();
        flushBufferedDelta();
        await eventDrain;
        if (eventError) throw eventError;
        if (terminalAssistantError) throw terminalAssistantError;
        if (terminalAssistantTruncated) throw new Error('AI gateway response was truncated before completion.');
        if (presentationArtifacts && resultText) {
          await presentLinkedSessionFiles({
            markdown: resultText,
            workspacePath: request.workspacePath,
            sink: presentationArtifacts,
          });
        }
        return {
          resultText,
          sessionFile: runtime.session.sessionManager.getSessionFile(),
          usage,
          providerCorrelationId,
        };
      } finally {
        flushBufferedDelta();
        await eventDrain;
        await abortPromise;
        request.signal?.removeEventListener('abort', abort);
        unsubscribe();
        unsubscribeCompletion?.();
        unsubscribeArrivals?.();
        await runtime.dispose();
      }
    }, this.options.sandboxScope);
  }
}

export function productAgentDir(dataDir: string): string {
  return join(dataDir, 'pi-agent');
}
