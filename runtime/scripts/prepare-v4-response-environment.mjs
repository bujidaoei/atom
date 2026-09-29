import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { createServer } from 'node:net';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { URL } from 'node:url';

const root = process.cwd();
const environmentFile = resolve(root, '.env');
if (!existsSync(environmentFile)) {
  throw new Error('The protected .env file is required for the V4 response E2E gate.');
}
if (typeof process.loadEnvFile === 'function') process.loadEnvFile(environmentFile);

const composeFile = resolve(root, 'deploy/compose/compose.yaml');
const responseRuntimeComposeFile = resolve(root, 'deploy/compose/compose.response-runtime.yaml');
const responseComposeFile = resolve(root, 'deploy/compose/compose.response.yaml');
const DOCKER_DAEMON_PROBE_TIMEOUT_MS = 8_000;

function dockerName(label, value) {
  if (!/^[a-z0-9][a-z0-9_-]{0,62}$/u.test(value)) {
    throw new Error(`${label} must be a Docker-safe name no longer than 63 characters`);
  }
  return value;
}

function derivedDockerName(label, value, maxLength = 63) {
  if (!/^[a-z0-9][a-z0-9_-]*$/u.test(value)) {
    throw new Error(`${label} contains characters that are not safe for Docker`);
  }
  if (value.length <= maxLength) return dockerName(label, value);
  const digest = createHash('sha256').update(value).digest('hex').slice(0, 10);
  const prefixLength = maxLength - digest.length - 1;
  if (prefixLength < 1) throw new Error(`${label} cannot be shortened safely`);
  return dockerName(label, `${value.slice(0, prefixLength)}-${digest}`);
}

const responseProject = dockerName(
  'response project',
  process.env.WORKDUDE_V4_RESPONSE_PROJECT?.trim() || `workdude-v4-response-${process.pid}`,
);
const configuredFailureProjectPrefix = process.env.WORKDUDE_V4_RESPONSE_FAILURE_PREFIX?.trim();
const failureProjectPrefix = configuredFailureProjectPrefix
  ? dockerName('failure project prefix', configuredFailureProjectPrefix)
  : derivedDockerName('failure project prefix', `${responseProject}-failure`);
const reservedComposeProjects = new Set(['workdude', 'sub2api', 'deploy_sub2api']);
if (reservedComposeProjects.has(responseProject)) {
  throw new Error('response project must be isolated from an existing production project');
}
if (reservedComposeProjects.has(failureProjectPrefix)) {
  throw new Error('failure project prefix must be isolated from an existing production project');
}

function parseResponseOrigin(origin, fallbackPort, label = 'response origin') {
  const raw = String(origin).trim();
  if (String(origin) !== raw) {
    throw new Error(`${label} must not contain surrounding whitespace`);
  }
  const canonical = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5})$/u.exec(raw);
  if (!canonical) {
    throw new Error(`${label} must be a canonical loopback HTTP URL with an explicit port`);
  }
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(`${label} must be a valid loopback HTTP URL`);
  }
  const hostname = canonical[1].replace(/^\[|\]$/gu, '').toLowerCase();
  if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost', '::1'].includes(hostname)) {
    throw new Error(`${label} must use loopback HTTP`);
  }
  const port = Number(canonical[2] ?? fallbackPort);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${label} port must be an integer from 1 to 65535`);
  }
  const displayHost = hostname.includes(':') ? `[${hostname}]` : hostname;
  const normalized = `http://${displayHost}:${port}`;
  if (raw !== normalized || parsed.username || parsed.password || parsed.pathname !== '/') {
    throw new Error(`${label} must not contain credentials, a path, query or fragment`);
  }
  return { origin: normalized, port };
}

function portFromOrigin(origin, fallback) {
  return parseResponseOrigin(origin, fallback).port;
}

function normalizeResponseOrigin(origin, fallbackPort, label) {
  return parseResponseOrigin(origin, fallbackPort, label).origin;
}

