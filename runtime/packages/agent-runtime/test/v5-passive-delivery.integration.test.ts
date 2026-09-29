import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { startEnterpriseGatewayLoopback } from '../../../tests/fixtures/v4/enterprise-ai-gateway.ts';
import type { V3GroupInboxPage } from '../../product-contracts/src/v3-ports.ts';
import { ProductAgentRuntime, type ProductAgentRuntimeOptions } from '../src/product-agent-runtime.ts';

const closes: Array<() => Promise<void>> = [];
afterEach(async () => {
  for (const close of closes.splice(0)) await close();
});
function batch(id?: string): V3GroupInboxPage {
  return {
    runId: 'passive-run',
    participantId: 'participant',
    claimId: 'batch',
    context: [],
    messages: id
      ? [
          {
            id,
            sequence: 2,
            type: 'user.message',
            occurredAt: '2026-09-20T00:00:00Z',
            payload: { content: id },
          },
        ]
      : [],
    candidateCount: id ? 1 : 0,
    claimedCount: id ? 1 : 0,
    pendingCount: 0,
    exhausted: !id,
    nextCursor: null,
    members: [],
  };
}
async function harness(
  next: NonNullable<ProductAgentRuntimeOptions['groupInbox']>['next'],
  options: { events?: ProductAgentRuntimeOptions['events']; status?: number } = {},
) {
  const root = await mkdtemp(join(tmpdir(), 'workdude-passive-delivery-'));
  const gateway = await startEnterpriseGatewayLoopback({
    contentChunks: ['finished'],
    ...(options.status ? { status: options.status } : {}),
  });
  closes.push(gateway.close, () => rm(root, { recursive: true, force: true }));
  const events: Array<{ type: string; payload: Record<string, unknown> }> = [];
  const snapshot = vi.fn<NonNullable<ProductAgentRuntimeOptions['groupInbox']>['snapshot']>(async () => ({
    todos: [
      {
        todo_id: 'fresh-todo',
        content: 'Updated during this Run',
        status: 'in_progress',
        created_at: '2026-09-20T00:00:00Z',
        updated_at: '2026-09-20T00:01:00Z',
      },
    ],
    goal: null,
  }));
  const runtime = new ProductAgentRuntime({
    aiGateway: {
      baseUrl: `${gateway.baseUrl}/v1`,
      masterKey: gateway.apiKey,
      model: 'gateway-model-a',
      requestTimeoutMs: 5000,
    },
    agentDir: join(root, 'agent'),
    sandbox: { create: vi.fn(), exec: vi.fn(), destroy: vi.fn() },
    approvals: { request: async () => 'approved' },
    enableTools: false,
    groupInbox: {
      conversationId: 'conversation',
      initial: batch('initial'),
      next,
      snapshot,
    },
    events: options.events ?? {
      emit: async (type, payload) => {
        events.push({ type, payload });
      },
    },
  });
  const request = {
    runId: 'passive-run',
    prompt: 'Process initial work.',
    workspacePath: join(root, 'workspace'),
    sessionPath: join(root, 'session.jsonl'),
  };
  return { runtime, request, gateway, events, snapshot };
}
describe('host-owned delivery through the real Pi loop', () => {
  it('awaits settlement and processes the next batch in the same session without claim/read prompts', async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const next = vi.fn(async () => {
      if (next.mock.calls.length === 1) {
        await held;
        return batch('later-work');
      }
      return batch();
    });
    const { runtime, request, gateway, events, snapshot } = await harness(next);
    let settled = false;
    const run = runtime.run(request).finally(() => {
      settled = true;
    });
    try {
      await vi.waitFor(() => expect(next).toHaveBeenCalledOnce(), { timeout: 15000 });
      expect(settled).toBe(false);
      expect(gateway.requests).toHaveLength(1);
      expect(snapshot).not.toHaveBeenCalled();
      release();
      await expect(run).resolves.toMatchObject({ resultText: 'finished' });
      expect(gateway.requests).toHaveLength(2);
      expect(snapshot).toHaveBeenCalledOnce();
      expect(events.filter(({ type }) => type === 'run.started')).toHaveLength(1);
      expect(events.filter(({ type }) => type === 'run.inbox_delivery')).toHaveLength(1);
      const session = await readFile(request.sessionPath, 'utf8');
      const header = JSON.parse(session.split('\n')[0]!);
      expect(events.filter(({ type }) => type === 'run.session')).toEqual([
        { type: 'run.session', payload: { sessionId: header.id, input: '[seq=2] [id=initial]\ninitial' } },
      ]);
      expect(session).toContain('later-work');
      expect(session).toContain('fresh-todo');
      expect(session).toContain('Updated during this Run');
      expect(session).toContain('todos_complete');
      expect(session).toContain('Current Goal snapshot');
      expect(session).not.toContain('qoderwake messages claim');
      expect(session).not.toContain('qoderwake messages read');
      expect(session).not.toContain(gateway.apiKey);
    } finally {
      release();
      await run.catch(() => undefined);
    }
  });
  it('rejects a repeated delivered batch instead of repeating work', async () => {
    const { runtime, request, gateway } = await harness(async () => batch('later-work'));
    await expect(runtime.run(request)).rejects.toThrow('already delivered work');
    expect(gateway.requests).toHaveLength(2);
  });
  it('fails delivery instead of fabricating an empty snapshot after a host read failure', async () => {
    const { runtime, request, gateway, events, snapshot } = await harness(async () => batch('later-work'));
    snapshot.mockRejectedValue(new Error('snapshot claim expired'));
    await expect(runtime.run(request)).rejects.toThrow('snapshot claim expired');
    expect(gateway.requests).toHaveLength(1);
    expect(events.filter(({ type }) => type === 'run.inbox_delivery')).toEqual([]);
  });
  it('does not inject a snapshot whose read finishes after cancellation', async () => {
    const { runtime, request, gateway, events, snapshot } = await harness(async () => batch('later-work'));
    let release!: () => void;
    snapshot.mockImplementation(async () => {
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return { todos: [], goal: null };
    });
    const abort = new AbortController();
    const run = runtime.run({ ...request, signal: abort.signal });
    const rejection = expect(run).rejects.toThrow();
    try {
      await vi.waitFor(() => expect(snapshot).toHaveBeenCalledOnce(), { timeout: 15000 });
      abort.abort();
      release();
      await rejection;
      expect(gateway.requests).toHaveLength(1);
      expect(events.filter(({ type }) => type === 'run.inbox_delivery')).toEqual([]);
    } finally {
      release?.();
      await run.catch(() => undefined);
    }
  });
  it('does not acknowledge work after event persistence fails', async () => {
    const next = vi.fn(async () => batch());
    const { runtime, request, gateway } = await harness(next, {
      events: {
        emit: async (type) => {
          if (type === 'message.completed') throw new Error('event persistence failed');
        },
      },
    });
    await expect(runtime.run(request)).rejects.toThrow('event persistence failed');
    expect(next).not.toHaveBeenCalled();
    expect(gateway.requests).toHaveLength(1);
  });
  it('does not inject a delayed batch after cancellation', async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const next = vi.fn(async () => {
      await held;
      return batch('later-work');
    });
    const { runtime, request, gateway } = await harness(next);
    const controller = new AbortController();
    const run = runtime.run({ ...request, signal: controller.signal });
    void run.catch(() => undefined);
    try {
      await vi.waitFor(() => expect(next).toHaveBeenCalledOnce(), { timeout: 15000 });
      controller.abort();
      release();
      await expect(run).rejects.toThrow();
      expect(gateway.requests).toHaveLength(1);
    } finally {
      release();
      await run.catch(() => undefined);
    }
  });
  it('does not acknowledge provider rejection as completed work', async () => {
    const next = vi.fn(async () => batch());
    const { runtime, request } = await harness(next, { status: 403 });
    await expect(runtime.run(request)).rejects.toThrow();
    expect(next).not.toHaveBeenCalled();
  });
  it('keeps rejected authority details outside the Pi session', async () => {
    const secret = 'sk-private-authority-error-fixture';
    const { runtime, request, gateway } = await harness(async () => {
      throw new Error(secret);
    });
    await expect(runtime.run(request)).rejects.toThrow('Host delivery could not be advanced');
    expect(gateway.requests).toHaveLength(1);
    expect(await readFile(request.sessionPath, 'utf8')).not.toContain(secret);
  });
  it('does not inject a batch whose audit cannot be persisted', async () => {
    const { runtime, request, gateway } = await harness(async () => batch('later-work'), {
      events: {
        emit: async (type) => {
          if (type === 'run.inbox_delivery') throw new Error('private audit error');
        },
      },
    });
    await expect(runtime.run(request)).rejects.toThrow('event persistence failed');
    expect(gateway.requests).toHaveLength(1);
    expect(await readFile(request.sessionPath, 'utf8')).not.toContain('private audit error');
  });
});
