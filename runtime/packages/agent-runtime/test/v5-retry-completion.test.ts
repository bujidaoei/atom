import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

it.each([true, false])(
  'uses the final Pi response after native retry (recovers=%s)',
  async (recovers) => {
    const provider = await startGatewayLoopback({
      response: ({ requestNumber }) => {
        if (!recovers || requestNumber === 1) throw new Error('Synthetic temporary gateway failure');
        return { content: 'RECOVERED-THROUGH-NATIVE-PI' };
      },
    });
    const root = await mkdtemp(join(tmpdir(), 'workdude-retry-pi-'));
    const events: Array<{ type: string; payload: Record<string, unknown> }> = [];
    try {
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: provider.baseUrl,
          masterKey: 'loopback-test-credential',
          model: 'gateway-test-model',
          requestTimeoutMs: 5000,
        },
        agentDir: join(root, 'agent'),
        sandbox: {
          create: async () => 'sandbox',
          exec: async () => {
            throw new Error('No tools expected');
          },
          destroy: async () => undefined,
        },
        approvals: { request: async () => 'rejected' },
        events: {
          emit: async (type, payload) => {
            events.push({ type, payload });
          },
        },
        enableTools: false,
      });
      const result = runtime.run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt: 'Reply with the proof marker.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'session.jsonl'),
      });
      if (recovers) {
        await expect(result).resolves.toMatchObject({ resultText: 'RECOVERED-THROUGH-NATIVE-PI' });
        expect(events).toContainEqual(
          expect.objectContaining({
            type: 'model.retry_completed',
            payload: expect.objectContaining({ success: true }),
          }),
        );
      } else {
        await expect(result).rejects.toThrow('Synthetic temporary gateway failure');
        expect(events).toContainEqual(
          expect.objectContaining({
            type: 'model.retry_completed',
            payload: expect.objectContaining({ success: false }),
          }),
        );
      }
      expect(events.some((event) => event.type === 'model.retry_scheduled')).toBe(true);
      expect(provider.requests.length).toBeGreaterThan(1);
    } finally {
      await provider.close();
      await rm(root, { recursive: true, force: true });
    }
  },
  60000,
);
