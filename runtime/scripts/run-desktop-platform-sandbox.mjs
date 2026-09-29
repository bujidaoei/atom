/* global Buffer, Headers, Response, URL, clearTimeout, setTimeout */

import { createHash, randomUUID } from 'node:crypto';
import { existsSync, createReadStream } from 'node:fs';
import { access, lstat, mkdir, mkdtemp, readFile, realpath, rm, unlink, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { arch as hostArch, platform as hostPlatform } from 'node:process';
import { tmpdir } from 'node:os';
import { isAbsolute, join, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repositoryRoot = resolve(fileURLToPath(new URL('..', import.meta.url)));
const NODE_IMAGE = 'node@sha256:2c87ef9bd3c6a3bd4b472b4bec2ce9d16354b0c574f736c476489d09f560a203';
const TEMPORARY_PREFIX = 'workdude-platform-sandbox-';
const CONTAINER_NAME_PATTERN = /^workdude-platform-sandbox-[0-9a-f-]{36}$/u;

export const PLATFORM_SANDBOX_TARGETS = Object.freeze([
  Object.freeze({ id: 'win32/x64', platform: 'win32', arch: 'x64', label: 'Windows-x64' }),
  Object.freeze({ id: 'linux/x64', platform: 'linux', arch: 'x64', label: 'Linux-x64' }),
  Object.freeze({ id: 'darwin/x64', platform: 'darwin', arch: 'x64', label: 'macOS-x64' }),
  Object.freeze({ id: 'darwin/arm64', platform: 'darwin', arch: 'arm64', label: 'macOS-arm64' }),
]);

const targetById = new Map(PLATFORM_SANDBOX_TARGETS.map((target) => [target.id, target]));

function fail(message) {
  throw new Error(message);
}

function assertCondition(condition, message) {
  if (!condition) fail(message);
}

function samePath(first, second) {
  const left = resolve(first);
  const right = resolve(second);
  return hostPlatform === 'win32' ? left.toLowerCase() === right.toLowerCase() : left === right;
}

function targetId(platform, arch) {
  return `${platform}/${arch}`;
}

function targetFromValue(value) {
  const id = typeof value === 'string' ? value : value?.id;
  const target = targetById.get(id);
  if (!target) fail(`Unsupported platform sandbox target: ${String(id)}`);
  return target;
}

function normalizeTargetValues(value) {
  if (Array.isArray(value)) {
    if (value.length === 0) fail('At least one platform sandbox target is required');
    const targets = value.map(targetFromValue);
    const ids = targets.map(({ id }) => id);
    if (new Set(ids).size !== ids.length) fail('Duplicate platform sandbox target');
    return targets;
  }
  return parsePlatformSandboxTargets(value);
}

export function parsePlatformSandboxTargets(value = 'all') {
  if (typeof value !== 'string' || !value.trim()) fail('Platform sandbox targets are required');
  const normalized = value.trim();
  if (normalized === 'all') return PLATFORM_SANDBOX_TARGETS;
  if (normalized.split(',').some((item) => item.trim() === 'all')) {
    fail('The all platform sandbox target cannot be combined with another target');
  }
  const ids = normalized.split(',').map((item) => item.trim());
  if (ids.some((id) => !id)) fail('Platform sandbox target list contains an empty target');
  const targets = ids.map(targetFromValue);
  if (new Set(ids).size !== ids.length) fail('Duplicate platform sandbox target');
  return targets;
}

export function expectedPlatformSandboxLabel(platform, arch) {
  return targetFromValue(targetId(platform, arch)).label;
}

function safeContainerName(value) {
  if (typeof value !== 'string' || !CONTAINER_NAME_PATTERN.test(value)) {
    fail('Platform sandbox container name is unsafe');
  }
  return value;
}

export function buildPlatformSandboxDockerInvocation({ repositoryRoot: root, targets, containerName }) {
  if (typeof root !== 'string' || !isAbsolute(root)) {
    fail('Platform sandbox repository root must be absolute');
  }
  if (root.includes(',') || /[\r\n]/u.test(root)) fail('Platform sandbox repository root is unsafe');
  const resolvedRoot = resolve(root);
  const selected = normalizeTargetValues(targets);
  assertCondition(
    selected.every((target) => target.platform !== 'win32'),
    'The Linux platform sandbox cannot execute a Windows target',
  );
  const name = safeContainerName(containerName);
  const source = resolvedRoot.replaceAll('\\', '/');
  return {
    command: 'docker',
    args: [
      'run',
      '--pull=never',
      '--name',
      name,
      '--label',
      'com.workdude.platform-sandbox=owned',
      '--network',
      'none',
      '--read-only',
      '--cap-drop=ALL',
      '--security-opt=no-new-privileges',
      '--pids-limit',
      '128',
      '--cpus=1',
      '--memory=768m',
      '--user',
      '65532:65532',
      '--tmpfs',
      '/tmp:rw,noexec,nosuid,nodev',
      '--tmpfs',
      '/run:rw,noexec,nosuid,nodev',
      '--env',
      'WORKDUDE_PLATFORM_SANDBOX=1',
      '--env',
      'NODE_NO_WARNINGS=1',
      '--mount',
      `type=bind,source=${source},target=/workspace,readonly`,
      '--workdir',
      '/workspace',
      NODE_IMAGE,
      'node',
      'scripts/run-desktop-platform-sandbox.mjs',
      '--inside-container',
      `--targets=${selected.map(({ id }) => id).join(',')}`,
      '--json',
    ],
  };
}

async function resolveRepositoryRoot(candidate) {
  const requested = resolve(candidate);
  const canonical = await realpath(requested);
  const [rootEntry, packageEntry, lockEntry, piEntry] = await Promise.all([
    lstat(canonical),
    lstat(join(canonical, 'package.json')),
    lstat(join(canonical, 'pi-source.lock.json')),
    lstat(join(canonical, 'pi')),
  ]);
  assertCondition(
    rootEntry.isDirectory() && !rootEntry.isSymbolicLink(),
    'Repository root is not a plain directory',
  );
  assertCondition(
    packageEntry.isFile() && !packageEntry.isSymbolicLink(),
    'Repository package manifest is invalid',
  );
  assertCondition(lockEntry.isFile() && !lockEntry.isSymbolicLink(), 'Repository Pi source lock is invalid');
  assertCondition(piEntry.isDirectory() && !piEntry.isSymbolicLink(), 'Repository Pi root is invalid');
  return canonical;
}

async function createOwnedTemporaryDirectory(label) {
  const base = resolve(tmpdir());
  const path = await mkdtemp(join(base, `${TEMPORARY_PREFIX}${label}-`));
  const canonicalBase = await realpath(base);
  const canonicalPath = await realpath(path);
  assertCondition(
    canonicalPath.startsWith(`${canonicalBase}${sep}`) && canonicalPath !== canonicalBase,
    'Platform sandbox temporary directory escaped its owned base',
  );
  assertCondition(
    path.split(/[\\/]/u).at(-1)?.startsWith(TEMPORARY_PREFIX),
    'Platform sandbox temporary name is invalid',
  );
  return canonicalPath;
}

async function removeOwnedTemporaryDirectory(path) {
  const resolved = resolve(path);
  const base = resolve(tmpdir());
  const canonicalBase = await realpath(base);
  const canonicalPath = await realpath(resolved).catch((error) => {
    if (error?.code === 'ENOENT') return resolved;
    throw error;
  });
  assertCondition(
    canonicalPath.startsWith(`${canonicalBase}${sep}`) &&
      canonicalPath.split(/[\\/]/u).at(-1)?.startsWith(TEMPORARY_PREFIX),
    'Refusing to remove an unowned platform sandbox temporary directory',
  );
  await rm(canonicalPath, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}

function runProcess(command, args, { cwd = repositoryRoot, env = process.env, timeoutMs = 30_000 } = {}) {
  return new Promise((settle) => {
    const child = spawn(command, args, {
      cwd,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let settled = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, timeoutMs);
    timeout.unref?.();
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      settle({ ...result, timedOut, stdout, stderr });
    };
    child.once('error', (error) => finish({ code: null, signal: null, error }));
    child.once('exit', (code, signal) => finish({ code, signal }));
  });
}

async function commandOutput(command, args, options = {}) {
  const result = await runProcess(command, args, options);
  if (result.timedOut || result.code !== 0) {
    const detail = `${result.stdout}\n${result.stderr}`.trim().slice(-12_000);
    fail(`${command} ${args.join(' ')} failed (${result.code ?? result.signal}): ${detail}`);
  }
  return result.stdout.trim();
}

async function sha256File(path) {
  return new Promise((resolveHash, rejectHash) => {
    const digest = createHash('sha256');
    const stream = createReadStream(path);
    stream.on('data', (chunk) => digest.update(chunk));
    stream.once('error', rejectHash);
    stream.once('end', () => resolveHash(digest.digest('hex')));
  });
}

function fakeSafeStorage(backend = 'platform-test-keyring') {
  return {
    isEncryptionAvailable: () => true,
    getSelectedStorageBackend: () => backend,
    encryptString(value) {
      return Buffer.from(`sealed:${Buffer.from(value, 'utf8').toString('base64')}`, 'utf8');
    },
    decryptString(value) {
      const encoded = value.toString('utf8');
      if (!encoded.startsWith('sealed:')) fail('Platform sandbox test storage received an unsealed value');
      return Buffer.from(encoded.slice('sealed:'.length), 'base64').toString('utf8');
    },
  };
}

async function waitUntil(predicate, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolveWait) => setTimeout(resolveWait, 10));
  }
  fail('Platform sandbox asynchronous contract did not become ready within its bound');
}

