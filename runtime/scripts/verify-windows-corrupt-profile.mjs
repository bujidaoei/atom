import { access, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';

if (process.platform !== 'win32')
  throw new Error('Packaged Windows profile recovery verification requires Windows.');
const manifest = JSON.parse(await readFile('apps/desktop/package.json', 'utf8'));
const executable = resolve('apps/desktop/out', `QoderWake-win32-x64`, 'QoderWake.exe');
await access(executable);
const root = await mkdtemp(join(tmpdir(), 'qoderwake-corrupt-profile-'));
const userData = join(root, 'user-data');
await import('node:fs/promises').then(({ mkdir }) => mkdir(userData, { recursive: true }));
const database = join(userData, 'workdude-v3.sqlite');
await writeFile(database, 'not a sqlite database', 'utf8');
let child;
try {
  child = spawn(executable, [`--user-data-dir=${userData}`], {
    env: { ...process.env, WORKDUDE_AUTOMATION_WINDOW: 'hidden' },
    windowsHide: true,
    stdio: 'ignore',
  });
  let earlyExit;
  child.once('exit', (code, signal) => {
    earlyExit = { code, signal };
  });
  await delay(10_000);
  if (earlyExit)
    throw new Error(`Packaged app exited during corrupt-profile recovery: ${JSON.stringify(earlyExit)}`);
  const entries = await readdir(userData);
  const quarantine = entries.find((name) => name.startsWith('corrupt-profile-'));
  if (!quarantine) throw new Error('Corrupt profile quarantine directory was not created.');
  const quarantinedDatabase = join(userData, quarantine, 'workdude-v3.sqlite');
  await access(quarantinedDatabase);
  if ((await readFile(quarantinedDatabase, 'utf8')) !== 'not a sqlite database') {
    throw new Error('Quarantined database contents were not preserved.');
  }
  const bootstrapped = join(userData, 'workdude-v3.sqlite');
  await access(bootstrapped);
  const header = (await readFile(bootstrapped)).subarray(0, 16).toString('ascii');
  if (header.slice(0, 15) !== 'SQLite format 3')
    throw new Error(`Clean bootstrap database has invalid SQLite header: ${JSON.stringify(header)}`);
  console.log(JSON.stringify({ version: manifest.version, executable, quarantine, cleanBootstrap: true }));
} finally {
  if (child?.exitCode === null) child.kill();
  await delay(1_000);
  await rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 250 });
}
