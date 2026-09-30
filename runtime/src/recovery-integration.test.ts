import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { ProductAgentRuntime } from '../packages/agent-runtime/src/product-agent-runtime.ts';
import { LocalSandboxClient } from './local-sandbox.ts';
import { runWithRecovery } from './run-recovery.ts';

test('real Pi session recovers length stop without replaying successful tool', async () => {
  const requests: any[] = [];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    requests.push(JSON.parse(Buffer.concat(chunks).toString()));
    const n = requests.length;
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    const delta = n === 1 ? { role: 'assistant', tool_calls: [{ index: 0, id: 'write-once', type: 'function', function: {
      name: 'write', arguments: JSON.stringify({ path: 'index.html', content: '<h1>retained</h1>' }),
    } }] } : { role: 'assistant', content: n === 2 ? 'unfinished' : 'recovered' };
    res.write(`data: ${JSON.stringify({ id: `r${n}`, object: 'chat.completion.chunk', choices: [{ index: 0, delta, finish_reason: null }] })}\n\n`);
    res.end(`data: ${JSON.stringify({ id: `r${n}`, choices: [{ index: 0, delta: {}, finish_reason: n === 1 ? 'tool_calls' : n === 2 ? 'length' : 'stop' }], usage: { prompt_tokens: 5, completion_tokens: 2, total_tokens: 7 } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const root = await mkdtemp(join(tmpdir(), 'atom-recovery-'));
  let writes = 0;
  let acquisitions = 0;
  let releases = 0;
  try {
    const workspacePath = join(root, 'workspace');
    const local = new LocalSandboxClient({ resolveWorkspace: () => workspacePath });
    const runtime = new ProductAgentRuntime({
      aiGateway: { baseUrl: `http://127.0.0.1:${(server.address() as any).port}/v1`, masterKey: 'test-key', model: 'test-model', requestTimeoutMs: 5000 },
      agentDir: join(root, 'agent'), sandbox: {
        async create(runId, workspaceId) { acquisitions++; return local.create(runId, workspaceId); },
        async destroy(id) { releases++; await local.destroy(id); },
        exec: local.exec.bind(local), writeFile: local.writeFile.bind(local),
      },
      approvals: { request: async () => 'approved' },
      workspaceToolNames: ['write', 'edit', 'read_file', 'glob', 'grep'],
      events: { async emit(type, payload) { if (type === 'tool.completed' && payload.toolName === 'write') writes++; } },
    });
    const result = await runWithRecovery({ signal: new AbortController().signal, onRecover() {},
      run: recovery => runtime.run({ runId: 'recovery-test', prompt: 'write then finish', workspacePath, sessionPath: join(root, 'session.jsonl'), recovery }),
    });
    assert.equal(result.resultText, 'recovered');
    assert.equal(writes, 1);
    assert.equal(acquisitions, 2);
    assert.equal(releases, acquisitions);
    assert.equal(requests.length, 3);
    assert.ok(!requests[0].tools.some((tool: any) => tool.function.name === 'sandbox_exec'));
    assert.equal(await readFile(join(workspacePath, 'index.html'), 'utf8'), '<h1>retained</h1>');
    assert.ok(requests[2].messages.some((m: any) => m.role === 'tool'));
    assert.ok((result.usage?.inputTokens ?? 0) >= 15);
  } finally {
    server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
    await rm(root, { recursive: true, force: true });
  }
});