async function loadDesktopModules(root) {
  const [updateChannel, sandboxImage, machineCredentials, machineBridge, piCache] = await Promise.all([
    import(pathToFileURL(resolve(root, 'apps/desktop/src/update-channel.ts')).href),
    import(pathToFileURL(resolve(root, 'apps/desktop/src/sandbox-image.ts')).href),
    import(pathToFileURL(resolve(root, 'apps/desktop/src/machine-credentials.ts')).href),
    import(pathToFileURL(resolve(root, 'apps/desktop/src/machine-bridge.ts')).href),
    import(pathToFileURL(resolve(root, 'scripts/pi-cache-publication.mjs')).href),
  ]);
  return { updateChannel, sandboxImage, machineCredentials, machineBridge, piCache };
}

function nextReleaseVersion(currentVersion) {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$/u.exec(currentVersion);
  assertCondition(match !== null, `Desktop package version is not semver-like: ${currentVersion}`);
  if (match[4] !== undefined) {
    return `${match[1]}.${match[2]}.${match[3]}-beta.${Number(match[4]) + 1}`;
  }
  return `${match[1]}.${match[2]}.${Number(match[3]) + 1}`;
}

async function runReleaseContract(root, target, modules) {
  const packageManifest = JSON.parse(await readFile(join(root, 'apps/desktop/package.json'), 'utf8'));
  const currentVersion = packageManifest.version;
  const tokens = modules.updateChannel.compatibleAssetTokens(target.platform, target.arch);
  assertCondition(Array.isArray(tokens), `${target.id} has no compatible update asset token`);
  const nextVersion = nextReleaseVersion(currentVersion);
  const assetName = `QoderWake-${nextVersion}-${tokens.join('-')}.zip`;
  const release = {
    tag_name: `desktop-v${nextVersion}`,
    draft: false,
    prerelease: true,
    assets: [{ name: assetName }],
  };
  const selected = modules.updateChannel.selectCompatibleRelease(
    [release],
    currentVersion,
    target.platform,
    target.arch,
  );
  assertCondition(
    selected?.tag_name === release.tag_name,
    `${target.id} update asset selection is not bound to its label`,
  );
  const mismatched = modules.updateChannel.selectCompatibleRelease(
    [release],
    currentVersion,
    target.platform,
    target.arch === 'x64' ? 'arm64' : 'x64',
  );
  assertCondition(mismatched === undefined, `${target.id} accepted a mismatched architecture asset`);
  return { version: currentVersion, assetName };
}

