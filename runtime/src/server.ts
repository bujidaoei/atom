/**
 * Agent runtime sidecar.
 *
 * Wraps the vendored WorkDude ProductAgentRuntime in a small HTTP surface so
 * the FastAPI application can drive agent turns without hosting Node itself.
 * One request equals one agent turn; the response is an NDJSON event stream
 * that mirrors the runtime's own event contract, terminated by a result or
 * error line.
 */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { mkdir } from 'node:fs/promises';
import { dirname, isAbsolute } from 'node:path';

import { ProductAgentRuntime } from '../packages/agent-runtime/src/product-agent-runtime.ts';
import type { RunEventType } from '../packages/product-contracts/src/index.ts';
import { LocalSandboxClient } from './local-sandbox.ts';
import { allRoles, roleDefinition } from './squad.ts';
import { runWithRecovery } from './run-recovery.ts';

const PORT = Number(process.env.ATOM_RUNTIME_PORT ?? 8721);
const HOST = process.env.ATOM_RUNTIME_HOST ?? '127.0.0.1';
const SHARED_TOKEN = process.env.ATOM_RUNTIME_TOKEN ?? '';
const MAX_BODY_BYTES = 4 * 1024 * 1024;

interface RunBody {
  runId: string;
  role: string;
  prompt: string;
  workspacePath: string;
  sessionPath: string;
  agentDir: string;
  parentSessionPath?: string;
  gateway: { baseUrl: string; apiKey: string; model: string; requestTimeoutMs?: number };
  systemPromptSuffix?: string;
  enableTools?: boolean;
  budgetMs?: number;
}

const active = new Map<string, AbortController>();

const server = createServer((request, response) => {
  handle(request, response).catch((error: unknown) => {
    if (!response.headersSent) sendJson(response, 500, { error: describe(error) });
    else response.end();
  });
});

async function handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`);

  if (request.method === 'GET' && url.pathname === '/healthz') {
    return sendJson(response, 200, { status: 'ok', activeRuns: active.size });
  }

  if (!authorized(request)) return sendJson(response, 401, { error: 'unauthorized' });

  if (request.method === 'GET' && url.pathname === '/v1/roles') {
    return sendJson(response, 200, {
      roles: allRoles().map(({ id, name, title, tools }) => ({ id, name, title, tools })),
    });
  }

  if (request.method === 'POST' && url.pathname === '/v1/runs') {
    return await startRun(request, response);
  }

  const cancelMatch = /^\/v1\/runs\/([^/]+)\/cancel$/.exec(url.pathname);
  if (request.method === 'POST' && cancelMatch) {
    const controller = active.get(decodeURIComponent(cancelMatch[1]));
    controller?.abort();
    return sendJson(response, 200, { cancelled: Boolean(controller) });
  }

  sendJson(response, 404, { error: 'not found' });
}

async function startRun(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const body = (await readJson(request)) as RunBody;
  const role = roleDefinition(body.role);

  if (active.has(body.runId)) return sendJson(response, 409, { error: 'run already active' });

  const controller = new AbortController();
  active.set(body.runId, controller);
  const deadline = setTimeout(() => controller.abort(), Math.max(1, Math.min(body.budgetMs ?? 180_000, 1_800_000)) + 1000);

  response.writeHead(200, {
    'content-type': 'application/x-ndjson; charset=utf-8',
    'cache-control': 'no-store',
    connection: 'close',
  });

  const write = (line: Record<string, unknown>) => {
    if (!response.writableEnded) response.write(`${JSON.stringify(line)}\n`);
  };

  // A dropped client means nobody is reading the stream; stop burning tokens.
  response.on('close', () => controller.abort());

  try {
    // The caller runs in a different working directory, so a relative path
    // would silently land somewhere else. Refuse it rather than guess.
    requireAbsolute(body, 'workspacePath', 'sessionPath', 'agentDir');

    await mkdir(body.workspacePath, { recursive: true });
    await mkdir(body.agentDir, { recursive: true });
    await mkdir(dirname(body.sessionPath), { recursive: true });

    const sandbox = new LocalSandboxClient({
      resolveWorkspace: () => body.workspacePath,
    });

    const runtime = new ProductAgentRuntime({
      aiGateway: {
        baseUrl: body.gateway.baseUrl,
        masterKey: body.gateway.apiKey,
        model: body.gateway.model,
        requestTimeoutMs: body.gateway.requestTimeoutMs ?? 300_000,
      },
      agentDir: body.agentDir,
      sandbox,
      approvals: { request: async () => 'approved' as const },
      events: {
        async emit(type: RunEventType, payload: Record<string, unknown>) {
          write({ kind: 'event', type, payload });
        },
      },
      enableTools: body.enableTools ?? role.tools,
      workspaceToolNames: ['glob', 'grep', 'read_file', 'write', 'edit'],
      systemPrompt: (body.systemPromptSuffix
        ? `${role.systemPrompt}\n\n## Context from the squad\n${body.systemPromptSuffix}`
        : role.systemPrompt) + `\n\nThis turn has a wall-clock budget of ${(body.budgetMs ?? 180_000) / 1000} seconds including tools and recovery. Finish core functionality within this budget.`,
    });

    const result = await runWithRecovery({
      signal: controller.signal,
      onRecover(attempt, maxAttempts) {
        write({ kind: 'event', type: 'run.recovering', payload: {
          attempt, maxAttempts, message: `响应被截断，正在从已有进度恢复（${attempt}/${maxAttempts}）`,
        } });
      },
      run: (recovery) => runtime.run({
      runId: body.runId,
      prompt: body.prompt,
      workspacePath: body.workspacePath,
      sessionPath: body.sessionPath,
      ...(body.parentSessionPath ? { parentSessionPath: body.parentSessionPath } : {}),
      model: body.gateway.model,
      signal: controller.signal,
      recovery,
      }),
    });

    write({
      kind: 'result',
      role: role.id,
      resultText: result.resultText,
      usage: result.usage,
      sessionFile: result.sessionFile,
      providerCorrelationId: result.providerCorrelationId,
    });
  } catch (error) {
    write({
      kind: 'error',
      role: role.id,
      cancelled: controller.signal.aborted,
      message: describe(error),
    });
  } finally {
    clearTimeout(deadline);
    active.delete(body.runId);
    response.end();
  }
}

function requireAbsolute(body: RunBody, ...keys: (keyof RunBody)[]): void {
  for (const key of keys) {
    const value = body[key];
    if (typeof value !== 'string' || !isAbsolute(value)) {
      throw new Error(`${String(key)} must be an absolute path, got ${String(value)}`);
    }
  }
}

function authorized(request: IncomingMessage): boolean {
  if (!SHARED_TOKEN) return true;
  const header = request.headers.authorization;
  return header === `Bearer ${SHARED_TOKEN}`;
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of request) {
    bytes += (chunk as Buffer).byteLength;
    if (bytes > MAX_BODY_BYTES) throw new Error('request body too large');
    chunks.push(chunk as Buffer);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(payload),
  });
  response.end(payload);
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

server.listen(PORT, HOST, () => {
  process.stdout.write(`atom runtime sidecar listening on http://${HOST}:${PORT}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    for (const controller of active.values()) controller.abort();
    server.close(() => process.exit(0));
  });
}
