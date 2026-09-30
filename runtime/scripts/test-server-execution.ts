import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';

const input = JSON.parse(readFileSync(0, 'utf8'));
const root = await mkdtemp(join(tmpdir(), 'atom-server-execution-'));
let requests = 0;
let cancellation: Promise<void> = Promise.resolve();
const model = createServer(async (req, res) => {
  for await (const _chunk of req) { /* consume request before responding */ }
  requests++;
  if (requests === 2 && ['cancel', 'deadline'].includes(input.interrupt)) {
    if (input.interrupt === 'cancel') cancellation = (async () => {
      const response = await fetch(`http://127.0.0.1:${port}/v1/runs/${input.lease.runId}/cancel`, {
        method: 'POST', headers: { authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(3000),
      });
      assert.equal(response.status, 200);
      assert.equal((await response.json()).cancelled, true);
    })();
    // Hold the actual second model response until runtime interruption closes it.
    return;
  }
  const delta = requests === 1 ? { role: 'assistant', tool_calls: [{ index: 0, id: 'write-output', type: 'function',
    function: { name: 'write', arguments: JSON.stringify({ path: input.outputFile ?? 'result.txt', content: input.outputText ?? 'actual coordinator output' }) } }] }
    : { role: 'assistant', content: 'Output saved.' };
  res.writeHead(200, { 'content-type': 'text/event-stream' });
  res.write(`data: ${JSON.stringify({ id: `r${requests}`, choices: [{ index: 0, delta, finish_reason: null }] })}\n\n`);
  res.end(`data: ${JSON.stringify({ id: `r${requests}`, choices: [{ index: 0, delta: {}, finish_reason: requests === 1 ? 'tool_calls' : 'stop' }] })}\n\ndata: [DONE]\n\n`);
});
await new Promise<void>(resolve => model.listen(0, '127.0.0.1', resolve));
const probe = createServer();
await new Promise<void>(resolve => probe.listen(0, '127.0.0.1', resolve));
const port = (probe.address() as any).port;
await new Promise<void>(resolve => probe.close(() => resolve()));
const runtime = dirname(dirname(fileURLToPath(import.meta.url)));
const token = randomBytes(32).toString('hex');
const child = spawn(process.execPath, ['--import', 'tsx', 'src/server.ts'], { cwd: runtime, windowsHide: true,
  env: { ...process.env, ATOM_ENVIRONMENT: 'production', ATOM_RUNTIME_TOKEN: token, ATOM_RUNTIME_PORT: String(port),
    ATOM_RUNTIME_HOST: '127.0.0.1', ATOM_SANDBOX_MODE: 'broker', ATOM_BROKER_ORIGIN: input.brokerOrigin,
    ATOM_EXECUTION_ORIGIN: input.executionOrigin }, stdio: ['ignore', 'pipe', 'pipe'] });
const exited = new Promise(resolve => child.once('exit', resolve));
let output = '';
child.stdout.on('data', chunk => { output += chunk; });
child.stderr.on('data', chunk => { output += chunk; });
try {
  const until = Date.now() + 5000;
  while (!output.includes('listening on')) {
    if (Date.now() > until || child.exitCode !== null) throw new Error('Runtime startup failed');
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  const body = { runId: input.lease.runId, role: 'alex', prompt: 'Write result.txt then finish.',
    ...(input.request ? {role:input.request.role, prompt:input.request.prompt,
      systemPromptSuffix:input.request.systemPromptSuffix, enableTools:input.request.enableTools} : {}),
    workspacePath: join(root, 'workspace'), sessionPath: join(root, 'session.jsonl'), agentDir: join(root, 'agent'),
    gateway: { baseUrl: `http://127.0.0.1:${(model.address() as any).port}/v1`, apiKey: 'synthetic-model-key', model: 'test-model' },
    budgetMs: input.interrupt?.startsWith('deadline') ? 3000 : 15000, lease: input.lease };
  const denied = await fetch(`http://127.0.0.1:${port}/v1/runs`, { method: 'POST',
    headers: { authorization: `Bearer ${token}` }, body: JSON.stringify({ ...body, lease: undefined }) });
  assert.equal(denied.status, 400);
  assert.equal(requests, 0);
  const response = await fetch(`http://127.0.0.1:${port}/v1/runs`, { method: 'POST',
    headers: { authorization: `Bearer ${token}` }, body: JSON.stringify(body), signal: AbortSignal.timeout(18000) });
  assert.equal(response.status, 200);
  const lines = (await response.text()).trim().split('\n').map(line => JSON.parse(line));
  assert.equal(requests, 2);
  await cancellation;
  if (input.interrupt) {
    assert.equal(lines.at(-1).kind, 'error', JSON.stringify(lines.at(-1)));
    assert.equal(lines.at(-1).status, input.interrupt === 'cancel' ? 'cancelled' : 'timed_out');
    assert.equal(lines.at(-1).cancelled, true);
    assert.ok(lines.some(line => line.kind === 'event' && line.type === 'tool.completed'));
    assert.ok(!lines.some(line => line.kind === 'result'));
    console.log(JSON.stringify({ revision: null, lines }));
  } else {
    assert.equal(lines.at(-1).kind, 'result', JSON.stringify(lines.at(-1)));
    const receipt = lines.at(-1).revisionReceipt;
    assert.equal(receipt.attempt_id, input.lease.executionId);
    assert.equal(receipt.workspace_id, input.lease.workspaceId);
    console.log(JSON.stringify({ revision: receipt.revision_id, lines }));
  }
} finally {
  child.kill(); await exited;
  model.closeAllConnections();
  await new Promise<void>(resolve => model.close(() => resolve()));
  await rm(root, { recursive: true, force: true });
}