async function runSandboxImageContract(target, root, modules) {
  const packageManifest = JSON.parse(await readFile(join(root, 'apps/desktop/package.json'), 'utf8'));
  const image = modules.sandboxImage.desktopSandboxImage(packageManifest.version);
  const invocation = modules.sandboxImage.sandboxBuildInvocation(
    image,
    '/workspace/deploy/sandbox',
    target.platform,
  );
  assertCondition(invocation.command === 'docker', `${target.id} sandbox builder command changed`);
  assertCondition(invocation.args.includes(image), `${target.id} sandbox image is not pinned`);
  const hasWindowsPipe = invocation.args.includes('npipe:////./pipe/docker_engine');
  assertCondition(
    hasWindowsPipe === (target.platform === 'win32'),
    `${target.id} Docker host boundary is wrong`,
  );
  return { image, windowsDockerPipe: hasWindowsPipe };
}

async function runCredentialContract(target, modules) {
  const profile = await createOwnedTemporaryDirectory(`credentials-${target.platform}-${target.arch}`);
  try {
    const machineId = randomUUID();
    const machineSecret = 'm'.repeat(43);
    const store = modules.machineCredentials.createDesktopMachineCredentialStore({
      userDataPath: profile,
      platformOrigin: 'https://platform.example.test',
      safeStorage: fakeSafeStorage(),
      platform: target.platform,
    });
    await store.write({ machineId, machineSecret });
    const restored = await store.read();
    assertCondition(
      restored?.machineId === machineId && restored.machineSecret === machineSecret,
      `${target.id} credential round-trip failed`,
    );
    const protectedBytes = await readFile(join(profile, 'machine-credentials.enc'), 'utf8');
    assertCondition(
      !protectedBytes.includes(machineSecret),
      `${target.id} credential was persisted in plaintext`,
    );
    await store.clear();
    assertCondition(
      (await store.read()) === undefined,
      `${target.id} credential clear did not remove the record`,
    );
    let insecureRejected = false;
    if (target.platform === 'linux') {
      const insecure = modules.machineCredentials.createDesktopMachineCredentialStore({
        userDataPath: profile,
        platformOrigin: 'https://platform.example.test',
        safeStorage: fakeSafeStorage('basic_text'),
        platform: target.platform,
      });
      try {
        await insecure.write({ machineId, machineSecret });
      } catch (error) {
        insecureRejected = /basic_text/u.test(String(error));
      }
      assertCondition(insecureRejected, 'Linux basic_text credential storage was not rejected');
    }
    return { roundTrip: true, plaintextAbsent: true, insecureLinuxRejected: insecureRejected };
  } finally {
    await removeOwnedTemporaryDirectory(profile);
  }
}