function previewPortFor(publicPort, configured) {
  const configuredPort = configured?.trim();
  const candidate = configuredPort
    ? Number(configuredPort)
    : publicPort === 8080
      ? 3000
      : publicPort + 10_000;
  if (!Number.isInteger(candidate) || candidate < 1 || candidate > 65_535) {
    throw new Error('response preview port must be an integer from 1 to 65535');
  }
  if (candidate === publicPort) throw new Error('response preview port must differ from the public port');
  // Keep the default fixture ports stable, while making custom response origins
  // self-contained and collision-free with the long-lived development stack.
  return String(candidate);
}

function assertPortAvailable(port, label) {
  return new Promise((resolve, reject) => {
    const server = createServer();
    const timer = globalThis.setTimeout(() => {
      server.close();
      reject(new Error(`${label} port ${port} availability check timed out`));
    }, 5_000);
    const finish = (error) => {
      globalThis.clearTimeout(timer);
      server.removeAllListeners();
      if (error) reject(error);
      else resolve();
    };
    server.once('error', () => finish(new Error(`${label} port ${port} is already in use`)));
    server.once('listening', () => server.close(() => finish()));
    server.listen({ host: '127.0.0.1', port, exclusive: true });
  });
}

function workspaceVolume(project) {
  return derivedDockerName('response workspace volume', `${project}_workdude-data`);
}

function postgresVolume(project) {
  return derivedDockerName('response postgres volume', `${project}_postgres-data`);
}

function redisVolume(project) {
  return derivedDockerName('response redis volume', `${project}_redis-data`);
}

function failureGatewayCaddyVolume(project) {
  return derivedDockerName('response gateway certificate volume', `${project}_failure-gateway-caddy-data`);
}

function failureProjectFor(kind) {
  return derivedDockerName('failure project', `${failureProjectPrefix}-${kind}`);
}

function responseNetwork(project) {
  // Reserve room for the longest logical suffix ("-sandbox-control").
  return derivedDockerName('response network base', `${project}_response-network`, 47);
}

const responseNetworkKinds = ['edge', 'application', 'data', 'egress', 'sandbox-control'];
const responseInternalNetworkKinds = new Set(['application', 'data', 'sandbox-control']);

function responseNetworkName(baseName, kind) {
  return derivedDockerName('response network', `${baseName}-${kind}`);
}

function responseSubnet(project, kind, attempt) {
  const digest = createHash('sha256').update(`${project}:${kind}:${attempt}`).digest();
  const thirdOctet = 1 + (digest.readUInt16BE(0) % 254);
  return `10.240.${thirdOctet}.0/24`;
}

function inspectResponseNetwork(name) {
  const inspect = spawnSync('docker', ['network', 'inspect', name, '--format', '{{json .}}'], {
    cwd: root,
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
    encoding: 'utf8',
    timeout: 8_000,
    windowsHide: true,
  });
  if (inspect.error) throw inspect.error;
  if (inspect.status !== 0) {
    const errorText = String(inspect.stderr ?? '').toLowerCase();
    if (!errorText.includes('no such network') && !errorText.includes('not found')) {
      throw new Error(`response network ${name} could not be inspected`);
    }
    return null;
  }
  try {
    return JSON.parse(String(inspect.stdout).trim());
  } catch {
    throw new Error(`response network ${name} metadata is invalid`);
  }
}

function validateResponseNetwork(project, kind, metadata) {
  if (
    metadata?.Driver !== 'bridge' ||
    metadata?.Labels?.['com.workdude.response'] !== 'true' ||
    metadata?.Labels?.['com.workdude.response.project'] !== project ||
    metadata?.Labels?.['com.workdude.response.kind'] !== kind ||
    metadata?.Internal !== responseInternalNetworkKinds.has(kind)
  ) {
    throw new Error(`${project} response network ${kind} is not a managed bridge network`);
  }
}

