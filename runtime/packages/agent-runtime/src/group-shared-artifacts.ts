import { randomUUID } from 'node:crypto';
import { link, lstat, mkdir, readFile, readdir, unlink, writeFile } from 'node:fs/promises';
import { basename, dirname, join, relative } from 'node:path';

import {
  inferSessionArtifactType,
  sessionArtifactMediaType,
  type SessionArtifactFile,
} from './session-artifacts.ts';

/**
 * Official QoderWake Group finalization: the Conversation `shared` directory is the
 * Run's artifact output root. A baseline is captured when the Run starts; at the end
 * every file added or modified under it becomes a `finalization` artifact shown in
 * the `共享目录` partition. Deleted files are not artifacts.
 */

/** Directory a Group participant sees as `shared/` inside its workspace. */
export const GROUP_SHARED_DIRECTORY_NAME = 'shared';
const MAX_TRACKED_FILES = 5_000;

type SharedDirectorySnapshot = Map<string, string>;

async function snapshot(root: string): Promise<SharedDirectorySnapshot> {
  const files: SharedDirectorySnapshot = new Map();
  const pending = [root];
  while (pending.length && files.size < MAX_TRACKED_FILES) {
    const directory = pending.pop()!;
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        pending.push(path);
      } else if (entry.isFile()) {
        const info = await lstat(path).catch(() => undefined);
        if (info?.isFile()) files.set(path, `${info.size}:${info.mtimeMs}`);
        if (files.size >= MAX_TRACKED_FILES) break;
      }
    }
  }
  return files;
}

export interface GroupSharedArtifactFinalizer {
  /** Files added or modified under the shared directory since the baseline. */
  changedFiles(): Promise<SessionArtifactFile[]>;
}

export async function captureGroupSharedBaseline(
  sharedPath: string,
  persistedBaselinePath?: string,
): Promise<GroupSharedArtifactFinalizer> {
  let baseline = await snapshot(sharedPath);
  if (persistedBaselinePath) {
    await mkdir(dirname(persistedBaselinePath), { recursive: true });
    const temporary = `${persistedBaselinePath}.${randomUUID()}.tmp`;
    try {
      // Publish only a complete baseline, without replacing one from an earlier lease.
      await writeFile(temporary, JSON.stringify([...baseline]), { flag: 'wx' });
      await link(temporary, persistedBaselinePath);
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code !== 'EEXIST') throw cause;
      const stored: unknown = JSON.parse(await readFile(persistedBaselinePath, 'utf8'));
      if (
        !Array.isArray(stored) ||
        stored.length > MAX_TRACKED_FILES ||
        stored.some(
          (entry) =>
            !Array.isArray(entry) || entry.length !== 2 || entry.some((value) => typeof value !== 'string'),
        )
      )
        throw new Error('Invalid shared directory baseline', { cause });
      // Stored paths are comparison keys only. Files returned below come exclusively
      // from the fresh directory scan and remain subject to the artifact reader.
      baseline = new Map(stored as Array<[string, string]>);
    } finally {
      await unlink(temporary).catch((cause: NodeJS.ErrnoException) => {
        if (cause.code !== 'ENOENT') throw cause;
      });
    }
  }
  return {
    async changedFiles() {
      const current = await snapshot(sharedPath);
      return [...current]
        .filter(([path, signature]) => baseline.get(path) !== signature)
        .map(([path]) => ({
          absolutePath: path,
          relativePath: relative(sharedPath, path).replaceAll('\\', '/'),
          mediaType: sessionArtifactMediaType(path),
          artifactType: inferSessionArtifactType(path),
          title: basename(path),
          description: null,
          toolName: null,
        }))
        .sort((left, right) => left.relativePath.localeCompare(right.relativePath));
    },
  };
}

/**
 * Maps a sandbox path from `qoderwake messages send --file` to the host root that owns
 * it: `/workspace/...` or a relative path is the participant workspace, and `shared/...`
 * is the Group shared directory. Containment is enforced by the reader.
 */
export function resolveGroupSandboxFile(
  filePath: string,
  roots: { workspacePath: string; sharedPath?: string | undefined },
): { root: string; relativePath: string } {
  const normalized = filePath.trim().replaceAll('\\', '/');
  const relativePath =
    normalized === '/workspace' || normalized.startsWith('/workspace/')
      ? normalized.slice('/workspace'.length).replace(/^\/+/u, '')
      : normalized;
  const sharedPrefix = `${GROUP_SHARED_DIRECTORY_NAME}/`;
  if (roots.sharedPath && relativePath.startsWith(sharedPrefix)) {
    return { root: roots.sharedPath, relativePath: relativePath.slice(sharedPrefix.length) };
  }
  return { root: roots.workspacePath, relativePath };
}

export const GROUP_SHARED_DIRECTORY_GUIDANCE = [
  '## Group shared directory',
  `\`${GROUP_SHARED_DIRECTORY_NAME}/\` in your workspace is this Group conversation's shared directory, visible to every member.`,
  `Write deliverables other members or the user should receive into \`${GROUP_SHARED_DIRECTORY_NAME}/\`; files added or changed there when your Run ends are listed as the conversation's artifacts under 共享目录.`,
  'Keep scratch and intermediate files in the rest of your workspace.',
].join('\n');
