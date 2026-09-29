import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import fs from 'node:fs';
import git from 'isomorphic-git';

import { afterEach, describe, expect, it, vi } from 'vitest';

import type { V3Project } from '../../product-contracts/src/v3.ts';
import { prepareV3ProjectSources } from '../src/v3-project-preparation.ts';

const roots: string[] = [];

function project(locator = 'https://github.com/octocat/Hello-World.git'): V3Project {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    ownerWakerId: null,
    name: 'Prepared Project',
    summary: '',
    visibility: 'workspace',
    availability: 'unknown',
    preparation: {
      state: 'initializing',
      attempt: 1,
      errorCode: null,
      errorDetail: null,
      updatedAt: '2026-08-18T00:00:00.000Z',
    },
    sources: [
      {
        id: '22222222-2222-4222-8222-222222222222',
        kind: 'git_repository',
        workspaceReferenceId: null,
        locator,
        branch: 'master',
        displayName: 'Hello World',
        availability: 'unknown',
        position: 0,
      },
    ],
    version: 1,
    createdAt: '2026-08-18T00:00:00.000Z',
    updatedAt: '2026-08-18T00:00:00.000Z',
  };
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe('V3 Project source preparation', () => {
  it.skipIf(process.env.WORKDUDE_PROJECT_LIVE_CLONE !== '1')(
    'clones the real remote HEAD when no branch is supplied',
    async () => {
      const root = await mkdtemp(join(tmpdir(), 'workdude-v5-live-project-'));
      roots.push(root);
      const value = project('https://github.com/octocat/Hello-World');
      value.sources[0]!.branch = null;
      const workspacePath = join(root, 'project');
      await expect(prepareV3ProjectSources(value, { managedRoot: root, workspacePath })).resolves.toEqual({
        workspacePath,
      });
      const dir = join(workspacePath, '01-hello-world');
      expect(await git.currentBranch({ fs, dir })).toBe('master');
      expect(await readFile(join(dir, 'README'), 'utf8')).toContain('Hello World');
    },
    90_000,
  );

  it('prepares branchless Git sources instead of silently skipping them', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v5-default-branch-'));
    roots.push(root);
    const value = project();
    value.sources[0]!.branch = null;
    const clone = vi.fn(async ({ directory }: { directory: string }) => {
      await mkdir(directory, { recursive: true });
      await writeFile(join(directory, 'README.md'), 'remote HEAD', 'utf8');
    });
    const workspacePath = join(root, 'project');
    await expect(
      prepareV3ProjectSources(value, { managedRoot: root, workspacePath, clone }),
    ).resolves.toEqual({ workspacePath });
    expect(clone).toHaveBeenCalledOnce();
    expect(clone.mock.calls[0]?.[0]).not.toHaveProperty('branch');
    await expect(readFile(join(workspacePath, '01-hello-world', 'README.md'), 'utf8')).resolves.toBe(
      'remote HEAD',
    );
  });

  it('prepares Git sources in staging and atomically replaces the managed workspace', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-project-prepare-'));
    roots.push(root);
    const managedRoot = join(root, 'projects');
    const workspacePath = join(managedRoot, 'project-1');
    await mkdir(workspacePath, { recursive: true });
    await writeFile(join(workspacePath, 'previous.txt'), 'preserve until commit', 'utf8');
    const clone = vi.fn(async ({ directory }: { directory: string }) => {
      await mkdir(directory, { recursive: true });
      await writeFile(join(directory, 'README.md'), 'prepared', 'utf8');
    });

    await expect(prepareV3ProjectSources(project(), { managedRoot, workspacePath, clone })).resolves.toEqual({
      workspacePath,
    });
    expect(clone).toHaveBeenCalledWith(
      expect.objectContaining({
        url: 'https://github.com/octocat/Hello-World.git',
        branch: 'master',
      }),
    );
    expect(clone.mock.calls[0]?.[0].directory).toMatch(/[\\/]01-hello-world$/u);
    await expect(readFile(join(workspacePath, '01-hello-world', 'README.md'), 'utf8')).resolves.toBe(
      'prepared',
    );
    await expect(readdir(managedRoot)).resolves.toEqual(['project-1']);
  });

  it('preserves the last ready workspace and returns a redacted actionable clone failure', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-project-failure-'));
    roots.push(root);
    const managedRoot = join(root, 'projects');
    const workspacePath = join(managedRoot, 'project-1');
    await mkdir(workspacePath, { recursive: true });
    await writeFile(join(workspacePath, 'previous.txt'), 'ready', 'utf8');

    await expect(
      prepareV3ProjectSources(project(), {
        managedRoot,
        workspacePath,
        clone: async () => {
          throw new Error('credential=https://user:secret@example.invalid/private.git');
        },
      }),
    ).resolves.toEqual({
      state: 'error',
      errorCode: 'git-clone-failed',
      errorDetail: 'Git repository could not be prepared. Check the URL and branch, then retry.',
    });
    await expect(readFile(join(workspacePath, 'previous.txt'), 'utf8')).resolves.toBe('ready');
    expect((await readdir(managedRoot)).filter((name) => name.startsWith('.prepare-'))).toEqual([]);
  });

  it('restores an interrupted atomic swap and removes abandoned staging before retrying', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-project-recovery-'));
    roots.push(root);
    const managedRoot = join(root, 'projects');
    const workspacePath = join(managedRoot, 'project-1');
    const previous = join(managedRoot, `.previous-${project().id}-interrupted`);
    const abandoned = join(managedRoot, `.prepare-${project().id}-interrupted`);
    await Promise.all([mkdir(previous, { recursive: true }), mkdir(abandoned, { recursive: true })]);
    await writeFile(join(previous, 'last-ready.txt'), 'ready', 'utf8');
    await writeFile(join(abandoned, 'partial.txt'), 'partial', 'utf8');

    await prepareV3ProjectSources(project(), {
      managedRoot,
      workspacePath,
      clone: async () => {
        throw new Error('retry remains offline');
      },
    });

    await expect(readFile(join(workspacePath, 'last-ready.txt'), 'utf8')).resolves.toBe('ready');
    await expect(readdir(managedRoot)).resolves.toEqual(['project-1']);
  });

  it('rejects embedded credentials, query secrets, and non-allowlisted hosts before network access', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-project-host-'));
    roots.push(root);
    const managedRoot = join(root, 'projects');
    const clone = vi.fn();
    await expect(
      prepareV3ProjectSources(project('https://user:password@github.com/private/repo.git'), {
        managedRoot,
        workspacePath: join(managedRoot, 'project-1'),
        clone,
      }),
    ).resolves.toMatchObject({ state: 'error', errorCode: 'git-url-not-allowed' });
    await expect(
      prepareV3ProjectSources(project('https://github.com/private/repo.git?token=secret'), {
        managedRoot,
        workspacePath: join(managedRoot, 'project-2'),
        clone,
      }),
    ).resolves.toMatchObject({ state: 'error', errorCode: 'git-url-not-allowed' });
    await expect(
      prepareV3ProjectSources(project('https://example.com/private/repo.git'), {
        managedRoot,
        workspacePath: join(managedRoot, 'project-3'),
        clone,
      }),
    ).resolves.toMatchObject({ state: 'error', errorCode: 'git-host-not-allowed' });
    expect(clone).not.toHaveBeenCalled();
  });
});