function ensureResponseNetworks(project, environment) {
  const baseName = environment.WORKDUDE_RESPONSE_NETWORK_NAME;
  if (!baseName) throw new Error(`${project} response network name is required`);
  for (const kind of responseNetworkKinds) {
    const name = responseNetworkName(baseName, kind);
    const existing = inspectResponseNetwork(name);
    if (existing) {
      validateResponseNetwork(project, kind, existing);
      continue;
    }

    let created = false;
    for (let attempt = 0; attempt < 64 && !created; attempt += 1) {
      const create = spawnSync(
        'docker',
        [
          'network',
          'create',
          '--driver',
          'bridge',
          ...(responseInternalNetworkKinds.has(kind) ? ['--internal'] : []),
          '--subnet',
          responseSubnet(project, kind, attempt),
          '--label',
          'com.workdude.response=true',
          '--label',
          `com.workdude.response.project=${project}`,
          '--label',
          `com.workdude.response.kind=${kind}`,
          name,
        ],
        {
          cwd: root,
          env: process.env,
          stdio: ['ignore', 'pipe', 'pipe'],
          encoding: 'utf8',
          timeout: 8_000,
          windowsHide: true,
        },
      );
      if (create.error) throw create.error;
      if (create.status === 0) {
        created = true;
        continue;
      }
      const raced = inspectResponseNetwork(name);
      if (raced) {
        validateResponseNetwork(project, kind, raced);
        created = true;
        continue;
      }
      const errorText = String(create.stderr ?? '').toLowerCase();
      if (!errorText.includes('overlap') && !errorText.includes('subnet')) break;
    }
    if (!created) throw new Error(`${project} response network ${kind} could not be created`);
  }
}

function assertDockerDaemonReady() {
  const probe = spawnSync('docker', ['version', '--format', '{{.Server.Version}}'], {
    cwd: root,
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
    encoding: 'utf8',
    timeout: DOCKER_DAEMON_PROBE_TIMEOUT_MS,
    windowsHide: true,
  });
  if (probe.error || probe.status !== 0 || !String(probe.stdout ?? '').trim()) {
    const timedOut = probe.error?.code === 'ETIMEDOUT' || probe.signal !== null;
    throw new Error(
      `Docker daemon is unavailable before response setup (${timedOut ? 'probe timed out' : 'probe failed'}).`,
    );
  }
}

function start(project, environment, build, additionalComposeFiles = [], forceRecreate = false) {
  ensureResponseNetworks(project, environment);
  const compose = spawnSync(
    'docker',
    [
      'compose',
      '--env-file',
      environmentFile,
      '-p',
      project,
      '-f',
      composeFile,
      ...additionalComposeFiles.flatMap((file) => ['-f', file]),
      'up',
      '-d',
      build ? '--build' : '--no-build',
      ...(forceRecreate ? ['--force-recreate'] : []),
    ],
    { cwd: root, env: { ...process.env, ...environment }, stdio: 'inherit' },
  );
  if (compose.error) throw compose.error;
  if (compose.status !== 0) {
    throw new Error(`${project} response environment failed to start (exit ${compose.status ?? 1}).`);
  }
}

function teardownEnvironment(project) {
  return {
    WORKDUDE_AUTH_MODE: 'legacy',
    PUBLIC_PORT: '1',
    PREVIEW_PORT: '2',
    PUBLIC_BASE_URL: 'http://127.0.0.1:1',
    WORKDUDE_GATEWAY_FAILURE_MODE: 'authentication',
    LITELLM_MODEL: process.env.LITELLM_MODEL || 'fixture/model',
    WORKSPACE_VOLUME: workspaceVolume(project),
    POSTGRES_VOLUME: postgresVolume(project),
    REDIS_VOLUME: redisVolume(project),
    FAILURE_GATEWAY_CADDY_VOLUME: failureGatewayCaddyVolume(project),
    WORKDUDE_RESPONSE_NETWORK_NAME: responseNetwork(project),
  };
}

