import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BrokerSandboxClient } from '../src/broker-sandbox.ts';
import { ExecutionClient } from '../src/execution-client.ts';

const input = JSON.parse(readFileSync(0, 'utf8'));
const lease = input.lease;
const sandbox = new BrokerSandboxClient({ baseUrl: input.brokerOrigin, lease });
const completion = new ExecutionClient({ baseUrl: input.executionOrigin, lease });
const id = await sandbox.create(lease.runId, lease.workspaceId);
try {
  await sandbox.fileOperation(id, { toolCallId: 'node-write', operation: {
    op: 'write', path: 'result.txt', content: 'actual coordinator output',
  } });
  const receipt = await completion.complete();
  assert.equal(receipt.attempt_id, lease.executionId);
  assert.equal(receipt.workspace_id, lease.workspaceId);
  assert.match(receipt.artifact_key, /^[a-f0-9]{64}$/);
  console.log(JSON.stringify({ revision: receipt.revision_id }));
} finally {
  await sandbox.destroy(id);
}
