import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { BrokerSandboxClient } from './broker-sandbox.ts';

const lease = () => ({ runId: 'r', workspaceId: 'w', attemptId: 'a'.repeat(32), grant: 'a.b.c', deadline: Math.floor(Date.now() / 1000) + 120 });
async function server(handler: (req: IncomingMessage, res: ServerResponse) => void) {
  const instance = createServer(handler);
  await new Promise<void>(resolve => instance.listen(0, '127.0.0.1', resolve));
  return { origin: `http://127.0.0.1:${(instance.address() as any).port}`,
    close: async () => { instance.closeAllConnections(); await new Promise<void>(resolve => instance.close(() => resolve())); } };
}
const json = (res: ServerResponse, value: unknown) => { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(value)); };

test('broker origin and lease validation never reveal credentials', () => {
  for (const baseUrl of ['http://example.com', 'http://127.0.0.1/path', 'https://user:secret@example.com', 'https://example.com/?key=secret']) {
    assert.throws(() => new BrokerSandboxClient({ baseUrl, lease: lease() }), /^Error: Invalid broker origin$/);
  }
  assert.throws(() => new BrokerSandboxClient({ baseUrl: 'https://example.com', lease: { ...lease(), deadline: 1 } }), /Invalid broker lease/);
});

test('redirects, malformed data and oversized responses close the lease without replay', async () => {
  for (const failure of ['redirect', 'malformed', 'oversized']) {
    const binding = lease();
    let files = 0;
    const host = await server((req, res) => {
      if (req.method === 'GET') return json(res, { attempt_id: binding.attemptId, state: 'ready', deadline: binding.deadline });
      if (req.url!.endsWith('/release')) return json(res, { attempt_id: binding.attemptId, state: 'terminated' });
      files++;
      if (failure === 'redirect') { res.writeHead(302, { location: '/should-not-follow' }); res.end(); }
      else if (failure === 'malformed') json(res, { tool_call_id: 'wrong', outcome: { ok: true, data: {} } });
      else { res.setHeader('content-type', 'application/json'); res.end('x'.repeat(12 * 1024 * 1024 + 1)); }
    });
    try {
      const client = new BrokerSandboxClient({ baseUrl: host.origin, lease: binding });
      const id = await client.create('r', 'w');
      const request = { toolCallId: 'tool', operation: { op: 'glob' as const, pattern: '**', limit: 10 } };
      await assert.rejects(client.fileOperation(id, request), /outcome is unknown/);
      await assert.rejects(client.fileOperation(id, request), /uncertain/);
      assert.equal(files, 1);
      await client.destroy(id);
    } finally { await host.close(); }
  }
});

test('response timeout is bounded and cleanup uses an independent request', async () => {
  const binding = lease();
  const entered = Promise.withResolvers<void>();
  const host = await server((req, res) => {
    if (req.method === 'GET') json(res, { attempt_id: binding.attemptId, state: 'ready', deadline: binding.deadline });
    else if (req.url!.endsWith('/release')) json(res, { attempt_id: binding.attemptId, state: 'terminated' });
    else { res.setHeader('content-type', 'application/json'); res.write('{'); entered.resolve(); }
  });
  try {
    const client = new BrokerSandboxClient({ baseUrl: host.origin, lease: binding, timeoutMs: 200 });
    const id = await client.create('r', 'w');
    const started = Date.now();
    await assert.rejects(client.fileOperation(id, { toolCallId: 'tool', operation: { op: 'glob', pattern: '**', limit: 10 } }), /unknown/);
    assert.ok(Date.now() - started < 1500);
    await entered.promise;
    await client.destroy(id);
  } finally { await host.close(); }
});

test('failed acquisition releases the pre-provisioned lease and failed release can retry', async () => {
  const binding = lease();
  let releases = 0;
  const host = await server((req, res) => {
    if (req.method === 'GET') return json(res, { attempt_id: 'wrong', state: 'ready', deadline: binding.deadline });
    releases++;
    if (releases === 1) { res.statusCode = 503; res.end(); }
    else json(res, { attempt_id: binding.attemptId, state: 'terminated' });
  });
  try {
    const client = new BrokerSandboxClient({ baseUrl: host.origin, lease: binding });
    await assert.rejects(client.create('r', 'w'), /release is unconfirmed/);
    assert.equal(releases, 1);
    await client.destroy(binding.attemptId);
    await client.destroy(binding.attemptId);
    assert.equal(releases, 2);
    await assert.rejects(client.create('r', 'w'), /closed/);
  } finally { await host.close(); }
});

test('tool abort closes dispatch but cannot cancel independent release', async () => {
  const binding = lease();
  const entered = Promise.withResolvers<void>();
  const host = await server((req, res) => {
    if (req.method === 'GET') json(res, { attempt_id: binding.attemptId, state: 'ready', deadline: binding.deadline });
    else if (req.url!.endsWith('/release')) json(res, { attempt_id: binding.attemptId, state: 'terminated' });
    else { res.setHeader('content-type', 'application/json'); res.write('{'); entered.resolve(); }
  });
  try {
    const client = new BrokerSandboxClient({ baseUrl: host.origin, lease: binding });
    const id = await client.create('r', 'w');
    const controller = new AbortController();
    const pending = client.fileOperation(id, { toolCallId: 'tool', operation: { op: 'glob', pattern: '**', limit: 10 } }, controller.signal);
    await entered.promise;
    controller.abort();
    await assert.rejects(pending, /unknown/);
    await client.destroy(id);
  } finally { await host.close(); }
});
