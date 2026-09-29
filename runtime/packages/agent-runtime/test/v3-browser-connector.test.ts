import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { Value } from 'typebox/value';
import { describe, expect, it, vi } from 'vitest';

import { startEnterpriseGatewayLoopback } from '../../../tests/fixtures/v4/enterprise-ai-gateway.ts';
import {
  V3_BROWSER_CONTEXT_EMPTY_RESULT,
  assertV3BrowserJavascriptReadOnly,
  compileV3BrowserJavascriptReadOnly,
  loadV3BrowserConnectorTools,
  type V3BrowserConnectorRuntimeState,
  type V3BrowserToolHostPort,
} from '../src/v3-browser-connector.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

const ownerId = '10000000-0000-4000-8000-000000000001';
const wakerId = '30000000-0000-4000-8000-000000000001';

function state(
  browserContextToolAvailable: boolean,
  browserPageToolReady: boolean,
): V3BrowserConnectorRuntimeState {
  return { browserContextToolAvailable, browserPageToolReady };
}

function hostHarness(initialState = state(true, true)) {
  let currentState = initialState;
  const invoke = vi.fn(async ({ method }: { method: string }) => `${method} result`);
  const host: V3BrowserToolHostPort = {
    getState: vi.fn(async () => currentState),
    invoke,
  };
  return {
    host,
    invoke,
    setState(next: V3BrowserConnectorRuntimeState) {
      currentState = next;
    },
  };
}

