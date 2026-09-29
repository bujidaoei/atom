import { spawn } from 'node:child_process';

if (process.platform !== 'win32') {
  throw new Error('The complete Windows Desktop maker requires a Windows host.');
}
const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error('npm_execpath is required to run the Windows Desktop maker.');

async function runNpm(args, label) {
  const child = spawn(
    process.execPath,
    [npmCli, '--workspace', '@workdude/desktop', 'run', 'make', '--', ...args],
    {
      env: { ...process.env, WORKDUDE_ENABLE_SQUIRREL: 'true', ...label.env },
      stdio: 'inherit',
      windowsHide: true,
    },
  );
  const result = await new Promise((resolveRun, rejectRun) => {
    child.once('error', rejectRun);
    child.once('exit', (code, signal) => resolveRun({ code, signal }));
  });
  if (result.code !== 0) {
    throw new Error(
      `Complete Windows Desktop ${label.name} failed (${String(result.code ?? result.signal)}).`,
    );
  }
}

async function runPackage() {
  const child = spawn(process.execPath, [npmCli, '--workspace', '@workdude/desktop', 'run', 'package'], {
    env: { ...process.env, WORKDUDE_ENABLE_SQUIRREL: 'true' },
    stdio: 'inherit',
    windowsHide: true,
  });
  const result = await new Promise((resolveRun, rejectRun) => {
    child.once('error', rejectRun);
    child.once('exit', (code, signal) => resolveRun({ code, signal }));
  });
  if (result.code !== 0) {
    throw new Error(`Complete Windows Desktop package failed (${String(result.code ?? result.signal)}).`);
  }
}

// Forge runs makers concurrently against one packaged directory. Squirrel's
// temporary packaging cleanup can remove Electron runtime files while MakerZIP
// is still reading them. Package once, then run both makers sequentially with
// --skip-package so every installer family shares one build identity.
await runPackage();
await runNpm(['--skip-package'], { name: 'squirrel maker', env: { WORKDUDE_MAKE_TARGET: 'squirrel' } });
await runNpm(['--skip-package'], { name: 'zip maker', env: { WORKDUDE_MAKE_TARGET: 'zip' } });
