import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type { AddressInfo } from 'node:net';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

it('keeps transport cancellation connected after garbage collection', async () => {
  const result = await promisify(execFile)(
    process.execPath,
    ['--expose-gc', '--import', 'tsx', 'tests/fixtures/v5/pi-stream-cancel-gc.ts'],
    { cwd: process.cwd(), windowsHide: true, timeout: 25000 },
  );
  const evidence = JSON.parse(result.stdout.trim()) as {
    aborted: boolean;
    rejected: boolean;
    elapsed: number;
    connectionClosed: boolean;
    sent: number;
  };
  expect(evidence).toMatchObject({ aborted: true, rejected: true, connectionClosed: true });
  expect(evidence.elapsed).toBeLessThan(1000);
  expect(evidence.sent).toBeLessThan(150);
}, 30000);

it.each([
  [0, false],
  [150, false],
  [0, true],
  [150, true],
] as const)(
  'closes actual Pi streaming with event delay %s ms and persistence failure %s',
  async (eventDelay, persistenceFailure) => {
    let sent = 0;
    let closed = false;
    const server = createServer(async (request, response) => {
      for await (const chunk of request) void chunk;
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      const timer = setInterval(() => {
        sent++;
        response.write(
          `data: ${JSON.stringify({
            id: 'stream-test',
            object: 'chat.completion.chunk',
            created: 1,
            model: 'gateway-test-model',
            choices: [{ index: 0, delta: { content: `line-${sent}\n` }, finish_reason: null }],
          })}\n\n`,
        );
        if (sent >= 100) {
          response.write('data: [DONE]\n\n');
          response.end();
        }
      }, 20);
      response.on('close', () => {
        closed = true;
        clearInterval(timer);
      });
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    const root = await mkdtemp(join(tmpdir(), 'workdude-stream-cancel-'));
    const controller = new AbortController();
    let countAtAbort = 0;
    let lateDeltas = 0;
    try {
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`,
          masterKey: 'synthetic-only',
          model: 'gateway-test-model',
          requestTimeoutMs: 5000,
        },
        agentDir: join(root, 'agent'),
        sandbox: {
          create: async () => 'unused',
          exec: async () => {
            throw new Error('No tools expected');
          },
          destroy: async () => undefined,
        },
        approvals: { request: async () => 'rejected' },
        events: {
          emit: async (type) => {
            if (type !== 'message.delta') return;
            if (controller.signal.aborted || countAtAbort > 0) lateDeltas++;
            else {
              if (eventDelay) await new Promise<void>((resolve) => setTimeout(resolve, eventDelay));
              countAtAbort = sent;
              if (persistenceFailure) throw new Error('Run execution claim was lost');
              controller.abort();
            }
          },
        },
        toolPolicy: { evaluate: () => 'deny' },
        enableTools: false,
      });
      await expect(
        runtime.run({
          runId: 'stream-cancel',
          prompt: 'Output numbered lines.',
          workspacePath: join(root, 'workspace'),
          sessionPath: join(root, 'session.jsonl'),
          signal: controller.signal,
        }),
      ).rejects.toThrow(persistenceFailure ? 'Run execution claim was lost' : undefined);
      expect(countAtAbort).toBeGreaterThan(0);
      await vi.waitFor(() => expect(closed).toBe(true), { timeout: 500, interval: 10 });
      expect(sent - countAtAbort).toBeLessThan(5);
      expect(lateDeltas).toBe(0);
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      await rm(root, { recursive: true, force: true });
    }
  },
  30_000,
);
