import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

it.each([false, true])(
  'handles terminal truncation without breaking Pi tool recovery (tool=%s)',
  async (tool) => {
    const provider = await startGatewayLoopback({
      response: ({ requestNumber }) =>
        requestNumber === 1
          ? {
              finishReason: 'length',
              ...(tool ? { toolCall: { command: 'must-not-execute' } } : { content: 'Incomplete result' }),
            }
          : { content: 'Recovered through Pi' },
    });
    const root = await mkdtemp(join(tmpdir(), 'workdude-truncated-pi-'));
    const exec = vi.fn(async () => {
      throw new Error('Truncated tool must not execute');
    });
    const completed: string[] = [];
    try {
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: provider.baseUrl,
          masterKey: 'loopback-test-credential',
          model: 'gateway-test-model',
          requestTimeoutMs: 5000,
        },
        agentDir: join(root, 'agent'),
        sandbox: { create: async () => 'sandbox', exec, destroy: async () => undefined },
        approvals: { request: async () => 'rejected' },
        events: {
          emit: async (type, payload) => {
            if (type === 'message.completed') completed.push(String(payload.text));
          },
        },
        toolPolicy: { evaluate: () => 'allow' },
        enableTools: tool,
      });
      const result = runtime.run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt: 'Finish the request.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'session.jsonl'),
      });
      if (tool) {
        await expect(result).resolves.toMatchObject({ resultText: 'Recovered through Pi' });
        expect(provider.requests).toHaveLength(2);
        expect(completed).toEqual(['Recovered through Pi']);
      } else {
        await expect(result).rejects.toThrow('AI gateway response was truncated before completion');
        expect(provider.requests).toHaveLength(1);
        expect(completed).toEqual([]);
      }
      expect(exec).not.toHaveBeenCalled();
    } finally {
      await provider.close();
      await rm(root, { recursive: true, force: true });
    }
  },
  30000,
);
