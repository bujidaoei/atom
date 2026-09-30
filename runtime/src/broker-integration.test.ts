import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { BrokerSandboxClient } from './broker-sandbox.ts';
import { createWorkspaceTools, createProductPiReadTool, createPolicyBoundPiWriteTool, createPolicyBoundPiEditTool } from '../packages/agent-runtime/src/workspace-tools.ts';
import { createReadToolDefinition, createWriteToolDefinition, createEditToolDefinition } from '../packages/agent-runtime/src/pi-runtime-loader.mjs';

test('actual Pi file tools execute through HTTP broker and release the real worker', { skip: !process.env.ATOM_TEST_BROKER_LEASE }, async () => {
  const lease = JSON.parse(process.env.ATOM_TEST_BROKER_LEASE!);
  const sandbox = new BrokerSandboxClient({ baseUrl: process.env.ATOM_TEST_BROKER_ORIGIN!, lease });
  const id = await sandbox.create(lease.runId, lease.workspaceId);
  try {
    await assert.rejects(sandbox.create('other-run', lease.workspaceId), /scope mismatch/);
    await assert.rejects(sandbox.exec(id, { toolCallId: 'exec', command: 'touch unexpected' }), /does not authorize/);
    const workspacePath = resolve(tmpdir(), 'atom-broker-virtual-workspace');
    const options = { runId: lease.runId, sandboxId: id, workspacePath, sandbox, approvals: { request: async () => 'approved' as const } };
    const read = createProductPiReadTool({ workspacePath, attachments: [], workspace: options }, createReadToolDefinition);
    const tools = [...createWorkspaceTools(options, read), createPolicyBoundPiWriteTool(options, createWriteToolDefinition), createPolicyBoundPiEditTool(options, createEditToolDefinition)];
    const call = async (name: string, args: unknown) => {
      // A repeated tool call identifier must not conflate Edit's read and write.
      const result = await tools.find(tool => tool.name === name)!.execute('shared-tool-call', args as never);
      assert.notEqual(result.isError, true);
      return JSON.stringify(result);
    };
    await call('write', { path: 'nested/app.txt', content: 'hello 中文' });
    assert.match(await call('read_file', { path: 'nested/app.txt' }), /hello 中文/);
    await call('edit', { path: 'nested/app.txt', edits: [{ oldText: 'hello', newText: 'verified' }] });
    assert.match(await call('read_file', { path: 'nested/app.txt' }), /verified 中文/);
    assert.match(await call('glob', { pattern: '**/*.txt' }), /nested\/app.txt/);
    assert.match(await call('grep', { pattern: 'verified' }), /verified/);
    await assert.rejects(sandbox.fileOperation(id, { toolCallId: 'cas', operation: { op: 'write', path: 'nested/app.txt', content: 'wrong', expected_sha256: 'f'.repeat(64) } }), /file_conflict/);
    assert.match(await call('read_file', { path: 'nested/app.txt' }), /verified/);
  } finally { await sandbox.destroy(id); }
  await sandbox.destroy(id);
  await assert.rejects(sandbox.fileOperation(id, { toolCallId: 'late', operation: { op: 'glob', pattern: '**', limit: 10 } }), /closed/);
});
