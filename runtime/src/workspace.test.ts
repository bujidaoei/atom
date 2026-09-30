import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LocalSandboxClient } from './local-sandbox.ts';
import { createWorkspaceTools, createProductPiReadTool, createPolicyBoundPiEditTool, createPolicyBoundPiWriteTool } from '../packages/agent-runtime/src/workspace-tools.ts';
import { createReadToolDefinition, createEditToolDefinition, createWriteToolDefinition } from '../packages/agent-runtime/src/pi-runtime-loader.mjs';
import { runWorkspaceFileOperation } from '../packages/agent-runtime/src/workspace-file-operation.ts';
import type { SandboxFileRequest } from '../packages/product-contracts/src/index.ts';

test('real write/read/edit/glob/grep agree across independent workspaces', async () => {
  const root = await mkdtemp(join(tmpdir(), 'atom-workspace-'));
  try {
    for (const name of ['one', 'two']) {
      const workspacePath = join(root, name);
      const sandbox = new LocalSandboxClient({ resolveWorkspace: () => workspacePath });
      const sandboxId = await sandbox.create(name, name);
      const structuredOnly = {
        create: sandbox.create.bind(sandbox), destroy: sandbox.destroy.bind(sandbox),
        fileOperation: sandbox.fileOperation.bind(sandbox),
        async exec(): Promise<never> { throw new Error('File wrappers must not call exec'); },
      };
      const options = { runId: name, sandboxId, workspacePath, sandbox: structuredOnly, approvals: { request: async () => 'approved' as const } };
      const resourceRead = createProductPiReadTool({ workspacePath, attachments: [], workspace: options }, createReadToolDefinition);
      const tools = [...createWorkspaceTools(options, resourceRead), createPolicyBoundPiWriteTool(options, createWriteToolDefinition), createPolicyBoundPiEditTool(options, createEditToolDefinition)];
      const call = async (tool: string, args: unknown) => {
        const result = await tools.find(t => t.name === tool)!.execute('roundtrip', args as never);
        assert.notEqual(result.isError, true, JSON.stringify(result));
        return JSON.stringify(result);
      };
      await call('write', { path: 'nested/app.txt', content: `hello ${name}` });
      assert.match(await call('read_file', { path: 'nested/app.txt' }), new RegExp(`hello ${name}`));
      await call('edit', { path: 'nested/app.txt', edits: [{ oldText: 'hello', newText: 'verified' }] });
      assert.equal(await readFile(join(workspacePath, 'nested/app.txt'), 'utf8'), `verified ${name}`);
      assert.match(await call('glob', { pattern: '**/*.txt' }), /nested\/app.txt/);
      assert.match(await call('grep', { pattern: 'verified' }), /verified/);
      assert.match(await call('grep', { pattern: 'verified', path: join(workspacePath, 'nested/app.txt') }), /verified/);
      assert.match(await call('glob', { pattern: join(workspacePath, 'nested/*.txt') }), /app.txt/);
      await call('write', { path: 'long.txt', content: Array.from({ length: 100 }, (_, i) => `line-${i + 1}`).join('\n') });
      const first = await call('read_file', { path: join(workspacePath, 'long.txt'), maxLines: 10 });
      assert.match(first, /offset=11/);
      assert.ok((tools.find(t => t.name === 'read_file')!.parameters as any).properties.offset);
      assert.match(await call('read_file', { path: join(workspacePath, 'long.txt'), offset: 11, limit: 2 }), /line-11/);
      assert.match(await call('read_file', { path: 'long.txt', offset: 13, limit: 2 }), /line-13/);
      await assert.rejects(call('read_file', { path: 'long.txt', offset: 2, startLine: 3 }), /Conflicting/);
      await assert.rejects(call('grep', { pattern: '.', path: root }), /traversal/);
      await assert.rejects(sandbox.fileOperation(sandboxId, { toolCallId: 'bad', operation: { op: 'write', path: '../escape', content: 'bad' } }));
      await symlink(root, join(workspacePath, 'outside'), process.platform === 'win32' ? 'junction' : 'dir');
      await assert.rejects(sandbox.fileOperation(sandboxId, { toolCallId: 'bad', operation: { op: 'write', path: 'outside/escape', content: 'bad' } }));
      await assert.rejects(call('grep', { pattern: '.', path: join(workspacePath, 'outside') }));
      const controller = new AbortController();
      controller.abort();
      await assert.rejects(sandbox.exec(sandboxId, { toolCallId: 'cancel', command: 'echo no' }, controller.signal));
      const running = new AbortController();
      const timer = setTimeout(() => running.abort(), 100);
      const before = Date.now();
      await sandbox.exec(sandboxId, { toolCallId: 'abort-tree', command: 'sleep 30 & wait' }, running.signal);
      clearTimeout(timer);
      assert.ok(Date.now() - before < 3000, 'shell descendants must not hold the pipe open after abort');
      await sandbox.destroy(sandboxId);
    }
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('real Pi Edit refuses a concurrent file change and reads only once', async () => {
  const root = await mkdtemp(join(tmpdir(), 'atom-edit-conflict-'));
  const local = new LocalSandboxClient({ resolveWorkspace: () => root });
  const sandboxId = await local.create('run', 'workspace');
  let reads = 0;
  try {
    await writeFile(join(root, 'file.txt'), 'original');
    const sandbox = {
      create: local.create.bind(local), destroy: local.destroy.bind(local),
      async exec(): Promise<never> { throw new Error('No shell dispatch'); },
      async fileOperation(id: string, request: SandboxFileRequest, signal?: AbortSignal) {
        if (request.operation.op === 'read_bytes') reads++;
        if (request.operation.op === 'write') {
          assert.ok(request.operation.expected_sha256);
          await writeFile(join(root, 'file.txt'), 'concurrent-change');
        }
        return local.fileOperation(id, request, signal);
      },
    };
    const options = { runId: 'run', sandboxId, workspacePath: root, sandbox, approvals: { request: async () => 'approved' as const } };
    const tool = createPolicyBoundPiEditTool(options, createEditToolDefinition);
    await assert.rejects(tool.execute('edit', { path: 'file.txt', edits: [{ oldText: 'original', newText: 'overwritten' }] }), /changed before conditional write/);
    assert.equal(reads, 1);
    assert.equal(await readFile(join(root, 'file.txt'), 'utf8'), 'concurrent-change');
  } finally {
    await local.destroy(sandboxId);
    await rm(root, { recursive: true, force: true });
  }
});

test('structured file responses require correlation and integrity, with no exec fallback', async () => {
  let executions = 0;
  const sandbox = { async create() { return 'sandbox'; }, async destroy() {},
    async exec(): Promise<never> { executions++; throw new Error('unexpected exec'); } };
  const options = { runId: 'r', sandboxId: 'sandbox', workspacePath: '.', sandbox, approvals: { request: async () => 'approved' as const } };
  await assert.rejects(runWorkspaceFileOperation(options, 'read', { op: 'read_bytes', path: 'x' }), /capability is unavailable/);
  for (const response of [
    { toolCallId: 'other', data: { text: 'wrong-call' } },
    { toolCallId: 'read', data: { base64: 'eA==', sha256: 'a'.repeat(64) } },
    { toolCallId: 'read', data: { base64: '!!!!', sha256: 'a'.repeat(64) } },
  ]) {
    await assert.rejects(runWorkspaceFileOperation({ ...options, sandbox: { ...sandbox, async fileOperation() { return response; } } },
      'read', { op: 'read_bytes', path: 'x' }));
  }
  assert.equal(executions, 0);
});
