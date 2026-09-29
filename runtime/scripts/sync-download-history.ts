import { execFile } from 'node:child_process';
import { mkdir, mkdtemp, open, readFile, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { pathToFileURL } from 'node:url';
import {
  platformKeys,
  validateManifest,
  type DownloadRelease,
  type PlatformKey,
} from '../deploy/download-page/manifest.mjs';
type SourceAsset = { id: number; name: string; size: number; digest: string; browser_download_url: string };
const exec = promisify(execFile);
const repository = 'bujidaoei/workdude';
async function main(): Promise<void> {
  const path = resolve('deploy/download-page/data/releases.json');
  const lock = await open(`${path}.publish.lock`, 'wx', 0o600);
  try {
    const original = await readFile(path, 'utf8');
    const manifest = validateManifest(JSON.parse(original));
    const temporary = await mkdtemp(join(tmpdir(), 'workdude-download-sync-'));
    const candidate = join(temporary, 'releases.json');

    type SourceRelease = { tag_name: string; draft: boolean; published_at: string; assets: SourceAsset[] };
    const list = JSON.parse(
      (
        await exec('gh', [
          'release',
          'list',
          '--repo',
          repository,
          '--exclude-drafts',
          '--limit',
          '100',
          '--json',
          'tagName',
        ])
      ).stdout,
    ) as { tagName: string }[];
    const pending: { version: string; tag: string; platform: PlatformKey; asset: SourceAsset }[] = [];
    for (const { tagName } of list) {
      if (!/^desktop-v\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$/.test(tagName)) continue;
      const source = JSON.parse(
        (await exec('gh', ['api', `repos/${repository}/releases/tags/${tagName}`])).stdout,
      ) as SourceRelease;
      if (source.draft || source.tag_name !== tagName || !source.published_at)
        throw new Error('Release source identity mismatch');
      const version = tagName.slice('desktop-v'.length);
      let release = manifest.releases.find((item) => item.version === version);
      if (!release) {
        release = {
          version,
          status: 'history',
          date: source.published_at.slice(0, 10),
          summary: '历史桌面测试版本。',
          changes: [],
          fixes: [],
          previousVersion: null,
          notesBasis: '原发布记录未提供分类说明；请参阅代码变更来源。',
          platforms: {
            windows: {
              status: 'unavailable',
              label: 'Windows',
              arch: 'x64',
              requirement: 'Windows 10 及以上',
            },
            linux: { status: 'unavailable', label: 'Linux', arch: 'x64' },
            macosIntel: { status: 'unavailable', label: 'macOS', arch: 'Intel' },
            macosArm: { status: 'unavailable', label: 'macOS', arch: 'Apple Silicon' },
          },
        } satisfies DownloadRelease;
        manifest.releases.push(release);
      }
      const matchers: Record<PlatformKey, (name: string) => boolean> = {
        windows: (name) => name.endsWith('.exe'),
        linux: (name) => name.endsWith('.deb'),
        macosIntel: (name) => name.endsWith('-x64.dmg'),
        macosArm: (name) => name.endsWith('-arm64.dmg'),
      };
      for (const platform of platformKeys) {
        if (release.platforms[platform].status === 'available') continue;
        const matches = source.assets.filter((asset) => matchers[platform](asset.name));
        if (!matches.length) continue;
        if (matches.length !== 1) throw new Error('Ambiguous installer selection');
        const asset = matches[0]!;
        if (
          basename(asset.name) !== asset.name ||
          !/^sha256:[a-f0-9]{64}$/.test(asset.digest) ||
          asset.size <= 0 ||
          !Number.isSafeInteger(asset.id) ||
          asset.id <= 0
        )
          throw new Error('Missing source integrity');
        release.platforms[platform].sourceUrl = asset.browser_download_url;
        pending.push({ version, tag: tagName, platform, asset });
      }
    }
    manifest.releases.sort((a, b) => b.version.localeCompare(a.version, undefined, { numeric: true }));
    for (const [index, release] of manifest.releases.entries()) {
      const previous = manifest.releases[index + 1];
      if (!release.notesBasis.startsWith('原发布记录')) continue;
      release.previousVersion = previous?.version ?? null;
      release.sourceUrl = previous
        ? `https://github.com/${repository}/compare/desktop-v${previous.version}...desktop-v${release.version}`
        : `https://github.com/${repository}/commits/desktop-v${release.version}`;
      if (previous) {
        const subjects = (
          await exec('git', [
            'log',
            '--format=%s',
            `desktop-v${previous.version}..desktop-v${release.version}`,
          ])
        ).stdout.split('\n');
        release.changes = subjects.filter((line) => /^feat(?:\(|:)/.test(line));
        release.fixes = subjects.filter((line) => /^fix(?:\(|:)/.test(line));
        release.notesBasis = `相较 ${previous.version}；分类条目引用该版本范围的原始提交标题，未把无记录的类别补写为新功能。`;
      }
    }
    // Extend a previously terminal history entry when older public releases are found.
    for (const [index, release] of manifest.releases.entries()) {
      const previous = manifest.releases[index + 1];
      if (previous && release.previousVersion === null) {
        release.previousVersion = previous.version;
        release.sourceUrl =
          'https://github.com/' +
          repository +
          '/compare/desktop-v' +
          previous.version +
          '...desktop-v' +
          release.version;
        release.notesBasis =
          '相较 ' + previous.version + '；原发布记录未提供分类更新说明，请查阅代码变更来源。';
      }
    }
    validateManifest(manifest);
    await writeFile(candidate, JSON.stringify(manifest, null, 2) + '\n');
    for (let offset = 0; offset < pending.length; offset += 4) {
      const results = await Promise.allSettled(
        pending.slice(offset, offset + 4).map(async (item) => {
          process.stdout.write('Syncing ' + item.version + ' ' + item.platform + '\n');
          const isolated = join(temporary, item.version + '-' + item.platform + '.json');
          await writeFile(isolated, JSON.stringify(manifest, null, 2) + '\n');
          const cache = resolve('.tmp/download-history', item.version);
          await mkdir(cache, { recursive: true });
          const file = join(cache, item.asset.name);
          await downloadAsset(item.asset, file);
          const result = await exec(
            process.execPath,
            [
              '--import',
              'tsx',
              'scripts/publish-download-asset.ts',
              '--manifest=' + isolated,
              '--file=' + file,
              '--version=' + item.version,
              '--platform=' + item.platform,
              '--sha256=' + item.asset.digest.slice(7),
            ],
            { timeout: 600_000 },
          );
          process.stdout.write(result.stdout);
          const updated = validateManifest(JSON.parse(await readFile(isolated, 'utf8'))).releases.find(
            (release) => release.version === item.version,
          )!;
          await unlink(isolated);
          return { version: item.version, platform: item.platform, asset: updated.platforms[item.platform] };
        }),
      );
      for (const result of results) {
        if (result.status === 'fulfilled') {
          manifest.releases.find((release) => release.version === result.value.version)!.platforms[
            result.value.platform
          ] = result.value.asset;
        }
      }
      await writeFile(candidate, JSON.stringify(manifest, null, 2) + '\n');
      if (results.some((result) => result.status === 'rejected')) {
        for (const result of results)
          if (result.status === 'rejected') process.stderr.write(String(result.reason) + '\n');
        throw new Error('Batch failed; verified candidate retained at ' + candidate);
      }
    }
    const final = validateManifest(JSON.parse(await readFile(candidate, 'utf8')));
    if ((await readFile(path, 'utf8')) !== original)
      throw new Error(`Catalog changed; verified candidate retained at ${candidate}`);
    const promotion = `${path}.${process.pid}.tmp`;
    final.generatedAt = new Date().toISOString();
    await writeFile(promotion, JSON.stringify(final, null, 2) + '\n', { flag: 'wx' });
    await rename(promotion, path);
    process.stdout.write(`Synchronized ${pending.length} assets across ${final.releases.length} releases\n`);
  } finally {
    await lock.close();
    await unlink(`${path}.publish.lock`);
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await main();

// GitHub API authorization is never forwarded to the asset CDN. Each retry obtains
// a fresh download URL and resumes only when the server confirms the byte range.
export async function downloadAsset(asset: SourceAsset, file: string): Promise<void> {
  const token = process.env.GH_TOKEN || (await exec('gh', ['auth', 'token'])).stdout.trim();
  for (let attempt = 0; attempt < 5; attempt++) {
    let offset = await stat(file)
      .then((info) => info.size)
      .catch(() => 0);
    if (offset === asset.size) return;
    if (offset > asset.size) throw new Error('Cached asset exceeds source size');
    try {
      const authorization = await fetch(
        'https://api.github.com/repos/' + repository + '/releases/assets/' + asset.id,
        {
          headers: { Accept: 'application/octet-stream', Authorization: 'Bearer ' + token },
          redirect: 'manual',
          signal: AbortSignal.timeout(30_000),
        },
      );
      let response = authorization;
      const location = authorization.headers.get('location');
      if (location) {
        const url = new URL(location);
        if (url.protocol !== 'https:' || !url.hostname.endsWith('.githubusercontent.com'))
          throw new Error('Unexpected release CDN');
        response = await fetch(url, {
          headers: offset ? { Range: 'bytes=' + offset + '-' } : {},
          signal: AbortSignal.timeout(120_000),
        });
      }
      if (!response.ok || !response.body) throw new Error('GitHub asset download failed: ' + response.status);
      if (response.status === 206) {
        if (!response.headers.get('content-range')?.startsWith('bytes ' + offset + '-'))
          throw new Error('Invalid resume range');
      } else {
        offset = 0;
      }
      const output = await open(file, offset ? 'a' : 'w');
      const reader = response.body.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          await output.writeFile(value);
        }
      } finally {
        await output.close();
        reader.releaseLock();
      }
      if ((await stat(file)).size !== asset.size) throw new Error('Incomplete release download');
      return;
    } catch {
      if (attempt === 4) throw new Error('Download retries exhausted for ' + asset.name);
      process.stdout.write('Resuming ' + asset.name + '\n');
    }
  }
}
