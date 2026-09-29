import fs from 'node:fs';
import { access, mkdir, readdir, rename, rm, stat } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';

import git from 'isomorphic-git';
import http from 'isomorphic-git/http/node';
import type { GitHttpRequest, HttpClient } from 'isomorphic-git/http/node';

import type { V3Project } from '../../product-contracts/src/v3.ts';

export interface V3PreparedProjectResult {
  workspacePath: string;
}

export interface V3ProjectPreparationFailure {
  state: 'error';
  errorCode: string;
  errorDetail: string;
}

interface V3ProjectPreparerOptions {
  managedRoot: string;
  workspacePath: string;
  allowedGitHosts?: readonly string[];
  clone?: (input: { url: string; branch?: string; directory: string }) => Promise<void>;
  onDiagnostic?: (diagnostic: { errorName: string; errorCode: string | null }) => void;
}

function isInside(parent: string, candidate: string): boolean {
  const pathFromParent = relative(parent, candidate);
  return pathFromParent === '' || (!pathFromParent.startsWith('..') && !isAbsolute(pathFromParent));
}

function validatedGitUrl(
  locator: string,
  allowedHosts: readonly string[],
  allowSmartHttpServiceQuery = false,
): string {
  const url = new URL(locator);
  const smartHttpServiceQuery =
    allowSmartHttpServiceQuery &&
    url.pathname.endsWith('/info/refs') &&
    url.searchParams.size === 1 &&
    url.searchParams.get('service') === 'git-upload-pack';
  if (
    url.protocol !== 'https:' ||
    url.username ||
    url.password ||
    url.port ||
    (url.search && !smartHttpServiceQuery) ||
    url.hash
  ) {
    throw new Error('git-url-not-allowed');
  }
  const host = url.hostname.toLocaleLowerCase('en-US');
  if (!allowedHosts.includes(host)) throw new Error('git-host-not-allowed');
  return url.href;
}

function restrictedHttpClient(allowedHosts: readonly string[]): HttpClient {
  return {
    async request(request: GitHttpRequest) {
      const url = validatedGitUrl(request.url, allowedHosts, true);
      const response = await http.request({
        ...request,
        url,
        fetchOptions: {
          ...request.fetchOptions,
          followRedirects: false,
          timeout: 60_000,
        },
      });
      if (response.url) validatedGitUrl(response.url, allowedHosts, true);
      return response;
    },
  };
}

function sourceDirectoryName(position: number, displayName: string): string {
  const slug = displayName
    .toLocaleLowerCase('en-US')
    .replace(/[^a-z0-9._-]+/gu, '-')
    .replace(/^-+|-+$/gu, '')
    .slice(0, 80);
  return `${String(position + 1).padStart(2, '0')}-${slug || 'repository'}`;
}

async function removeTree(path: string): Promise<void> {
  await rm(path, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
}

async function renameWithWindowsRetry(from: string, to: string): Promise<void> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await rename(from, to);
      return;
    } catch (cause) {
      const code =
        typeof cause === 'object' && cause !== null && 'code' in cause ? String(cause.code) : undefined;
      if (!code || !['EACCES', 'EBUSY', 'EPERM'].includes(code) || attempt >= 20) throw cause;
      await new Promise<void>((resolveDelay) => setTimeout(resolveDelay, 100));
    }
  }
}

async function reconcileInterruptedPreparation(
  managedRoot: string,
  workspacePath: string,
  projectId: string,
): Promise<void> {
  await mkdir(managedRoot, { recursive: true });
  const entries = await readdir(managedRoot);
  const stagingPrefix = `.prepare-${projectId}-`;
  const previousPrefix = `.previous-${projectId}-`;
  const staging = entries.filter((entry) => entry.startsWith(stagingPrefix));
  const previous = entries.filter((entry) => entry.startsWith(previousPrefix));
  const workspaceExists = await access(workspacePath)
    .then(() => true)
    .catch(() => false);
  let restored: string | undefined;
  if (!workspaceExists && previous.length) {
    const candidates = await Promise.all(
      previous.map(async (entry) => ({ entry, modifiedAt: (await stat(join(managedRoot, entry))).mtimeMs })),
    );
    restored = candidates.sort((left, right) => right.modifiedAt - left.modifiedAt)[0]?.entry;
    if (restored) await renameWithWindowsRetry(join(managedRoot, restored), workspacePath);
  }
  await Promise.all(
    [...staging, ...previous.filter((entry) => entry !== restored)].map((entry) =>
      removeTree(join(managedRoot, entry)),
    ),
  );
}