async function runMachineBridgeContract(target, root, modules) {
  const profile = await createOwnedTemporaryDirectory(`bridge-${target.platform}-${target.arch}`);
  const platformAccessToken = 'p'.repeat(32);
  const machineSecret = 's'.repeat(43);
  let persisted;
  let registrations = 0;
  let polls = 0;
  const registrationBodies = [];
  const credentialStore = {
    platformOrigin: 'https://platform.example.test',
    async read() {
      return persisted;
    },
    async write(value) {
      persisted = value;
    },
    async clear() {
      persisted = undefined;
    },
  };
  const fetchImpl = async (input, init) => {
    const url = new URL(String(input));
    const authorization = new Headers(init?.headers).get('authorization');
    if (init?.method === 'POST' && url.pathname === '/api/v1/remote/machines/bridge') {
      assertCondition(
        authorization === `Bearer ${platformAccessToken}`,
        `${target.id} bridge registration auth changed`,
      );
      registrations += 1;
      registrationBodies.push(JSON.parse(String(init.body)));
      return Response.json({ machine_secret: machineSecret });
    }
    if (init?.method === 'GET' && url.pathname.endsWith('/work/poll')) {
      assertCondition(authorization === `Bearer ${machineSecret}`, `${target.id} bridge poll auth changed`);
      polls += 1;
      return Response.json({});
    }
    return new Response('', { status: 404 });
  };
  const bridge = await modules.machineBridge.createDesktopMachineBridge({
    userDataPath: profile,
    configuration: {
      platformOrigin: 'https://platform.example.test',
      platformAccessToken,
      aiGatewayModel: 'gateway-model',
    },
    deviceName: `platform-sandbox-${target.platform}-${target.arch}`,
    clientVersion: JSON.parse(await readFile(join(root, 'apps/desktop/package.json'), 'utf8')).version,
    platform: target.platform,
    architecture: target.arch,
    credentialStore,
    handleWork: async () => {},
    pollIntervalMs: 20,
    requestTimeoutMs: 1_000,
    fetchImpl,
  });
  try {
    bridge.start();
    await waitUntil(() => registrations === 1 && polls >= 1);
    bridge.stop();
    const identity = JSON.parse(await readFile(join(profile, 'machine-identity.json'), 'utf8'));
    assertCondition(
      identity.machineId === bridge.machineId,
      `${target.id} bridge identity was not persisted`,
    );
    assertCondition(
      registrationBodies[0]?.platform === target.platform,
      `${target.id} bridge platform payload changed`,
    );
    assertCondition(
      registrationBodies[0]?.architecture === target.arch,
      `${target.id} bridge architecture payload changed`,
    );
    return {
      registration: true,
      poll: true,
      identity: true,
      persistedSecretInMemoryOnly: persisted?.machineSecret === machineSecret,
    };
  } finally {
    bridge.stop();
    await removeOwnedTemporaryDirectory(profile);
  }
}

