import { spawn } from 'node:child_process';
import { access, mkdtemp, readdir, readFile, rm } from 'node:fs/promises';
import { basename, join, resolve, sep } from 'node:path';
import { tmpdir } from 'node:os';
import { setTimeout as delay } from 'node:timers/promises';
import { assertDebianPackageIdentity, selectNativeDesktopInstaller } from './desktop-release-contract.mjs';

const argument = (name) => {
  const prefix = `--${name}=`;
  const value = process.argv.find((item) => item.startsWith(prefix))?.slice(prefix.length);
  if (!value) throw new Error(`Missing ${prefix}<value>`);
  return value;
};
const targetPlatform = argument('platform');
const targetArch = argument('arch');
const expectedPlatform =
  process.platform === 'darwin' ? 'darwin' : process.platform === 'linux' ? 'linux' : 'win32';
if (targetPlatform !== expectedPlatform || targetArch !== process.arch) {
  throw new Error(
    `Native verification requires ${targetPlatform}/${targetArch}, received ${process.platform}/${process.arch}.`,
  );
}
if (targetPlatform === 'win32') {
  throw new Error('Windows native installation is verified by verify-desktop-clean-install.mjs.');
}
if (targetPlatform === 'linux' && targetArch !== 'x64') {
  throw new Error('The current Linux release contract supports x64 only.');
}

const desktopPackage = JSON.parse(await readFile('apps/desktop/package.json', 'utf8'));
const makeDirectory = resolve('apps/desktop/out/make');
const temporary = await mkdtemp(join(tmpdir(), 'workdude-native-install-'));
const resolvedTemp = resolve(tmpdir());
if (
  !resolve(temporary).startsWith(`${resolvedTemp}${sep}`) ||
  !basename(temporary).startsWith('workdude-native-install-')
) {
  throw new Error('Refusing to use an unexpected native verification directory.');
}

const walk = async (directory) => {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map((entry) => {
      const path = resolve(directory, entry.name);
      return entry.isDirectory() ? walk(path) : [path];
    }),
  );
  return nested.flat();
};
const files = await walk(makeDirectory);
const shellQuote = (value) => `'${value.replaceAll("'", "'\\''")}'`;

const run = (command, args, options = {}) =>
  new Promise((resolveRun, reject) => {
    const child = spawn(command, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => (stderr += chunk));
    child.once('error', reject);
    child.once('exit', (code, signal) => resolveRun({ code, signal, stdout, stderr }));
  });

const requireSuccess = async (command, args, options) => {
  const result = await run(command, args, options);
  if (result.code !== 0) {
    throw new Error(
      `${command} failed (${result.code ?? result.signal}):\n${result.stdout}\n${result.stderr}`,
    );
  }
  return result.stdout.trim();
};