async function defaultClone(
  input: { url: string; branch?: string; directory: string },
  allowedHosts: readonly string[],
): Promise<void> {
  await git.clone({
    fs,
    http: restrictedHttpClient(allowedHosts),
    dir: input.directory,
    url: input.url,
    ...(input.branch ? { ref: input.branch } : {}),
    singleBranch: true,
    depth: 1,
    noTags: true,
  });
}

export async function prepareV3ProjectSources(
  project: V3Project,
  options: V3ProjectPreparerOptions,
): Promise<V3PreparedProjectResult | V3ProjectPreparationFailure> {
  const managedRoot = resolve(options.managedRoot);
  const workspacePath = resolve(options.workspacePath);
  if (!isInside(managedRoot, workspacePath) || workspacePath === managedRoot) {
    throw new Error('Project workspace escaped the managed root');
  }
  const gitSources = project.sources.filter(
    (source): source is typeof source & { locator: string } =>
      source.kind === 'git_repository' && Boolean(source.locator),
  );
  if (!gitSources.length) return { workspacePath };

  const allowedHosts = options.allowedGitHosts ?? ['github.com', 'gitlab.com', 'bitbucket.org'];
  const clone = options.clone ?? ((input) => defaultClone(input, allowedHosts));
  const stagingPath = join(
    managedRoot,
    `.prepare-${project.id}-${project.preparation.attempt}-${crypto.randomUUID()}`,
  );
  const previousPath = join(managedRoot, `.previous-${project.id}-${crypto.randomUUID()}`);
  let previousMoved = false;
  try {
    await reconcileInterruptedPreparation(managedRoot, workspacePath, project.id);
    await mkdir(stagingPath, { recursive: false });
    for (const source of gitSources) {
      const url = validatedGitUrl(source.locator, allowedHosts);
      const directory = join(stagingPath, sourceDirectoryName(source.position, source.displayName));
      await clone({ url, ...(source.branch ? { branch: source.branch } : {}), directory });
    }

    try {
      await access(workspacePath);
      await renameWithWindowsRetry(workspacePath, previousPath);
      previousMoved = true;
    } catch {
      // A first preparation has no previous workspace to preserve.
    }
    await renameWithWindowsRetry(stagingPath, workspacePath);
    if (previousMoved) await removeTree(previousPath);
    return { workspacePath };
  } catch (cause) {
    options.onDiagnostic?.({
      errorName: cause instanceof Error ? cause.name : 'UnknownError',
      errorCode:
        typeof cause === 'object' && cause !== null && 'code' in cause && typeof cause.code === 'string'
          ? cause.code
          : null,
    });
    await removeTree(stagingPath).catch(() => undefined);
    if (previousMoved) {
      await renameWithWindowsRetry(previousPath, workspacePath).catch(() => undefined);
    }
    const code =
      cause instanceof Error && /^(?:git-url|git-host)-not-allowed$/u.test(cause.message)
        ? cause.message
        : 'git-clone-failed';
    return {
      state: 'error',
      errorCode: code,
      errorDetail:
        code === 'git-host-not-allowed'
          ? 'Git host is not allowed. Use GitHub, GitLab, or Bitbucket, then retry.'
          : code === 'git-url-not-allowed'
            ? 'Git URL must use HTTPS without embedded credentials, query parameters, fragments, or a custom port.'
            : 'Git repository could not be prepared. Check the URL and branch, then retry.',
    };
  }
}