function composeDown(project, failure) {
  const environment = teardownEnvironment(project);
  const additionalComposeFiles = failure
    ? [responseRuntimeComposeFile, responseComposeFile]
    : [responseRuntimeComposeFile];
  const result = spawnSync(
    'docker',
    [
      'compose',
      '--env-file',
      environmentFile,
      '-p',
      project,
      '-f',
      composeFile,
      ...additionalComposeFiles.flatMap((file) => ['-f', file]),
      'down',
      '--remove-orphans',
      '--volumes',
    ],
    {
      cwd: root,
      env: { ...process.env, ...environment },
      stdio: 'inherit',
      timeout: 60_000,
      windowsHide: true,
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${project} response teardown failed`);
}

function removeManagedResponseNetwork(project, kind) {
  const baseName = responseNetwork(project);
  const name = responseNetworkName(baseName, kind);
  const metadata = inspectResponseNetwork(name);
  if (!metadata) return;
  validateResponseNetwork(project, kind, metadata);
  if (Object.keys(metadata.Containers ?? {}).length > 0) {
    throw new Error(`${project} response network ${kind} still has attached containers`);
  }
  const result = spawnSync('docker', ['network', 'rm', name], {
    cwd: root,
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
    encoding: 'utf8',
    timeout: 8_000,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${project} response network ${kind} could not be removed`);
}

async function teardownResponseEnvironment() {
  assertDockerDaemonReady();
  const entries = [
    { project: responseProject, failure: false },
    ...['auth', 'model', 'timeout'].map((kind) => ({ project: failureProjectFor(kind), failure: true })),
  ];
  const errors = [];
  for (const entry of entries) {
    try {
      const managed = responseNetworkKinds.some((kind) => {
        const metadata = inspectResponseNetwork(responseNetworkName(responseNetwork(entry.project), kind));
        if (!metadata) return false;
        validateResponseNetwork(entry.project, kind, metadata);
        return true;
      });
      if (!managed) {
        console.log(`[v4-response] No managed network found for ${entry.project}; skipping teardown.`);
        continue;
      }
      composeDown(entry.project, entry.failure);
    } catch (error) {
      errors.push(error instanceof Error ? error.message : `${entry.project} teardown failed`);
    }
  }
  for (const entry of entries) {
    for (const kind of responseNetworkKinds) {
      try {
        removeManagedResponseNetwork(entry.project, kind);
      } catch (error) {
        errors.push(error instanceof Error ? error.message : `${entry.project} network cleanup failed`);
      }
    }
  }
  if (errors.length > 0) throw new Error(errors.join('; '));
}

async function waitReady(origin) {
  const deadline = Date.now() + 180_000;
  let lastFailure;
  while (Date.now() < deadline) {
    try {
      const response = await globalThis.fetch(`${origin}/health/live`, {
        redirect: 'error',
        signal: globalThis.AbortSignal.timeout(5_000),
      });
      if (response.ok) {
        await response.body?.cancel();
        console.log(`[v4-response] Web deployment is ready at ${origin}.`);
        return;
      }
      lastFailure = new Error(`HTTP ${response.status}`);
      await response.body?.cancel();
    } catch (cause) {
      lastFailure = cause;
    }
    await delay(1_000);
  }
  throw new Error(`V4 response environment did not become ready at ${origin}.`, { cause: lastFailure });
}

if (process.argv.includes('--teardown')) {
  await teardownResponseEnvironment();
  process.exit(0);
}

const mainOriginInput = process.env.WORKDUDE_V4_WEB_ORIGIN ?? 'http://127.0.0.1:8080';
const mainPublicPort = portFromOrigin(mainOriginInput, 8080);
const mainOrigin = normalizeResponseOrigin(mainOriginInput, mainPublicPort, 'main response origin');
// Response E2E exercises the isolated fixture-owner protocol, not the real
// Feishu provider. Force the explicit legacy test mode for every Compose
// project so a developer/production `.env` cannot silently change the auth
// contract or require provider credentials during this gate.
const responseAuthEnvironment = {
  WORKDUDE_AUTH_MODE: 'legacy',
  PUBLIC_PORT: String(mainPublicPort),
  PREVIEW_PORT: previewPortFor(mainPublicPort, process.env.WORKDUDE_V4_WEB_PREVIEW_PORT),
  PUBLIC_BASE_URL: mainOrigin,
  WORKSPACE_VOLUME: workspaceVolume(responseProject),
  POSTGRES_VOLUME: postgresVolume(responseProject),
  REDIS_VOLUME: redisVolume(responseProject),
  FAILURE_GATEWAY_CADDY_VOLUME: failureGatewayCaddyVolume(responseProject),
  WORKDUDE_RESPONSE_NETWORK_NAME: responseNetwork(responseProject),
};
const failures = [
  ['auth', process.env.WORKDUDE_V4_WEB_AUTH_FAILURE_ORIGIN ?? 'http://127.0.0.1:8181', 'authentication'],
  ['model', process.env.WORKDUDE_V4_WEB_MODEL_FAILURE_ORIGIN ?? 'http://127.0.0.1:8182', 'model'],
  ['timeout', process.env.WORKDUDE_V4_WEB_TIMEOUT_FAILURE_ORIGIN ?? 'http://127.0.0.1:8183', 'timeout'],
].map(([kind, originInput, mode], index) => {
  const project = failureProjectFor(kind);
  const publicPort = portFromOrigin(originInput, 8181 + index);
  const origin = normalizeResponseOrigin(originInput, publicPort, `${kind} failure origin`);
  return {
    project,
    origin,
    environment: {
      PUBLIC_PORT: String(publicPort),
      PREVIEW_PORT: previewPortFor(
        publicPort,
        process.env[`WORKDUDE_V4_${String(kind).toUpperCase()}_PREVIEW_PORT`],
      ),
      PUBLIC_BASE_URL: origin,
      WORKDUDE_GATEWAY_FAILURE_MODE: mode,
      ...(mode === 'timeout'
        ? { WORKDUDE_GATEWAY_FAILURE_DELAY_MS: '10000', LITELLM_REQUEST_TIMEOUT_MS: '1000' }
        : {}),
      WORKSPACE_VOLUME: workspaceVolume(project),
      POSTGRES_VOLUME: postgresVolume(project),
      REDIS_VOLUME: redisVolume(project),
      FAILURE_GATEWAY_CADDY_VOLUME: failureGatewayCaddyVolume(project),
      WORKDUDE_RESPONSE_NETWORK_NAME: responseNetwork(project),
    },
  };
});

const publishedPorts = new Set();
for (const entry of [
  { kind: 'main', publicPort: mainPublicPort, previewPort: Number(responseAuthEnvironment.PREVIEW_PORT) },
  ...failures.map(({ project, environment }) => ({
    kind: project,
    publicPort: Number(environment.PUBLIC_PORT),
    previewPort: Number(environment.PREVIEW_PORT),
  })),
]) {
  for (const [label, port] of [
    ['public', entry.publicPort],
    ['preview', entry.previewPort],
  ]) {
    if (publishedPorts.has(port)) {
      throw new Error(`response ${label} port ${port} is already assigned to another fixture`);
    }
    publishedPorts.add(port);
  }
}

for (const entry of [
  { kind: 'main public', port: mainPublicPort },
  { kind: 'main preview', port: Number(responseAuthEnvironment.PREVIEW_PORT) },
  ...failures.flatMap(({ project, environment }) => [
    { kind: `${project} public`, port: Number(environment.PUBLIC_PORT) },
    { kind: `${project} preview`, port: Number(environment.PREVIEW_PORT) },
  ]),
]) {
  await assertPortAvailable(entry.port, entry.kind);
}
assertDockerDaemonReady();

start(responseProject, responseAuthEnvironment, true, [responseRuntimeComposeFile]);
await waitReady(mainOrigin);

for (const failure of failures) {
  start(
    failure.project,
    { ...responseAuthEnvironment, ...failure.environment },
    false,
    [responseRuntimeComposeFile, responseComposeFile],
    true,
  );
  await waitReady(failure.origin);
}
