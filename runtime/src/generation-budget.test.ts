import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdir, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { ProductAgentRuntime } from '../packages/agent-runtime/src/product-agent-runtime.ts';
import { LocalSandboxClient } from './local-sandbox.ts';
import { generationBudget } from './generation-budget.ts';

test('budget defaults to one hour, preserves long budgets and rejects invalid values', () => {
  assert.equal(generationBudget(undefined), 3_600_000);
  assert.equal(generationBudget(7_140_000), 7_140_000);
  for (const value of [null, true, '3600000', NaN, Infinity, 0, -1, 7_140_001]) {
    assert.throws(() => generationBudget(value));
  }
});

for (const behavior of ['success', 'cancel', 'redirect']) test(`real Pi gateway transport: ${behavior}`,
  { timeout: 350_000 }, async () => {
    const cancel = behavior === 'cancel';
    const redirect = behavior === 'redirect';
    const delay = process.env.ATOM_LONG_GENERATION_TEST === '1' && behavior === 'success' ? 310_000 : 250;
    const root = await mkdtemp(join(tmpdir(), 'atom-budget-'));
    const agentDir = join(root, 'agent');
    const workspacePath = join(root, 'workspace');
    await mkdir(agentDir); await mkdir(workspacePath);
    const persisted = JSON.stringify({ httpIdleTimeoutMs: 20,
      retry: { enabled: false, provider: { timeoutMs: 20, maxRetries: 0 } } });
    const settingsFile = join(agentDir, 'settings.json');
    await writeFile(settingsFile, persisted);
    let requests = 0;
    let closed = false;
    const controller = new AbortController();
    const server = createServer(async (req, res) => {
      for await (const _ of req) { /* Drain the actual request body. */ }
      requests++;
      if (redirect) {
        res.writeHead(307, { location: '/outside-gateway' });
        res.end();
        res.on('close', () => { closed = true; });
        return;
      }
      const timer = setTimeout(() => {
        res.writeHead(200, { 'content-type': 'text/event-stream' });
        res.write(`data: ${JSON.stringify({ id: 'budget-proof', object: 'chat.completion.chunk',
          choices: [{ index: 0, delta: { role: 'assistant', content: 'SLOW-SUCCESS' }, finish_reason: null }] })}\n\n`);
        res.end(`data: ${JSON.stringify({ id: 'budget-proof', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
          usage: { prompt_tokens: 5, completion_tokens: 2, total_tokens: 7 } })}\n\ndata: [DONE]\n\n`);
      }, cancel ? 310_000 : delay);
      const abortTimer = cancel ? setTimeout(() => controller.abort(), 150) : undefined;
      res.on('close', () => { closed = true; clearTimeout(timer); clearTimeout(abortTimer); });
    });
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      const runtime = new ProductAgentRuntime({
        aiGateway: { baseUrl: `http://127.0.0.1:${(server.address() as any).port}/v1`,
          masterKey: 'synthetic-test-only', model: 'test-model', requestTimeoutMs: generationBudget(undefined) },
        agentDir, sandbox: new LocalSandboxClient({ resolveWorkspace: () => workspacePath }),
        approvals: { request: async () => 'rejected' }, events: { async emit() {} }, enableTools: false,
      });
      const started = performance.now();
      const result = runtime.run({ runId: 'budget-test', prompt: 'Return a short response.', workspacePath,
        sessionPath: join(root, 'session.jsonl'), signal: controller.signal });
      if (cancel || redirect) {
        await assert.rejects(result);
        assert.ok(performance.now() - started < 5000);
      } else {
        assert.equal((await result).resultText, 'SLOW-SUCCESS');
        assert.ok(performance.now() - started >= delay);
      }
      assert.equal(requests, 1);
      assert.equal(await readFile(settingsFile, 'utf8'), persisted, 'policy must not rewrite persisted settings');
      await new Promise(resolve => setTimeout(resolve, 100));
      assert.equal(closed, true);
      console.log(JSON.stringify({ delayedHttpMs: delay, cancelled: cancel, elapsedMs: Math.round(performance.now() - started) }));
    } finally {
      controller.abort(); server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
      await rm(root, { recursive: true, force: true });
    }
  });
