import { mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createV3GroupMessagingSandbox } from '../src/v3-group-messaging.ts';
import { createSandboxExecTool } from '../src/sandbox-tool.ts';
import { compileV3ToolPolicy } from '../src/v3-policy.ts';

const roots: string[] = [];
afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'workdude-sop-'));
  roots.push(root);
  const exec = vi.fn();
  const sandbox = createV3GroupMessagingSandbox({
    sandbox: { create: vi.fn(), exec, destroy: vi.fn() },
    conversationId: 'conversation',
    sopWorkspacePath: root,
    onDelivery: vi.fn(),
    onList: vi.fn(),
    onGoalGet: vi.fn(),
    onGoalMutate: vi.fn(),
  });
  return {
    root,
    exec,
    sandbox,
    run: (command: string, signal?: AbortSignal) =>
      sandbox.exec('sandbox', { command, toolCallId: 'sop', timeoutMs: 1000 }, signal),
  };
}

describe('observed Group SOP authoring', () => {
  it.each(['allow', 'deny'] as const)(
    'applies effective %s policy at the real tool boundary',
    async (decision) => {
      const { root, sandbox } = await fixture();
      const approvals = { request: vi.fn() };
      const tool = createSandboxExecTool({
        runId: 'run',
        sandboxId: 'sandbox',
        workspacePath: root,
        sandbox,
        approvals,
        policy: compileV3ToolPolicy(root, [{ id: 'policy', version: 1, decisions: { Bash: decision } }]),
      });
      const result = await tool.execute(
        'init',
        {
          command: 'qoderwake sop init guarded.json --skill-id example --version 1.0.0',
        },
        undefined,
      );
      expect(approvals.request).not.toHaveBeenCalled();
      if (decision === 'allow') {
        expect(result.content).toEqual([
          { type: 'text', text: `Created SOP template ${join(root, 'guarded.json')}.` },
        ]);
        expect(JSON.parse(await readFile(join(root, 'guarded.json'), 'utf8')).skillId).toBe('example');
      } else {
        expect(result.content).toEqual([{ type: 'text', text: '权限策略禁止执行该沙箱命令。' }]);
        await expect(readFile(join(root, 'guarded.json'))).rejects.toThrow();
      }
    },
  );
  it('initializes the exact official JSON and validates an edited file without publishing', async () => {
    const { root, run, exec } = await fixture();
    const initialized = await run(
      'qoderwake sop init "my SOP.json" --skill-id contract-shape-probe --version 1.0.0',
    );
    expect(initialized).toMatchObject({
      exitCode: 0,
      stdout: `Created SOP template ${join(root, 'my SOP.json')}.`,
    });
    const template = JSON.parse(await readFile(join(root, 'my SOP.json'), 'utf8'));
    expect(template).toEqual({
      skillId: 'contract-shape-probe',
      version: '1.0.0',
      displayName: 'contract-shape-probe',
      template: {
        format: 'qoder-sop-template/v1',
        description: 'Follow the contract-shape-probe SOP',
        body: '# contract-shape-probe\n\nDescribe the SOP here.\n',
      },
    });
    template.displayName = '协作规则';
    template.template.body = '# 协作规则\n\n负责人分派、成员回复、负责人检查。\n';
    await writeFile(join(root, 'my SOP.json'), JSON.stringify(template));
    expect(await run('qoderwake sop validate "my SOP.json"')).toMatchObject({
      exitCode: 0,
      stdout: 'SOP template contract-shape-probe@1.0.0 is valid.',
    });
    expect(exec).not.toHaveBeenCalled();
  });

  it('does not overwrite an existing file, including on retried init', async () => {
    const { root, run } = await fixture();
    await writeFile(join(root, 'existing.json'), 'retain this');
    expect(
      (await run('qoderwake sop init existing.json --skill-id example --version 1.0.0')).exitCode,
    ).not.toBe(0);
    expect(await readFile(join(root, 'existing.json'), 'utf8')).toBe('retain this');
  });

  it.each([
    'qoderwake sop init ../escape.json --skill-id example --version 1.0.0',
    'qoderwake sop init bad.json --skill-id ../bad --version 1.0.0',
    'qoderwake sop init bad.json --skill-id example --version latest',
    'qoderwake sop init bad.json --skill-id example --version 1.0.0-01',
    'qoderwake sop init bad.json:stream --skill-id example --version 1.0.0',
    'qoderwake sop init bad.json --skill-id example --skill-id duplicate --version 1.0.0',
    'qoderwake sop init bad.json --skill-id example --version 1.0.0; echo injected',
    'qoderwake sop validate good.json --unknown',
  ])('rejects invalid commands without executing a shell: %s', async (command) => {
    const { root, run, exec } = await fixture();
    expect((await run(command)).exitCode).not.toBe(0);
    expect(exec).not.toHaveBeenCalled();
    await expect(readFile(join(root, 'bad.json'))).rejects.toThrow();
  });

  it.each([
    'not json',
    '{}',
    '{"secret":"sensitive-content"}',
    JSON.stringify({
      skillId: 'example',
      version: '1.0.0',
      displayName: 'Example',
      template: {
        format: 'qoder-sop-template/v1',
        description: 'Example',
        body: '# Example',
        parameters: {},
      },
    }),
  ])('rejects malformed or unsupported templates without disclosing their contents', async (content) => {
    const { root, run } = await fixture();
    await writeFile(join(root, 'invalid.json'), content);
    const result = await run('qoderwake sop validate invalid.json');
    expect(result.exitCode).not.toBe(0);
    expect(result.stderr).not.toContain('sensitive-content');
  });

  it('rejects directory junction escape and honors cancellation', async () => {
    const { root, run } = await fixture();
    const outside = await mkdtemp(join(tmpdir(), 'workdude-sop-outside-'));
    roots.push(outside);
    await symlink(outside, join(root, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
    expect(
      (await run('qoderwake sop init linked/escape.json --skill-id example --version 1.0.0')).exitCode,
    ).not.toBe(0);
    await expect(readFile(join(outside, 'escape.json'))).rejects.toThrow();
    const controller = new AbortController();
    controller.abort();
    await expect(
      run('qoderwake sop init cancelled.json --skill-id example --version 1.0.0', controller.signal),
    ).rejects.toThrow();
    await expect(readFile(join(root, 'cancelled.json'))).rejects.toThrow();
  });
});
