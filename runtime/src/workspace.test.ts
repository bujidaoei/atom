import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LocalSandboxClient } from './local-sandbox.ts';
import { createWorkspaceTools, createPolicyBoundPiEditTool, createPolicyBoundPiWriteTool } from '../packages/agent-runtime/src/workspace-tools.ts';
import { createEditToolDefinition, createWriteToolDefinition } from '../packages/agent-runtime/src/pi-runtime-loader.mjs';

test('real write/read/edit/glob/grep agree across independent workspaces', async () => {
  const root = await mkdtemp(join(tmpdir(), 'atom-workspace-'));
  try {
    for (const name of ['one', 'two']) {
      const workspacePath = join(root, name);
      const sandbox = new LocalSandboxClient({ resolveWorkspace: () => workspacePath });
      const sandboxId = await sandbox.create(name, name);
      const options = { runId: name, sandboxId, workspacePath, sandbox, approvals: { request: async () => 'approved' as const } };
      const tools = [...createWorkspaceTools(options), createPolicyBoundPiWriteTool(options, createWriteToolDefinition), createPolicyBoundPiEditTool(options, createEditToolDefinition)];
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
      await assert.rejects(sandbox.writeFile(sandboxId, { toolCallId: 'bad', path: '../escape', content: 'bad' }));
      await symlink(root, join(workspacePath, 'outside'), process.platform === 'win32' ? 'junction' : 'dir');
      await assert.rejects(sandbox.writeFile(sandboxId, { toolCallId: 'bad', path: 'outside/escape', content: 'bad' }));
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
