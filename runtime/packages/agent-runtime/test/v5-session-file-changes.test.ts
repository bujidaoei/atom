import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import type { SessionArtifactFile } from '../src/session-artifacts.ts';
import type { ToolDefinition } from '../src/pi-runtime-types.ts';
import { trackSessionFileChanges } from '../src/session-file-changes.ts';

const roots: string[] = [];
afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function harness() {
  const workspace = await mkdtemp(join(tmpdir(), 'workdude-file-changes-'));
  roots.push(workspace);
  const recorded: SessionArtifactFile[] = [];
  const sink = {
    conversationId: '00000000-0000-4000-8000-000000000001',
    recordProcessFile: async (file: SessionArtifactFile) => {
      recorded.push(file);
    },
    presentFile: async () => undefined,
  };
  let sequence = 0;
  const run = async (
    toolName: string,
    input: Record<string, unknown>,
    effect: () => Promise<unknown>,
    result: { isError?: boolean; details?: unknown } = {},
  ) => {
    const tool = {
      name: toolName,
      label: toolName,
      description: toolName,
      parameters: {},
      execute: async () => {
        await effect();
        if (result.isError) throw new Error('tool failed');
        return { content: [], details: result.details };
      },
    } as unknown as ToolDefinition;
    const [wrapped] = trackSessionFileChanges([tool], { workspacePath: workspace, sink });
    await wrapped!.execute(`call-${++sequence}`, input as never, undefined).catch(() => undefined);
  };
  return { workspace, recorded, run };
}

describe('session file change tracker', () => {
  it('records Write and Edit targets inside the workspace as process files', async () => {
    const { workspace, recorded, run } = await harness();
    await run('write', { path: 'notes/plan.md' }, async () => {
      await mkdir(join(workspace, 'notes'), { recursive: true });
      await writeFile(join(workspace, 'notes', 'plan.md'), 'plan');
    });
    await run('edit', { path: join(workspace, 'notes', 'plan.md') }, async () => undefined);
    expect(
      recorded.map(({ relativePath, toolName, mediaType }) => [relativePath, toolName, mediaType]),
    ).toEqual([
      ['notes/plan.md', 'Write', 'text/markdown'],
      ['notes/plan.md', 'Edit', 'text/markdown'],
    ]);
  });

  it('records a single cp/mv destination and ignores compound or failed commands', async () => {
    const { workspace, recorded, run } = await harness();
    await writeFile(join(workspace, 'a.txt'), 'a');
    await mkdir(join(workspace, 'out'));
    await run(
      'sandbox_exec',
      { command: 'cp a.txt /workspace/out' },
      () => writeFile(join(workspace, 'out', 'a.txt'), 'a'),
      { details: { exitCode: 0, timedOut: false } },
    );
    await run(
      'sandbox_exec',
      { command: 'mv "a.txt" b.txt' },
      () => writeFile(join(workspace, 'b.txt'), 'a'),
      { details: { exitCode: 0, timedOut: false } },
    );
    await run(
      'sandbox_exec',
      { command: 'cp a.txt c.txt && echo done' },
      () => writeFile(join(workspace, 'c.txt'), 'a'),
      { details: { exitCode: 0, timedOut: false } },
    );
    await run('sandbox_exec', { command: 'cp a.txt d.txt' }, () => writeFile(join(workspace, 'd.txt'), 'a'), {
      details: { exitCode: 1, timedOut: false },
    });
    expect(recorded.map(({ relativePath, toolName }) => [relativePath, toolName])).toEqual([
      ['out/a.txt', 'Bash'],
      ['b.txt', 'Bash'],
    ]);
  });

  it('ignores failed tools, missing files and paths outside the workspace', async () => {
    const { workspace, recorded, run } = await harness();
    await run('write', { path: 'x.txt' }, () => writeFile(join(workspace, 'x.txt'), 'x'), { isError: true });
    await run('write', { path: 'missing.txt' }, async () => undefined);
    await run('write', { path: '../escape.txt' }, async () => undefined);
    await run('sandbox_exec', { command: 'cp /etc/passwd /tmp/p' }, async () => undefined, {
      details: { exitCode: 0, timedOut: false },
    });
    expect(recorded).toEqual([]);
  });
});