describe('V3 Browser Connector Pi adapter', () => {
  it('injects no Browser tool outside a direct native Waker Run', async () => {
    const { host } = hostHarness();

    await expect(
      loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'group', host }),
    ).resolves.toEqual([]);
    await expect(loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'waker' })).resolves.toEqual(
      [],
    );

    const disabled = hostHarness(state(false, false));
    await expect(
      loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'waker', host: disabled.host }),
    ).resolves.toEqual([]);

    const unavailable = hostHarness();
    unavailable.host.getState = vi.fn(async () => {
      throw new Error('raw host transport detail');
    });
    await expect(
      loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'waker', host: unavailable.host }),
    ).resolves.toEqual([]);
  });

  it('offers only the exact context tool without a selected-page grant and returns the observed normal result locally', async () => {
    const { host, invoke } = hostHarness(state(true, false));
    const tools = await loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'waker', host });

    expect(tools.map(({ name }) => name)).toEqual(['mcp__plugin_builtin_browser__tabs_context_mcp']);
    expect(Value.Check(tools[0]!.parameters, {})).toBe(true);
    expect(Value.Check(tools[0]!.parameters, { createIfEmpty: true })).toBe(false);
    await expect(tools[0]!.execute('context', {}, undefined)).resolves.toEqual({
      content: [{ type: 'text', text: V3_BROWSER_CONTEXT_EMPTY_RESULT }],
      isError: false,
    });
    expect(invoke).not.toHaveBeenCalled();
  });

  it('exposes only the four source-locked safe names when a selected-page grant is ready', async () => {
    const { host } = hostHarness();
    const tools = await loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'waker', host });

    expect(tools.map(({ name }) => name)).toEqual([
      'mcp__plugin_builtin_browser__tabs_context_mcp',
      'mcp__plugin_builtin_browser__read_page',
      'mcp__plugin_builtin_browser__get_page_text',
      'mcp__plugin_builtin_browser__javascript_tool',
    ]);
    expect(tools.some(({ name }) => name === 'mcp__plugin_builtin_browser__tabs_context')).toBe(false);
  });

  it('removes model-controlled tab identity and forwards only bounded official read parameters', async () => {
    const { host, invoke } = hostHarness();
    const tools = await loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'waker', host });
    const read = tools.find(({ name }) => name.endsWith('__read_page'))!;
    const text = tools.find(({ name }) => name.endsWith('__get_page_text'))!;

    expect(
      Value.Check(read.parameters, {
        filter: 'interactive',
        depth: 5,
        max_chars: 20_000,
        ref_id: 'ref_1',
      }),
    ).toBe(false);
    expect(Value.Check(read.parameters, { filter: 'interactive', depth: 5, max_chars: 20_000 })).toBe(true);
    expect(Value.Check(read.parameters, { tabId: 42 })).toBe(false);
    expect(Value.Check(text.parameters, { max_chars: 50_000 })).toBe(true);
    expect(Value.Check(text.parameters, { max_chars: 200_001 })).toBe(false);

    await read.execute('read', { filter: 'interactive', depth: 5, max_chars: 20_000 }, undefined);
    await text.execute('text', { max_chars: 50_000 }, undefined);

    expect(invoke).toHaveBeenNthCalledWith(
      1,
      {
        ownerId,
        wakerId,
        method: 'read_page',
        input: { filter: 'interactive', depth: 5, max_chars: 20_000 },
      },
      expect.any(AbortSignal),
    );
    expect(invoke).toHaveBeenNthCalledWith(
      2,
      { ownerId, wakerId, method: 'get_page_text', input: { max_chars: 50_000 } },
      expect.any(AbortSignal),
    );
  });

  it('revalidates context and the selected-page grant immediately before every host dispatch', async () => {
    const harness = hostHarness();
    const tools = await loadV3BrowserConnectorTools({
      ownerId,
      wakerId,
      subjectType: 'waker',
      host: harness.host,
    });
    const read = tools.find(({ name }) => name.endsWith('__read_page'))!;

    harness.setState(state(true, false));
    await expect(read.execute('read', {}, undefined)).resolves.toMatchObject({
      isError: true,
      content: [{ type: 'text', text: 'Browser selected-page authorization is unavailable.' }],
    });
    expect(harness.invoke).not.toHaveBeenCalled();

    harness.setState(state(false, false));
    const context = tools.find(({ name }) => name.endsWith('__tabs_context_mcp'))!;
    await expect(context.execute('context', {}, undefined)).resolves.toMatchObject({
      isError: true,
      content: [{ type: 'text', text: 'Browser Connector is unavailable for this Waker.' }],
    });
    expect(harness.invoke).not.toHaveBeenCalled();
  });

  it('passes cancellation through and enforces a host-independent deadline', async () => {
    const aborting = hostHarness();
    aborting.host.invoke = vi.fn(
      async (_input, signal) =>
        new Promise<string>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(signal.reason), { once: true });
        }),
    );
    const tools = await loadV3BrowserConnectorTools({
      ownerId,
      wakerId,
      subjectType: 'waker',
      host: aborting.host,
      deadlineMs: 20,
    });
    const read = tools.find(({ name }) => name.endsWith('__read_page'))!;

    await expect(read.execute('read', {}, undefined)).rejects.toThrow(
      'Browser Connector tool exceeded its execution deadline.',
    );

    const controller = new AbortController();
    controller.abort(new Error('Run cancelled'));
    await expect(read.execute('read', {}, controller.signal)).rejects.toThrow('Run cancelled');
  });

  it('allows a small parser-validated read-only JavaScript expression and rejects unsafe syntax before relay', async () => {
    const { host, invoke } = hostHarness();
    const tools = await loadV3BrowserConnectorTools({ ownerId, wakerId, subjectType: 'waker', host });
    const javascript = tools.find(({ name }) => name.endsWith('__javascript_tool'))!;
    const source = `(document.querySelector('main h1')?.textContent ?? '').trim()`;

    expect(() => assertV3BrowserJavascriptReadOnly(source)).not.toThrow();
    await javascript.execute('javascript', { text: source }, undefined);
    expect(invoke).toHaveBeenCalledWith(
      { ownerId, wakerId, method: 'javascript_tool', input: { text: source } },
      expect.any(AbortSignal),
    );

    const denied = [
      `document.body.textContent = 'changed'`,
      `document.querySelector('a')?.click()`,
      `location.href = 'https://example.test/'`,
      `fetch('https://example.test/')`,
      `localStorage.getItem('token')`,
      `navigator.clipboard.readText()`,
      `eval('document.title')`,
      `Function('return document.title')()`,
      `window.open('https://example.test/')`,
      `document['cookie']`,
      `(() => document.title)()`,
    ];
    for (const text of denied) {
      expect(() => assertV3BrowserJavascriptReadOnly(text), text).toThrow(
        'Browser JavaScript policy rejected the expression.',
      );
      await expect(javascript.execute('javascript', { text }, undefined)).resolves.toMatchObject({
        isError: true,
      });
    }
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it('compiles approved JavaScript into a structured-cloneable AST without dynamic code', () => {
    const compiled = compileV3BrowserJavascriptReadOnly(String.raw`document.querySelector('main\u0020h1')`);

    expect(structuredClone(compiled)).toEqual(compiled);
    expect(compiled).toMatchObject({
      type: 'call',
      arguments: [{ type: 'literal', value: 'main h1' }],
    });
    expect(JSON.stringify(compiled)).not.toMatch(/eval|Function|source/u);
  });

  it('rejects malformed inputs and over-limit host results without leaking them into Pi', async () => {
    const harness = hostHarness();
    harness.host.invoke = vi.fn(async () => 'x'.repeat(200_001));
    const tools = await loadV3BrowserConnectorTools({
      ownerId,
      wakerId,
      subjectType: 'waker',
      host: harness.host,
    });
    const read = tools.find(({ name }) => name.endsWith('__read_page'))!;

    await expect(read.execute('read', { max_chars: 200_001 } as never, undefined)).resolves.toMatchObject({
      isError: true,
    });
    expect(harness.host.invoke).not.toHaveBeenCalled();

    await expect(read.execute('read', { max_chars: 200_000 }, undefined)).rejects.toThrow(
      'Browser Connector returned an invalid or over-limit result.',
    );
  });

  it('uses one existing Pi loop, persists one normal no-grant card, and does not re-execute recovery', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-browser-runtime-'));
    const gateway = await startEnterpriseGatewayLoopback({
      toolCall: { name: 'mcp__plugin_builtin_browser__tabs_context_mcp', arguments: {} },
      contentChunks: ['Browser page access is unavailable without a selected-page grant.'],
    });
    const events: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const harness = hostHarness(state(true, false));
    try {
      const externalTools = await loadV3BrowserConnectorTools({
        ownerId,
        wakerId,
        subjectType: 'waker',
        host: harness.host,
      });
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: `${gateway.baseUrl}/v1`,
          masterKey: gateway.apiKey,
          model: 'gateway-model-a',
          requestTimeoutMs: 5_000,
        },
        agentDir: join(root, 'agent'),
        sandbox: {
          async create() {
            throw new Error('Browser context-only Run must not create a sandbox.');
          },
          async exec() {
            throw new Error('Browser context-only Run must not execute in a sandbox.');
          },
          async destroy() {},
        },
        approvals: {
          async request() {
            throw new Error('Read-only Browser context must not request approval.');
          },
        },
        events: { emit: async (type, payload) => void events.push({ type, payload }) },
        enableTools: false,
        externalTools,
      });
      const request = {
        runId: crypto.randomUUID(),
        prompt: 'Read only the selected Browser page, or report the exact no-grant failure.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'sessions', 'browser.jsonl'),
      };

      const first = await runtime.run(request);
      const recovered = await runtime.run({ ...request, recovery: true });

      expect(first.resultText).toBe('Browser page access is unavailable without a selected-page grant.');
      expect(recovered).toEqual(first);
      expect(gateway.requests.filter(({ url }) => url === '/v1/chat/completions')).toHaveLength(2);
      expect(harness.invoke).not.toHaveBeenCalled();
      expect(events.map(({ type }) => type)).toEqual(
        expect.arrayContaining(['tool.requested', 'tool.started', 'tool.completed', 'message.completed']),
      );
      const completedEvents = events.filter(
        ({ type, payload }) =>
          type === 'tool.completed' && payload.toolName === 'mcp__plugin_builtin_browser__tabs_context_mcp',
      );
      expect(completedEvents).toHaveLength(1);
      expect(completedEvents[0]?.payload.isError).toBe(false);
    } finally {
      await gateway.close();
      await rm(root, { recursive: true, force: true });
    }
  });
});
