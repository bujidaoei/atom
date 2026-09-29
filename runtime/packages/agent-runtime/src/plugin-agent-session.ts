import { randomUUID } from 'node:crypto';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import type { ModelUsage } from '../../product-contracts/src/index.ts';
import type { PiModelRuntimeInstance } from './pi-runtime-loader.mjs';
import type { PiAgentSessionEvent, ToolDefinition } from './pi-runtime-types.ts';
import { accumulateModelUsage, extractAssistantText, extractModelUsage } from './event-normalizer.ts';

export interface PluginAgentSessionOptions {
  cwd: string;
  agentDir: string;
  /** The parent's already authorized gateway runtime/model, never a package hint. */
  modelRuntime: PiModelRuntimeInstance;
  model: unknown;
  systemPrompt: string;
  task: string;
  /** Preselected, policy-bound parent tools. No ambient or recursive discovery. */
  tools: readonly ToolDefinition[];
  requestTimeoutMs: number;
  signal?: AbortSignal;
  onEvent?(event: PiAgentSessionEvent): Promise<void>;
}

export interface PluginAgentSessionResult {
  status: 'completed' | 'failed' | 'cancelled';
  text: string;
  usage: ModelUsage | null;
  sessionFile: string | undefined;
  error?: string;
}

/**
 * Independent native Pi session, following Pi 0.86.1's subagent example via its
 * public SDK instead of spawning a CLI with ambient provider/tool discovery.
 * Product-only package orchestration; Pi owns the model/tool loop and abort.
 */
export async function runPluginAgentSession(
  options: PluginAgentSessionOptions,
): Promise<PluginAgentSessionResult> {
  options.signal?.throwIfAborted();
  const {
    SessionManager,
    createAgentSessionRuntime,
    createAgentSessionServices,
    createAgentSessionFromServices,
  } = await import('./pi-runtime-loader.mjs');
  options.signal?.throwIfAborted();
  const sessionDirectory = join(options.agentDir, 'plugin-sessions', randomUUID());
  await mkdir(sessionDirectory, { recursive: true });
  const manager = SessionManager.open(join(sessionDirectory, 'session.jsonl'), sessionDirectory, options.cwd);
  const runtime = await createAgentSessionRuntime(
    async ({ cwd, agentDir, sessionManager, sessionStartEvent }) => {
      const services = await createAgentSessionServices({
        cwd,
        agentDir,
        modelRuntime: options.modelRuntime,
        resourceLoaderOptions: {
          noExtensions: true,
          noSkills: true,
          noPromptTemplates: true,
          noThemes: true,
          noContextFiles: true,
          systemPrompt: options.systemPrompt,
        },
      });
      services.settingsManager.setHttpIdleTimeoutMs(options.requestTimeoutMs);
      const created = await createAgentSessionFromServices({
        services,
        sessionManager,
        ...(sessionStartEvent ? { sessionStartEvent } : {}),
        model: options.model,
        thinkingLevel: 'off',
        tools: options.tools.map(({ name }) => name),
        customTools: [...options.tools],
      });
      return { ...created, services, diagnostics: services.diagnostics };
    },
    { cwd: options.cwd, agentDir: sessionDirectory, sessionManager: manager },
  );

  let text = '';
  let usage: ModelUsage | null = null;
  let finalStopReason: string | undefined;
  let finalError: string | undefined;
  let eventDeliveryFailed = false;
  let drain = Promise.resolve();
  let abortPromise: Promise<void> | undefined;
  const abort = () => {
    abortPromise ??= runtime.session.abort().catch(() => {
      eventDeliveryFailed = true;
    });
  };
  const unsubscribe = runtime.session.subscribe((event) => {
    if (event.type === 'message_end' && event.message.role === 'assistant') {
      finalStopReason = event.message.stopReason;
      finalError = event.message.errorMessage;
      text = extractAssistantText(event.message);
      usage = accumulateModelUsage(usage, extractModelUsage(event.message));
    }
    drain = drain.then(async () => {
      if (eventDeliveryFailed) return;
      try {
        await options.onEvent?.(event);
      } catch {
        eventDeliveryFailed = true;
        // Native abort waits for idle. Never await it inside the event drain.
        abort();
      }
    });
  });
  options.signal?.addEventListener('abort', abort, { once: true });
  try {
    options.signal?.throwIfAborted();
    await runtime.session.prompt(options.task);
    await drain;
    const cancelled = options.signal?.aborted;
    const failed = eventDeliveryFailed || finalStopReason !== 'stop';
    return {
      status: cancelled ? 'cancelled' : failed ? 'failed' : 'completed',
      text,
      usage,
      sessionFile: manager.getSessionFile(),
      ...(cancelled
        ? { error: 'Plugin Agent execution was cancelled' }
        : failed
          ? {
              error: eventDeliveryFailed
                ? 'Plugin Agent event delivery failed'
                : finalError || `Plugin Agent stopped: ${finalStopReason ?? 'no response'}`,
            }
          : {}),
    };
  } catch (error) {
    await drain;
    return {
      status: options.signal?.aborted ? 'cancelled' : 'failed',
      text,
      usage,
      sessionFile: manager.getSessionFile(),
      error: error instanceof Error ? error.message : 'Plugin Agent execution failed',
    };
  } finally {
    options.signal?.removeEventListener('abort', abort);
    unsubscribe();
    await abortPromise;
    await runtime.dispose();
  }
}
