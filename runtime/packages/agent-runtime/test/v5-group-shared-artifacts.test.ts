import { mkdir, mkdtemp, rm, unlink, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { captureGroupSharedBaseline } from '../src/group-shared-artifacts.ts';

const roots: string[] = [];
afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe('Group shared directory finalization', () => {
  it('returns files added or modified since the baseline and skips unchanged or deleted ones', async () => {
    const shared = await mkdtemp(join(tmpdir(), 'workdude-group-shared-'));
    roots.push(shared);
    await writeFile(join(shared, 'unchanged.txt'), 'same');
    await writeFile(join(shared, 'edited.md'), 'v1');
    await writeFile(join(shared, 'removed.txt'), 'gone');
    const finalizer = await captureGroupSharedBaseline(shared);

    await mkdir(join(shared, 'reports'));
    await writeFile(join(shared, 'reports', 'group-note.md'), 'GROUP-ARTIFACT-OK\n');
    await writeFile(join(shared, 'edited.md'), 'v2 longer');
    const later = new Date(Date.now() + 5_000);
    await utimes(join(shared, 'edited.md'), later, later);
    await unlink(join(shared, 'removed.txt'));

    const changed = await finalizer.changedFiles();
    expect(
      changed.map(({ relativePath, mediaType, artifactType, title }) => [
        relativePath,
        mediaType,
        artifactType,
        title,
      ]),
    ).toEqual([
      ['edited.md', 'text/markdown', 'document', 'edited.md'],
      ['reports/group-note.md', 'text/markdown', 'document', 'group-note.md'],
    ]);
  });
});

it('preserves pre-interruption changes when a new execution captures the same Run baseline', async () => {
  const root = await mkdtemp(join(tmpdir(), 'workdude-group-recovery-'));
  roots.push(root);
  const shared = join(root, 'shared');
  await mkdir(shared);
  await writeFile(join(shared, 'existing.txt'), 'unchanged');
  const baseline = join(root, 'baselines', 'run.json');
  await captureGroupSharedBaseline(shared, baseline);
  await writeFile(join(shared, 'deliverable.txt'), 'created before interruption');
  const recovered = await captureGroupSharedBaseline(shared, baseline);
  expect((await recovered.changedFiles()).map((file) => file.relativePath)).toEqual(['deliverable.txt']);
  const nextRun = await captureGroupSharedBaseline(shared, join(root, 'baselines', 'next-run.json'));
  expect(await nextRun.changedFiles()).toEqual([]);
});