async function writePiFixtureGeneration(root, source, stageName, marker, piCache, layout) {
  const stage = join(root, '.cache', stageName);
  await mkdir(stage);
  await writeFile(join(stage, 'marker.txt'), marker, 'utf8');
  const artifactHash = createHash('sha256').update(marker).digest('hex');
  await writeFile(
    join(stage, 'source-lock.json'),
    `${JSON.stringify({ schemaVersion: 1, source, artifacts: { 'marker.txt': artifactHash } })}\n`,
    'utf8',
  );
  return piCache.publishPiBuildCacheGeneration(layout, stage);
}

async function runPiReaderContract(root, modules) {
  const fixture = await createOwnedTemporaryDirectory('pi-reader');
  try {
    await mkdir(join(fixture, 'pi'));
    await mkdir(join(fixture, '.cache'));
    const sourceLockContent = await readFile(join(root, 'pi-source.lock.json'), 'utf8');
    const source = JSON.parse(sourceLockContent);
    await writeFile(join(fixture, 'pi-source.lock.json'), sourceLockContent, 'utf8');
    const layout = await modules.piCache.resolveSafePiCacheLayout({ repositoryRoot: fixture });
    const first = await writePiFixtureGeneration(
      fixture,
      source,
      `pi-build-stage-${randomUUID()}`,
      'platform-sandbox-old',
      modules.piCache,
      layout,
    );
    const oldReader = await modules.piCache.pinPublishedPiBuildCache({ repositoryRoot: fixture });
    const second = await writePiFixtureGeneration(
      fixture,
      source,
      `pi-build-stage-${randomUUID()}`,
      'platform-sandbox-new',
      modules.piCache,
      layout,
    );
    const oldBytes = await modules.piCache.readPiBuildCacheArtifact(oldReader, 'marker.txt');
    assertCondition(
      oldBytes.toString('utf8') === 'platform-sandbox-old',
      'Pi reader changed generations inside one process',
    );
    const moduleUrl = pathToFileURL(resolve(root, 'scripts/pi-cache-publication.mjs')).href;
    const childScript = `
      import { readPiBuildCacheArtifact, pinPublishedPiBuildCache } from ${JSON.stringify(moduleUrl)};
      const reader = await pinPublishedPiBuildCache({ repositoryRoot: process.argv[1] });
      const content = (await readPiBuildCacheArtifact(reader, 'marker.txt')).toString('utf8');
      process.stdout.write(JSON.stringify({ generation: reader.generation, content }));
    `;
    const child = await runProcess(
      process.execPath,
      ['--input-type=module', '--eval', childScript, fixture],
      {
        cwd: root,
        env: { ...process.env, NODE_NO_WARNINGS: '1' },
        timeoutMs: 15_000,
      },
    );
    assertCondition(child.code === 0, `Pi new-reader child failed: ${child.stderr}`);
    const childResult = JSON.parse(child.stdout.trim().split(/\r?\n/u).at(-1));
    assertCondition(
      childResult.content === 'platform-sandbox-new',
      'Pi new reader did not observe the replacement generation',
    );
    assertCondition(
      oldReader.generation === first.generation && childResult.generation === second.generation,
      'Pi generation identities were not reader-atomic',
    );
    return {
      oldGeneration: first.generation,
      newGeneration: second.generation,
      oldReaderStable: true,
      newReaderSeesReplacement: true,
    };
  } finally {
    await removeOwnedTemporaryDirectory(fixture);
  }
}

async function runArtifactAndWorkflowContract(root, target, release, sandbox) {
  const [workflow, forge] = await Promise.all([
    readFile(join(root, '.github/workflows/release-desktop.yml'), 'utf8'),
    readFile(join(root, 'apps/desktop/forge.config.ts'), 'utf8'),
  ]);
  for (const runner of ['ubuntu-24.04', 'macos-15-intel', 'macos-15']) {
    assertCondition(workflow.includes(runner), `Release workflow is missing ${runner}`);
  }
  assertCondition(
    workflow.includes('platform: linux') && workflow.includes('platform: darwin'),
    'Release workflow matrix is incomplete',
  );
  assertCondition(
    forge.includes('MakerZIP') && forge.includes('MakerDMG') && forge.includes('MakerDeb'),
    'Desktop makers are incomplete',
  );
  const result = {
    workflowMatrix: true,
    makers: true,
    expectedLabel: release.assetName,
    sandboxImage: sandbox.image,
  };
  if (
    target.platform === 'win32' &&
    target.arch === 'x64' &&
    hostPlatform === 'win32' &&
    hostArch === 'x64'
  ) {
    const files = [
      join(root, 'apps/desktop/out/QoderWake-win32-x64/QoderWake.exe'),
      join(root, 'apps/desktop/out/QoderWake-win32-x64/resources/app.asar'),
      join(
        root,
        'apps/desktop/out/make/zip/win32/x64',
        `QoderWake-win32-x64-${JSON.parse(await readFile(join(root, 'apps/desktop/package.json'), 'utf8')).version}.zip`,
      ),
    ];
    const artifacts = [];
    for (const path of files) {
      await access(path);
      const details = await lstat(path);
      assertCondition(
        details.isFile() && details.size > 10_000,
        `Windows artifact is unexpectedly small: ${path}`,
      );
      artifacts.push({
        name: path.slice(root.length + 1),
        bytes: details.size,
        sha256: await sha256File(path),
      });
    }
    result.artifacts = artifacts;
  } else {
    result.artifacts = 'contract-only';
  }
  return result;
}

