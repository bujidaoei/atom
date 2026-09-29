import { readFile, readdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const root = JSON.parse(await readFile('package.json', 'utf8'));
const lock = JSON.parse(await readFile('package-lock.json', 'utf8'));
if (typeof root.version !== 'string' || !root.version) throw new Error('Root package version is required');
const updates = [];
for (const family of ['apps', 'packages', 'services']) {
  for (const entry of await readdir(family, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const workspace = `${family}/${entry.name}`;
    const path = join(workspace, 'package.json');
    let source;
    try {
      source = await readFile(path, 'utf8');
    } catch (error) {
      if (error.code === 'ENOENT') continue;
      throw error;
    }
    const manifest = JSON.parse(source);
    if (!lock.packages[workspace]) throw new Error(`Missing workspace lock entry: ${workspace}`);
    manifest.version = root.version;
    lock.packages[workspace].version = root.version;
    const next = JSON.stringify(manifest, null, 2) + '\n';
    if (source !== next) updates.push({ path, next });
  }
}
lock.version = root.version;
lock.packages[''].version = root.version;
for (const { path, next } of updates) await writeFile(path, next);
await writeFile('package-lock.json', JSON.stringify(lock, null, 2) + '\n');
console.log(`Workspace manifests and lockfile synchronized to ${root.version}`);
