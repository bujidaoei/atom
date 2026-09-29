import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

it.each(['streaming', 'completed', 'after-tool'] as const)(
  'recovers the same Pi session after a real process crash at %s',
  async (mode) => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-pi-process-crash-'));
    let requests = 0;
    const requestBodies: string[] = [];
    let closed = 0;
    const server = createServer(async (request, response) => {
      let body = '';
      for await (const chunk of request) body += String(chunk);
      requestBodies.push(body);
      const index = ++requests;
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      const send = (content: string, finish: string | null) =>
        response.write(
          `data: ${JSON.stringify({
            id: 'crash-stream',
            object: 'chat.completion.chunk',
            model: 'crash-test-model',
            choices: [{ index: 0, delta: { content }, finish_reason: finish }],
          })}\n\n`,
        );
      let timer: ReturnType<typeof setInterval> | undefined;
      if (mode === 'after-tool' && index === 1) {
        response.write(
          `data: ${JSON.stringify({ id: 'tool-turn', choices: [{ index: 0, delta: { tool_calls: [{ index: 0, id: 'tool-once', type: 'function', function: { name: 'sandbox_exec', arguments: JSON.stringify({ command: 'record-tool-once' }) } }] }, finish_reason: 'tool_calls' }] })}\n\n`,
        );
        response.end('data: [DONE]\n\n');
      } else if ((mode === 'streaming' && index === 1) || (mode === 'after-tool' && index === 2))
        timer = setInterval(() => send('partial ', null), 20);
      else {
        send(index === 1 ? 'DURABLE-RESULT' : 'RECOVERED-RESULT', 'stop');
        response.end('data: [DONE]\n\n');
      }
      response.on('close', () => {
        clearInterval(timer);
        closed++;
      });
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    const baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
    const child = spawn(
      process.execPath,
      ['--import', 'tsx', 'tests/fixtures/v5/pi-crash-owner.ts', root, baseUrl, mode],
      {
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
      },
    );
    let stderr = '';
    child.stderr?.on('data', (chunk) => {
      stderr += String(chunk);
    });
    const exited = once(child, 'exit');
    try {
      const boundary = await Promise.race([
        once(child, 'message', { signal: AbortSignal.timeout(20_000) }).then(([message]) => message),
        exited.then(() => {
          throw new Error(`Child exited before crash boundary: ${stderr}`);
        }),
      ]);
      expect(boundary).toEqual({ type: 'crash-boundary', boundary: mode });
      const path = join(root, 'session.jsonl');
      let persisted: string | undefined;
      if (mode === 'completed') {
        await vi.waitFor(async () => {
          persisted = await readFile(path, 'utf8');
          expect(persisted).toContain('DURABLE-RESULT');
        });
      }
      expect(child.kill('SIGKILL')).toBe(true);
      await exited;
      await vi.waitFor(() => expect(closed).toBeGreaterThanOrEqual(mode === 'after-tool' ? 2 : 1));
      const unexpectedTool = vi.fn(async () => {
        throw new Error('Unexpected tool replay');
      });
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl,
          masterKey: 'synthetic-only',
          model: 'crash-test-model',
          requestTimeoutMs: 5000,
        },
        agentDir: join(root, 'agent'),
        enableTools: mode === 'after-tool',
        toolPolicy: { evaluate: () => 'allow' },
        sandbox: {
          create: async () => 'unused',
          exec: unexpectedTool,
          destroy: async () => undefined,
        },
        approvals: { request: async () => 'rejected' },
        events: { emit: async () => undefined },
      });
      await expect(
        runtime.run({
          runId: 'crash-run',
          prompt: 'Return the fixed marker.',
          workspacePath: join(root, 'workspace'),
          sessionPath: path,
          recovery: true,
        }),
      ).resolves.toMatchObject({ resultText: mode === 'completed' ? 'DURABLE-RESULT' : 'RECOVERED-RESULT' });
      expect(requests).toBe(mode === 'completed' ? 1 : mode === 'after-tool' ? 3 : 2);
      expect(unexpectedTool).not.toHaveBeenCalled();
      if (mode === 'after-tool') {
        expect(await readFile(join(root, 'tool-marker.txt'), 'utf8')).toBe('TOOL-ONCE\n');
        expect(requestBodies.at(-1)).toContain('TOOL-ONCE');
      }
      const after = await readFile(path, 'utf8');
      const entries = after
        .trim()
        .split('\n')
        .map((line) => JSON.parse(line));
      expect(entries.filter((entry) => entry.type === 'session')).toHaveLength(1);
      if (persisted) expect(after).toBe(persisted);
    } finally {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
      await exited;
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      await rm(root, { recursive: true, force: true });
    }
  },
  30_000,
);