async function runPlatformContract(
  targetValue,
  {
    repositoryRoot: root,
    physicalPlatform = hostPlatform,
    physicalArch = hostArch,
    runNativeSmoke = false,
  } = {},
) {
  const target = targetFromValue(targetValue);
  const modules = await loadDesktopModules(root);
  const mode = physicalPlatform === target.platform && physicalArch === target.arch ? 'native' : 'simulated';
  const release = await runReleaseContract(root, target, modules);
  const sandbox = await runSandboxImageContract(target, root, modules);
  const credentials = await runCredentialContract(target, modules);
  const bridge = await runMachineBridgeContract(target, root, modules);
  const pi = await runPiReaderContract(root, modules);
  const artifacts = await runArtifactAndWorkflowContract(root, target, release, sandbox);
  let nativeSmoke;
  if (runNativeSmoke) {
    assertCondition(
      mode === 'native' && target.platform === 'win32',
      `${target.id} cannot run a native smoke on this host`,
    );
    const smoke = await runProcess(process.execPath, ['scripts/smoke-desktop.mjs'], {
      cwd: root,
      env: { ...process.env, WORKDUDE_PLATFORM_SANDBOX: '1' },
      timeoutMs: 120_000,
    });
    if (smoke.timedOut || smoke.code !== 0) {
      fail(`Windows native Desktop smoke failed: ${smoke.stderr || smoke.stdout}`);
    }
    nativeSmoke = smoke.stdout.trim().slice(-4_000);
  }
  return {
    id: target.id,
    platform: target.platform,
    arch: target.arch,
    label: target.label,
    mode,
    checks: {
      release,
      sandbox,
      credentials,
      bridge,
      pi,
      artifacts,
      ...(nativeSmoke === undefined ? {} : { nativeSmoke }),
    },
  };
}

async function verifyContainerIsolation() {
  assertCondition(
    hostPlatform === 'linux' && hostArch === 'x64',
    'Platform sandbox container must execute on Linux x64',
  );
  assertCondition(
    typeof process.getuid === 'function' && process.getuid() === 65_532,
    'Platform sandbox container must run as uid 65532',
  );
  const status = await readFile('/proc/self/status', 'utf8');
  const capEff = /^CapEff:\s*([0-9a-f]+)$/mu.exec(status)?.[1];
  assertCondition(
    capEff === '0000000000000000',
    'Platform sandbox container retained effective capabilities',
  );
  const routes = (await readFile('/proc/net/route', 'utf8')).split(/\r?\n/u).slice(1).filter(Boolean);
  assertCondition(
    !routes.some((line) => line.split(/\s+/u)[1] === '00000000'),
    'Platform sandbox container has a default network route',
  );
  for (const socket of ['/var/run/docker.sock', '/run/docker.sock']) {
    assertCondition(!existsSync(socket), `Platform sandbox container exposed ${socket}`);
  }
  const writableProbe = '/workspace/.workdude-platform-sandbox-write-probe';
  let readOnlyRejected = false;
  try {
    await writeFile(writableProbe, 'must-fail', 'utf8');
  } catch {
    readOnlyRejected = true;
  }
  if (!readOnlyRejected) {
    await unlink(writableProbe).catch(() => undefined);
  }
  assertCondition(readOnlyRejected, 'Platform sandbox repository mount is writable');
  const rootProbe = '/etc/.workdude-platform-sandbox-root-probe';
  let rootReadOnlyRejected = false;
  try {
    await writeFile(rootProbe, 'must-fail', 'utf8');
  } catch {
    rootReadOnlyRejected = true;
  }
  if (!rootReadOnlyRejected) await unlink(rootProbe).catch(() => undefined);
  assertCondition(rootReadOnlyRejected, 'Platform sandbox root filesystem is writable');
  const temporaryProbe = join('/tmp', `workdude-platform-sandbox-${randomUUID()}.tmp`);
  await writeFile(temporaryProbe, 'owned', 'utf8');
  await unlink(temporaryProbe);
  return {
    uid: process.getuid(),
    effectiveCapabilities: capEff,
    networkDefaultRoute: false,
    dockerSocket: false,
    repositoryReadOnly: true,
    rootReadOnly: true,
    ownedTmpWritable: true,
  };
}

