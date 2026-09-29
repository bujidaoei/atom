import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Type } from 'typebox';
import { expect, it } from 'vitest';
import { startGatewayLoopback, type GatewayLoopbackOptions } from '../../../tests/fixtures/v3/providers.ts';
import { runPluginAgentSession } from '../src/plugin-agent-session.ts';
import type { PiAgentSessionEvent, ToolDefinition } from '../src/pi-runtime-types.ts';

async function fixture(options: GatewayLoopbackOptions = {}) {
  const root = await mkdtemp(join(tmpdir(), 'workdude-plugin-child-'));
  const gateway = await startGatewayLoopback(options);
  const { ModelRuntime } = await import('../src/pi-runtime-loader.mjs');
  const modelRuntime = await ModelRuntime.create({
    modelsPath: null,
    refreshOnCreate: false,
    allowModelNetwork: false,
  });
  modelRuntime.registerProvider('enterprise-gateway', {
    baseUrl: gateway.baseUrl,
    apiKey: 'synthetic-key',
    api: 'openai-completions',
    authHeader: true,
    models: [
      {
        id: 'authorized-model',
        name: 'authorized-model',
        api: 'openai-completions',
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens: 8192,
      },
    ],
  });
  await modelRuntime.setRuntimeApiKey('enterprise-gateway', 'synthetic-key');
  const cwd = join(root, 'workspace');
  await mkdir(cwd);
  await writeFile(join(cwd, 'AGENTS.md'), 'AMBIENT-INSTRUCTIONS-MUST-NOT-LOAD');
  return {
    gateway,
    base: {
      cwd,
      agentDir: join(root, 'agent'),
      modelRuntime,
      model: modelRuntime.getModel('enterprise-gateway', 'authorized-model'),
      systemPrompt: 'Use only the supplied public documentation tool.',
      task: 'Look up a synthetic public document.',
      tools: [] as ToolDefinition[],
      requestTimeoutMs: 5000,
    },
    close: async () => {
      await gateway.close();
      await rm(root, { recursive: true, force: true });
    },
  };
}

it('runs the native Pi tool loop with only inherited tools and a distinct child transcript', async () => {
  const f = await fixture({
    externalToolCall: { name: 'query_docs', arguments: {}, finalContent: 'CHILD-DOCUMENT-RESULT' },
    toolCallUsage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
  });
  let calls = 0;
  const events: PiAgentSessionEvent[] = [];
  const tool: ToolDefinition = {
    name: 'query_docs',
    label: 'Query docs',
    description: 'Fetch a controlled document.',
    parameters: Type.Object({}),
    execute: async () => {
      calls++;
      return { content: [{ type: 'text', text: 'REAL-TOOL-RESULT' }] };
    },
  };
  try {
    const first = await runPluginAgentSession({
      ...f.base,
      tools: [tool],
      onEvent: async (event) => {
        events.push(event);
      },
    });
    const second = await runPluginAgentSession({ ...f.base, tools: [tool] });
    expect(first.status).toBe('completed');
    expect(first.text).toBe('CHILD-DOCUMENT-RESULT');
    expect(first.usage).toMatchObject({ inputTokens: 10, outputTokens: 7, totalTokens: 17 });
    expect(second.sessionFile).not.toBe(first.sessionFile);
    expect(calls).toBe(2);
    expect(
      events.some((event) => event.type === 'tool_execution_start' && event.toolName === 'query_docs'),
    ).toBe(true);
    const payloads = f.gateway.requests.map((request) => JSON.parse(request.body));
    expect(payloads).toHaveLength(4);
    for (const payload of payloads) {
      expect(payload.model).toBe('authorized-model');
      expect(payload.tools.map((tool: { function: { name: string } }) => tool.function.name)).toEqual([
        'query_docs',
      ]);
      expect(JSON.stringify(payload.messages)).not.toContain('AMBIENT-INSTRUCTIONS-MUST-NOT-LOAD');
    }
    expect(JSON.stringify(payloads[1].messages)).toContain('REAL-TOOL-RESULT');
    expect(JSON.stringify(payloads[2].messages)).not.toContain('REAL-TOOL-RESULT');
    expect(await readFile(first.sessionFile!, 'utf8')).toContain('CHILD-DOCUMENT-RESULT');
  } finally {
    await f.close();
  }
});

it('propagates cancellation into the native child tool and does not claim success', async () => {
  const f = await fixture({ externalToolCall: { name: 'wait_for_document', arguments: {} } });
  const controller = new AbortController();
  let entered!: () => void;
  const started = new Promise<void>((resolve) => {
    entered = resolve;
  });
  let toolCancelled = false;
  const tool: ToolDefinition = {
    name: 'wait_for_document',
    label: 'Wait',
    description: 'Wait for test cancellation.',
    parameters: Type.Object({}),
    execute: async (_id, _params, signal) => {
      await new Promise<void>((resolve) => {
        const stop = () => {
          toolCancelled = true;
          resolve();
        };
        if (signal?.aborted) stop();
        else signal?.addEventListener('abort', stop, { once: true });
        entered();
      });
      return { content: [{ type: 'text', text: 'cancelled' }] };
    },
  };
  try {
    const pending = runPluginAgentSession({ ...f.base, signal: controller.signal, tools: [tool] });
    await started;
    controller.abort();
    const result = await pending;
    expect(result.status).toBe('cancelled');
    expect(toolCancelled).toBe(true);
    expect(f.gateway.requests).toHaveLength(1);
  } finally {
    await f.close();
  }
});

it('fails truncated output and event-delivery failure rather than returning completed', async () => {
  const f = await fixture({ response: async () => ({ content: 'partial', finishReason: 'length' }) });
  try {
    const truncated = await runPluginAgentSession(f.base);
    expect(truncated.status).toBe('failed');
    expect(truncated.error).toContain('length');
    const undelivered = await runPluginAgentSession({
      ...f.base,
      onEvent: async () => {
        throw new Error('sink unavailable');
      },
    });
    expect(undelivered.status).toBe('failed');
  } finally {
    await f.close();
  }
});