const assertStarts = async (executable, args = [], env = process.env) => {
  await access(executable);
  const detached = process.platform !== 'win32';
  const child = spawn(executable, args, {
    detached,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stderr = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (chunk) => (stderr += chunk));
  const exited = new Promise((resolveExit) =>
    child.once('exit', (code, signal) => resolveExit({ code, signal })),
  );
  const earlyExit = await Promise.race([exited, delay(10_000, null)]);
  if (earlyExit !== null) {
    throw new Error(`Installed Desktop exited during startup: ${JSON.stringify(earlyExit)}\n${stderr}`);
  }
  const terminate = (signal) => {
    if (!detached || !child.pid) return child.kill(signal);
    try {
      process.kill(-child.pid, signal);
      return true;
    } catch (cause) {
      if (cause?.code === 'ESRCH') return false;
      throw cause;
    }
  };
  terminate('SIGTERM');
  const stopped = await Promise.race([exited, delay(5_000, null)]);
  if (stopped === null) terminate('SIGKILL');
  await Promise.race([exited, delay(5_000)]);
  child.stdout.destroy();
  child.stderr.destroy();
};

try {
  const installer = selectNativeDesktopInstaller(
    files,
    makeDirectory,
    targetPlatform === 'linux' ? 'Linux-x64' : `macOS-${targetArch}`,
    desktopPackage.version,
  );
  if (targetPlatform === 'linux') {
    const expectedVersion = desktopPackage.version.replace('-', '~');
    assertDebianPackageIdentity(
      {
        package: await requireSuccess('dpkg-deb', ['--field', installer, 'Package']),
        version: await requireSuccess('dpkg-deb', ['--field', installer, 'Version']),
        architecture: await requireSuccess('dpkg-deb', ['--field', installer, 'Architecture']),
      },
      expectedVersion,
    );
    await requireSuccess('sudo', ['apt-get', 'install', '-y', installer]);
    assertDebianPackageIdentity(
      {
        package: await requireSuccess('dpkg-query', ['-W', '-f=${Package}', 'qoderwake']),
        version: await requireSuccess('dpkg-query', ['-W', '-f=${Version}', 'qoderwake']),
        architecture: await requireSuccess('dpkg-query', ['-W', '-f=${Architecture}', 'qoderwake']),
      },
      expectedVersion,
    );
    const executable = await requireSuccess('sh', ['-c', 'command -v qoderwake || command -v QoderWake']);
    const keyringRuntime = resolve(temporary, 'keyring');
    const launch = [
      `export XDG_RUNTIME_DIR=${shellQuote(keyringRuntime)}`,
      'mkdir -p "$XDG_RUNTIME_DIR"',
      'chmod 700 "$XDG_RUNTIME_DIR"',
      `eval "$(printf %s ${shellQuote('workdude-ci-keyring')} | gnome-keyring-daemon --unlock --components=secrets)" >/dev/null`,
      'cleanup() { if [ -n "${GNOME_KEYRING_PID:-}" ]; then kill "$GNOME_KEYRING_PID" 2>/dev/null || true; fi; }',
      'trap cleanup EXIT TERM INT',
      `/usr/bin/xvfb-run --auto-servernum ${shellQuote(executable)} ${shellQuote(`--user-data-dir=${resolve(temporary, 'user-data')}`)} --password-store=gnome-libsecret`,
    ].join('; ');
    await assertStarts('/usr/bin/dbus-run-session', ['--', 'bash', '-lc', launch], {
      ...process.env,
      WORKDUDE_AUTOMATION_WINDOW: 'hidden',
    });
  } else {
    const mount = resolve(temporary, 'mount');
    await requireSuccess('mkdir', ['-p', mount]);
    await requireSuccess('hdiutil', ['attach', '-readonly', '-nobrowse', '-mountpoint', mount, installer]);
    try {
      const mounted = (await readdir(mount)).find((name) => name.endsWith('.app'));
      if (!mounted) throw new Error('Mounted DMG contains no application bundle.');
      await requireSuccess('mkdir', ['-p', resolve(temporary, 'Applications')]);
      const installed = resolve(temporary, 'Applications', 'QoderWake.app');
      await requireSuccess('ditto', [resolve(mount, mounted), installed]);
      const plist = resolve(installed, 'Contents', 'Info.plist');
      const installedVersion = await requireSuccess('/usr/libexec/PlistBuddy', [
        '-c',
        'Print :CFBundleShortVersionString',
        plist,
      ]);
      if (installedVersion !== desktopPackage.version) {
        throw new Error(
          `Installed macOS version ${installedVersion} does not match ${desktopPackage.version}.`,
        );
      }
      const releaseVersion = desktopPackage.version;
      if (!releaseVersion.includes('-')) {
        await requireSuccess('codesign', ['--verify', '--deep', '--strict', '--verbose=2', installed]);
        await requireSuccess('spctl', ['--assess', '--type', 'execute', '--verbose=2', installed]);
      }
      await assertStarts(
        resolve(installed, 'Contents', 'MacOS', 'QoderWake'),
        [`--user-data-dir=${resolve(temporary, 'user-data')}`],
        { ...process.env, WORKDUDE_AUTOMATION_WINDOW: 'hidden' },
      );
    } finally {
      await requireSuccess('hdiutil', ['detach', mount]);
    }
  }
  process.stdout.write(
    `${targetPlatform}/${targetArch} native package installed, versioned, and started successfully.\n`,
  );
} finally {
  await rm(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 250 });
}
