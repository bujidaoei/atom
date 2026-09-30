/** Controlled boundary reproduction, not proof of an agent-exploitable tool path. */
import { mkdtemp, mkdir, writeFile, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, relative, isAbsolute } from 'node:path';
import { randomUUID } from 'node:crypto';
import { LocalSandboxClient } from '../src/local-sandbox.ts';

const temporaryRoot = await realpath(tmpdir());
const root = await mkdtemp(join(temporaryRoot, 'atom-isolation-probe-'));
const workspace = join(root, 'workspace');
const hostCanary = join(root, 'outside-workspace.txt');
const envName = 'ATOM_ISOLATION_PROBE_' + randomUUID().replaceAll('-', '');
const canary = randomUUID();
let sandbox: LocalSandboxClient | undefined;
let sandboxId: string | undefined;
try {
  await mkdir(workspace);
  await writeFile(hostCanary, canary, { flag: 'wx' });
  process.env[envName] = canary;
  sandbox = new LocalSandboxClient({
    resolveWorkspace: () => workspace,
    shell: process.execPath,
    shellArgs: ['-e'],
  });
  sandboxId = await sandbox.create('synthetic-probe', 'synthetic-workspace');
  // Run only a fixed local script that reads our own temporary canaries.
  // No host inventory, actual secrets, network, model request or source mutation.
  const script = `const fs=require('node:fs');console.log(JSON.stringify({
    inherited:process.env[${JSON.stringify(envName)}]===${JSON.stringify(canary)},
    outsideReadable:fs.readFileSync(${JSON.stringify(hostCanary)},'utf8')===${JSON.stringify(canary)}
  }));`;
  const result = await sandbox.exec(sandboxId, { toolCallId: 'probe', command: script, timeoutMs: 5000 });
  if (result.exitCode !== 0 || result.timedOut) throw new Error('Controlled probe did not complete');
  const observed = JSON.parse(result.stdout);
  const isolated = observed.inherited === false && observed.outsideReadable === false;
  console.log(JSON.stringify({
    scope: 'LocalSandboxClient.exec-only',
    result: isolated ? 'NOT_OBSERVED' : 'NO_OS_ISOLATION',
    inheritedSyntheticEnvironment: observed.inherited,
    readSyntheticFileOutsideWorkspace: observed.outsideReadable,
    agentExploitability: 'not-tested',
  }));
  process.exitCode = isolated ? 0 : 1;
} finally {
  delete process.env[envName];
  if (sandbox && sandboxId) await sandbox.destroy(sandboxId);
  const resolved = await realpath(root);
  const offset = relative(temporaryRoot, resolved);
  if (!offset || offset.startsWith('..') || isAbsolute(offset)) throw new Error('Unsafe cleanup path');
  await rm(resolved, { recursive: true, force: true });
}