function parseJsonLine(output) {
  const line = output
    .trim()
    .split(/\r?\n/u)
    .reverse()
    .find((candidate) => candidate.trim().startsWith('{'));
  if (!line) fail('Platform sandbox child did not emit a JSON result');
  try {
    return JSON.parse(line);
  } catch (error) {
    fail(`Platform sandbox child emitted invalid JSON: ${String(error)}`);
  }
}

function summarizeContainerInspection(value) {
  const details = value[0];
  const host = details?.HostConfig;
  const config = details?.Config;
  assertCondition(details && host && config, 'Platform sandbox Docker inspect payload is incomplete');
  const security = host.SecurityOpt ?? [];
  const capDrop = host.CapDrop ?? [];
  const mounts = (details.Mounts ?? []).map((mount) => ({
    destination: mount.Destination,
    source: mount.Source,
    rw: mount.RW,
  }));
  assertCondition(host.ReadonlyRootfs === true, 'Platform sandbox container rootfs is not read-only');
  assertCondition(host.NetworkMode === 'none', 'Platform sandbox container is not network-isolated');
  assertCondition(
    capDrop.some((value) => String(value).toUpperCase() === 'ALL'),
    'Platform sandbox did not drop all capabilities',
  );
  assertCondition(
    security.some((value) => String(value).startsWith('no-new-privileges')),
    'Platform sandbox lacks no-new-privileges',
  );
  assertCondition(
    host.PidsLimit === 128 && host.NanoCpus === 1_000_000_000 && host.Memory === 768 * 1024 * 1024,
    'Platform sandbox resource bounds changed',
  );
  assertCondition(config.User === '65532:65532', 'Platform sandbox user boundary changed');
  assertCondition(
    host.PidMode !== 'host' && host.IpcMode !== 'host',
    'Platform sandbox joined a host namespace',
  );
  assertCondition(
    !mounts.some(
      ({ source, destination }) =>
        String(source).includes('docker.sock') || String(destination).includes('docker.sock'),
    ),
    'Platform sandbox mounted a Docker socket',
  );
  const workspace = mounts.find(({ destination }) => destination === '/workspace');
  assertCondition(workspace && workspace.rw === false, 'Platform sandbox source mount is not read-only');
  return {
    containerId: String(details.Id).slice(0, 12),
    status: details.State?.Status,
    exitCode: details.State?.ExitCode,
    readonlyRootfs: host.ReadonlyRootfs,
    networkMode: host.NetworkMode,
    capDrop,
    securityOpt: security,
    pidsLimit: host.PidsLimit,
    nanoCpus: host.NanoCpus,
    memoryBytes: host.Memory,
    user: config.User,
    pidMode: host.PidMode ?? null,
    ipcMode: host.IpcMode ?? null,
    mounts,
  };
}

