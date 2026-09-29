import { mkdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

const root = process.cwd();
const temporaryDirectory = resolve(root, '.tmp', 'test');
mkdirSync(temporaryDirectory, { recursive: true });

const vitestEntry = resolve(root, 'node_modules', 'vitest', 'vitest.mjs');
const result = spawnSync(process.execPath, [vitestEntry, 'run', ...process.argv.slice(2)], {
  cwd: root,
  env: {
    ...process.env,
    TEMP: temporaryDirectory,
    TMP: temporaryDirectory,
  },
  stdio: 'inherit',
});

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
