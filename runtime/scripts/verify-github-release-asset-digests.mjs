import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

import { assertRemoteAssetDigests } from './desktop-release-contract.mjs';

async function localAssetIdentity(path) {
  const absolute = resolve(path);
  const info = await stat(absolute);
  if (!info.isFile() || info.size <= 0) {
    throw new Error(`Release asset must be a non-empty regular file: ${absolute}`);
  }
  const sha256 = await new Promise((resolveDigest, reject) => {
    const digest = createHash('sha256');
    const stream = createReadStream(absolute);
    stream.on('data', (chunk) => digest.update(chunk));
    stream.once('error', reject);
    stream.once('end', () => resolveDigest(digest.digest('hex')));
  });
  return { name: basename(absolute), sizeBytes: info.size, sha256 };
}

export function githubRelease(tag, repository) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/u.test(repository)) {
    throw new Error('GitHub release repository identity is invalid.');
  }
  if (!/^desktop-v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$/u.test(tag)) {
    throw new Error('GitHub release tag identity is invalid.');
  }
  // GitHub's REST "get release by tag" endpoint does not return draft
  // releases. Resolve the draft through the CLI (which can see it), then read
  // the immutable numeric release resource through REST.
  let metadata;
  try {
    metadata = JSON.parse(
      execFileSync(
        'gh',
        ['release', 'view', tag, '--repo', repository, '--json', 'databaseId,isDraft,isPrerelease,tagName'],
        { encoding: 'utf8', maxBuffer: 1 * 1024 * 1024 },
      ),
    );
  } catch {
    throw new Error('GitHub draft Release metadata is unavailable.');
  }
  if (
    !metadata ||
    typeof metadata !== 'object' ||
    metadata.isDraft !== true ||
    metadata.tagName !== tag ||
    metadata.isPrerelease !== tag.includes('-') ||
    !Number.isSafeInteger(metadata.databaseId) ||
    metadata.databaseId < 1
  ) {
    throw new Error('Remote GitHub Release is not the expected draft tag.');
  }
  const endpoint = `repos/${repository}/releases/${metadata.databaseId}`;
  const content = execFileSync(
    'gh',
    ['api', endpoint, '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: 2022-11-28'],
    { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 },
  );
  const release = JSON.parse(content);
  if (
    !release?.draft ||
    release.tag_name !== tag ||
    release.prerelease !== tag.includes('-') ||
    (release.html_url !== undefined &&
      (typeof release.html_url !== 'string' || release.html_url.toLowerCase().startsWith('javascript:'))) ||
    !Array.isArray(release.assets)
  ) {
    throw new Error('Remote GitHub Release is not a readable draft with assets.');
  }
  return release;
}

export async function verifyRemoteReleaseAssetDigests({
  tag,
  repository,
  assets,
  attempts = 30,
  retryDelayMs = 1_000,
}) {
  if (!tag || !Array.isArray(assets) || assets.length === 0) {
    throw new Error('Release tag and at least one local asset are required for remote verification.');
  }
  const expected = await Promise.all(assets.map((path) => localAssetIdentity(path)));
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const release = githubRelease(tag, repository);
      assertRemoteAssetDigests(release.assets, expected);
      return expected;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await delay(retryDelayMs);
    }
  }
  throw new Error('Remote GitHub Release asset digest verification failed.', { cause: lastError });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const assets = process.argv
    .filter((argument) => argument.startsWith('--asset='))
    .map((argument) => argument.slice('--asset='.length));
  const tag = process.env.GITHUB_REF_NAME;
  const repository = process.env.GITHUB_REPOSITORY;
  if (!tag || !repository || !process.env.GH_TOKEN) {
    throw new Error('GITHUB_REF_NAME, GITHUB_REPOSITORY, and GH_TOKEN are required.');
  }
  const verified = await verifyRemoteReleaseAssetDigests({ tag, repository, assets });
  process.stdout.write(`${JSON.stringify({ verified: verified.map(({ name }) => name) })}\n`);
}