async function runDockerCell(root, targets) {
  await commandOutput('docker', ['image', 'inspect', NODE_IMAGE], { cwd: root, timeoutMs: 15_000 });
  const name = `workdude-platform-sandbox-${randomUUID()}`;
  const invocation = buildPlatformSandboxDockerInvocation({
    repositoryRoot: root,
    targets,
    containerName: name,
  });
  const run = await runProcess(invocation.command, invocation.args, {
    cwd: root,
    env: { ...process.env, WORKDUDE_PLATFORM_SANDBOX: 'host-orchestrator' },
    timeoutMs: 180_000,
  });
  let inspection;
  let inspectError;
  try {
    const inspected = await runProcess('docker', ['inspect', name], { cwd: root, timeoutMs: 15_000 });
    if (inspected.code === 0) {
      try {
        inspection = summarizeContainerInspection(JSON.parse(inspected.stdout));
      } catch (error) {
        inspectError = error;
      }
    } else {
      inspectError = new Error(inspected.stderr || inspected.stdout || 'Docker inspect failed');
    }
  } finally {
    const removed = await runProcess('docker', ['rm', '-f', name], { cwd: root, timeoutMs: 15_000 });
    if (removed.code !== 0 && !/No such container/iu.test(`${removed.stdout}\n${removed.stderr}`)) {
      fail(`Owned platform sandbox container cleanup failed: ${removed.stderr || removed.stdout}`);
    }
    const leftovers = await runProcess(
      'docker',
      ['ps', '-a', '--filter', `name=^/${name}$`, '--format', '{{.ID}}'],
      { cwd: root, timeoutMs: 15_000 },
    );
    if (leftovers.code !== 0 || leftovers.stdout.trim())
      fail(`Owned platform sandbox container residue remains: ${leftovers.stdout || leftovers.stderr}`);
  }
  if (run.timedOut || run.code !== 0) {
    const detail = `${run.stdout}\n${run.stderr}`.trim().slice(-16_000);
    fail(`Linux platform sandbox cell failed (${run.code ?? run.signal}): ${detail}`);
  }
  if (inspectError) fail(`Linux platform sandbox isolation inspection failed: ${String(inspectError)}`);
  const child = parseJsonLine(run.stdout);
  assertCondition(child.status === 'passed', 'Linux platform sandbox child did not pass');
  assertCondition(
    child.containerIsolation?.repositoryReadOnly === true,
    'Linux platform sandbox child missed read-only proof',
  );
  return { invocation, inspection, child, cleaned: true };
}

async function runInsideContainer(root, targets) {
  const isolation = await verifyContainerIsolation();
  const results = [];
  for (const target of targets) {
    results.push(
      await runPlatformContract(target, {
        repositoryRoot: root,
        physicalPlatform: hostPlatform,
        physicalArch: hostArch,
      }),
    );
  }
  return {
    schemaVersion: 1,
    status: 'passed',
    host: { platform: hostPlatform, arch: hostArch, node: process.version, insideContainer: true },
    containerIsolation: isolation,
    targets: results,
  };
}

export async function runDesktopPlatformSandbox({
  repositoryRoot: root = repositoryRoot,
  targets: targetSpec = 'all',
  runNativeSmoke = false,
  useDocker = true,
  insideContainer = false,
} = {}) {
  const resolvedRoot = await resolveRepositoryRoot(root);
  const targets = normalizeTargetValues(targetSpec);
  if (insideContainer) return runInsideContainer(resolvedRoot, targets);
  const nativeTargets = targets.filter((target) => target.platform === 'win32');
  const nonWindowsTargets = targets.filter((target) => target.platform !== 'win32');
  const results = [];
  for (const target of nativeTargets) {
    results.push(
      await runPlatformContract(target, {
        repositoryRoot: resolvedRoot,
        runNativeSmoke: runNativeSmoke && target.platform === hostPlatform && target.arch === hostArch,
      }),
    );
  }
  let container;
  if (nonWindowsTargets.length && useDocker) {
    container = await runDockerCell(resolvedRoot, nonWindowsTargets);
    results.push(...(container.child.targets ?? []));
  } else {
    for (const target of nonWindowsTargets) {
      results.push(await runPlatformContract(target, { repositoryRoot: resolvedRoot }));
    }
  }
  return {
    schemaVersion: 1,
    status: 'passed',
    host: { platform: hostPlatform, arch: hostArch, node: process.version, insideContainer: false },
    targets: results,
    ...(container === undefined ? {} : { container }),
  };
}

function argumentValue(name, fallback) {
  const prefix = `--${name}=`;
  return process.argv.find((argument) => argument.startsWith(prefix))?.slice(prefix.length) ?? fallback;
}

async function runCli() {
  const result = await runDesktopPlatformSandbox({
    targets: argumentValue('targets', 'all'),
    runNativeSmoke: !process.argv.includes('--skip-native-smoke'),
    useDocker: !process.argv.includes('--no-docker'),
    insideContainer: process.argv.includes('--inside-container'),
  });
  if (process.argv.includes('--json')) {
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } else {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  }
}

if (process.argv[1] && samePath(process.argv[1], fileURLToPath(import.meta.url))) {
  try {
    await runCli();
  } catch (error) {
    if (process.argv.includes('--json')) {
      process.stderr.write(
        `${JSON.stringify({ schemaVersion: 1, status: 'failed', error: String(error) })}\n`,
      );
      process.exitCode = 1;
    } else {
      throw error;
    }
  }
}
