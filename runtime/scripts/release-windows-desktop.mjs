import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const skipPackage = process.argv.includes('--skip-package');
const publish = process.argv.includes('--publish');

function run(command, args) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, { cwd: root, stdio: 'inherit', windowsHide: true });
    child.once('error', rejectRun);
    child.once('exit', (code, signal) => {
      if (code === 0) resolveRun();
      else rejectRun(new Error(`${command} ${args.join(' ')} failed (${String(code ?? signal)}).`));
    });
  });
}

let source = '';
try {
  source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
  const dirty = execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim();
  if (dirty) throw new Error('Refusing to record a Windows release from a dirty worktree.');
} catch (error) {
  if (String(error instanceof Error ? error.message : error).includes('dirty worktree')) throw error;
  if (publish) {
    throw new Error('A git commit is required before a Windows release can be published.', { cause: error });
  }
}
const npmCli = process.env.npm_execpath;
if (!skipPackage) {
  if (!npmCli) throw new Error('Run this through npm run release:windows so the package step can start.');
  await run(process.execPath, [npmCli, '--workspace', '@workdude/desktop', 'run', 'package']);
}
await run(process.execPath, [join(root, 'scripts', 'make-windows-inno.mjs')]);

const desktop = JSON.parse(await readFile(join(root, 'apps', 'desktop', 'package.json'), 'utf8'));
const installer = join(
  root,
  'apps',
  'desktop',
  'out',
  'make',
  'inno',
  `QoderWake-${desktop.version}-Windows-x64-Setup.exe`,
);
const hash = createHash('sha256');
let size = 0;
for await (const chunk of createReadStream(installer)) {
  size += chunk.length;
  hash.update(chunk);
}
const sha256 = hash.digest('hex');
const receiptDirectory = join(root, '.tmp', 'windows-release');
await mkdir(receiptDirectory, { recursive: true });
const receipt = {
  version: desktop.version,
  source,
  file: installer,
  size,
  sha256,
  platform: 'windows',
};
await writeFile(join(receiptDirectory, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(
  JSON.stringify({ phase: 'windows-installer-ready', version: desktop.version, bytes: size, sha256, source }),
);
console.log(
  'Publish from the server, where COS and the catalog database are already configured: node --env-file=/opt/workdude/.env --import tsx scripts/publish-native-release.ts --file=<installer> --source=' +
    source +
    ' --platform=windows --notes=<release-notes.json>',
);
if (publish) {
  const notes = process.argv.find((item) => item.startsWith('--notes='))?.slice('--notes='.length);
  if (!notes) throw new Error('--publish requires --notes=<release-notes.json>');
  await run(process.execPath, [
    '--env-file=.env',
    '--import',
    'tsx',
    join(root, 'scripts', 'publish-native-release.ts'),
    `--file=${installer}`,
    `--source=${source}`,
    '--platform=windows',
    `--notes=${notes}`,
  ]);
}
