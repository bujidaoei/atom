import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LocalSandboxClient } from './local-sandbox.ts';
import { createWorkspaceTools, createProductPiReadTool, createPolicyBoundPiEditTool, createPolicyBoundPiWriteTool } from '../packages/agent-runtime/src/workspace-tools.ts';
import { createReadToolDefinition, createEditToolDefinition, createWriteToolDefinition } from '../packages/agent-runtime/src/pi-runtime-loader.mjs';

test('real write/read/edit/glob/grep agree across independent workspaces', async () => {
  const root = await mkdtemp(join(tmpdir(), 'atom-workspace-'));
  try {
    for (const name of ['one', 'two']) {
      const workspacePath = join(root, name);
      const sandbox = new LocalSandboxClient({ resolveWorkspace: () => workspacePath });
      const sandboxId = await sandbox.create(name, name);
      const options = { runId: name, sandboxId, workspacePath, sandbox, approvals: { request: async () => 'approved' as const } };
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
      await assert.rejects(sandbox.writeFile(sandboxId, { toolCallId: 'bad', path: '../escape', content: 'bad' }));
      await symlink(root, join(workspacePath, 'outside'), process.platform === 'win32' ? 'junction' : 'dir');
      await assert.rejects(sandbox.writeFile(sandboxId, { toolCallId: 'bad', path: 'outside/escape', content: 'bad' }));
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
