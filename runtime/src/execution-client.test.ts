import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { ExecutionClient } from './execution-client.ts';

const lease = () => ({ executionId: 'execution', workspaceId: 'workspace', attemptId: 'a'.repeat(32),
  grantId: 'grant', completionGrant: 'a.b.c', deadline: Math.floor(Date.now() / 1000) + 120 });

test('execution origin and binding validation rejects unsafe configuration', () => {
  for (const baseUrl of ['http://example.com', 'http://0x7f000001', 'http://127.1', 'https://user:secret@example.com', 'https://example.com/?', 'https://example.com/#', 'https://example.com/endpoint']) {
    assert.throws(() => new ExecutionClient({ baseUrl, lease: lease() }), /Invalid execution/);
  }
});

test('real protocol failures never become completion and are not replayed', async () => {
  for (const mode of ['redirect', 'scope', 'receipt', 'missing_receipt', 'cancelled', 'oversize', 'slow']) {
    const binding = lease();
    let calls = 0;
    const server = createServer((req, res) => {
      calls++;
      assert.equal(req.url, '/v1/executions/complete');
      assert.equal(req.headers.authorization, `Bearer ${binding.completionGrant}`);
      if (mode === 'slow') return;
      if (mode === 'redirect') { res.writeHead(307, { location: '/forbidden' }); res.end(); return; }
      res.setHeader('content-type', 'application/json');
      if (mode === 'oversize') { res.end('x'.repeat(16385)); return; }
      // Deliberately synthetic protocol evidence, not a business success fixture.
      res.end(JSON.stringify({ attempt_id: mode === 'scope' ? 'other' : binding.executionId,
        workspace_id: binding.workspaceId, grant_id: binding.grantId, broker_attempt_id: binding.attemptId,
        deadline: binding.deadline, state: 'closed', termination_state: 'confirmed',
        outcome: mode === 'cancelled' ? 'cancelled' : 'succeeded', receipt: mode === 'missing_receipt' ? null : {
          attempt_id: binding.executionId, workspace_id: mode === 'receipt' ? 'other' : binding.workspaceId,
          revision_id: 'b'.repeat(32), artifact_key: 'c'.repeat(64), snapshot_revision: 'd'.repeat(64),
        } }));
    });
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      const client = new ExecutionClient({ baseUrl: `http://127.0.0.1:${(server.address() as any).port}`,
        lease: binding, timeoutMs: mode === 'slow' ? 50 : 3000 });
      await assert.rejects(client.complete(), /Execution/);
      assert.equal(calls, 1);
      assert.ok(!JSON.stringify(client).includes(binding.completionGrant));
    } finally {
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  }
});
