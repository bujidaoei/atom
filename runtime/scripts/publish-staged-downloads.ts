import { existsSync, readFileSync } from 'node:fs';
import { posix } from 'node:path';
import { spawnSync } from 'node:child_process';
import { validateManifest } from '../deploy/download-page/manifest.mjs';

// Runs only inside the isolated release container. Credentials stay on the server.
const manifestPath = '/release/releases.json';
const manifest = validateManifest(JSON.parse(readFileSync(manifestPath, 'utf8')));
function publish(args: string[]) {
  const result = spawnSync(
    process.execPath,
    ['--import', 'tsx', '/app/scripts/publish-download-asset.ts', '--manifest', manifestPath, ...args],
    { stdio: 'inherit' },
  );
  if (result.error || result.status !== 0) throw new Error('COS publication/verification failed');
}
for (const release of manifest.releases) {
  for (const [platform, asset] of Object.entries(release.platforms)) {
    if (asset.status !== 'available') continue;
    const source = [
      posix.join('/release', asset.file!),
      posix.join('/legacy', release.version, asset.file!),
    ].find((path) => existsSync(path));
    if (!source) continue; // Existing COS objects are all verified below.
    publish([
      '--file',
      source,
      '--version',
      release.version,
      '--platform',
      platform,
      '--sha256',
      asset.sha256!,
    ]);
  }
}
publish(['--verify']);
