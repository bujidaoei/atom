import { Buffer } from 'node:buffer';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { lstat, readFile, readdir } from 'node:fs/promises';
import { basename, dirname, extname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

import { createLineResolver } from './scan-line-index.mjs';
import {
  forEachUtf16AsciiString,
  mapScansInOrder,
  scanBufferForSecrets,
  scanV3Secrets,
} from './scan-v3-secrets.mjs';
import {
  auditAsarArtifact,
  auditElectronExecutable,
  filterExactVendorArtifactSecrets,
} from './asar-artifact-audit.mjs';
import {
  readPiBuildCacheArtifact,
  resolvePiCacheReaderLayout,
  resolvePublishedPiBuildCache,
} from './pi-cache-publication.mjs';
import { hasGatewayOnlyPiRuntimeBoundary, readPiGatewayRuntimeSnapshot } from './pi-gateway-runtime.mjs';
import { verifyPiModelDataCache } from './pi-model-data-boundary.mjs';

const execute = promisify(execFile);
const defaultRepositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const v4SecretEnvironmentNames = [
  'LITELLM_MASTER_KEY',
  'STORAGE_S3_ACCESS_KEY',
  'STORAGE_S3_SECRET_KEY',
  'app_secret',
  'APP_SECRET_ENCRYPTION_KEY',
  'FEISHU_AUTH_ENCRYPTION_KEY',
  'SANDBOX_BROKER_TOKEN',
  'APP_ACCESS_TOKEN',
  'DESKTOP_PLATFORM_ACCESS_TOKEN',
  'WORKDUDE_PLATFORM_ACCESS_TOKEN',
  'GITHUB_TOKEN',
  'GH_TOKEN',
];

const artifactRoots = [
  { category: 'bundle', path: 'dist' },
  { category: 'bundle', path: 'build' },
  { category: 'bundle', path: 'out' },
  { category: 'bundle', path: 'apps/desktop/out' },
  { category: 'log', path: 'logs' },
  { category: 'log', path: 'test-results' },
  { category: 'log', path: 'playwright-report' },
  { category: 'evidence', path: 'output' },
  { category: 'evidence', path: 'specs/004-qoderwake-v4-parity/evidence' },
  { category: 'export', path: 'exports' },
  { category: 'release', path: 'release' },
  { category: 'release', path: 'releases' },
  { category: 'container', path: 'container-exports' },
  { category: 'container', path: 'container-images' },
  { category: 'container', path: 'containers' },
  { category: 'package', path: '.cache/pi-build-current.json', piCache: true, required: true },
];

const directProviderArtifactCategories = new Set(['bundle', 'container', 'export', 'package', 'release']);
const productionRoots = ['apps/', 'packages/', 'services/', 'deploy/', '.github/workflows/', 'scripts/'];
const rootProductionFiles = new Set([
  '.env.example',
  '.npmrc',
  'package-lock.json',
  'package.json',
  'tsconfig.json',
]);
const productionExtensions = new Set([
  '.bash',
  '.cjs',
  '.conf',
  '.config',
  '.dockerfile',
  '.example',
  '.ini',
  '.js',
  '.json',
  '.jsx',
  '.mjs',
  '.mts',
  '.ps1',
  '.properties',
  '.sh',
  '.sql',
  '.toml',
  '.ts',
  '.tsx',
  '.yaml',
  '.yml',
  '.zsh',
]);
const ignoredSourceSegments = new Set(['.vite', 'node_modules', 'out', 'test', 'tests']);
const offlinePiCatalogPrefix = 'deploy/compose/pi-model-data/';
const offlinePiCatalogManifest = `${offlinePiCatalogPrefix}.manifest.json`;
const piBuildGenerationPattern = /^pi-build-generation-[a-f0-9]{64}$/u;
// provider-audit-definition:start v4-provider-detector-data
const exactHistoricalProviderLines = new Map([
  [
    'packages/data-access/src/v3/sqlite-execution-repository.ts',
    ["        provider TEXT NOT NULL CHECK (provider = 'deepseek'),"],
  ],
  [
    'services/migrations/sql/001_v3_core.sql',
    ["  provider text NOT NULL DEFAULT 'deepseek' CHECK (provider = 'deepseek'),"],
  ],
  ['services/migrations/sql/032_v4_enterprise_ai_gateway.sql', ["  WHERE provider='deepseek'"]],
]);
const exactHistoricalProviderFileHashes = new Map([
  [
    'packages/data-access/src/v3/sqlite-execution-repository.ts',
    'fdea83775857be6e5ae8e5091121be8dde99caf244ece507537626709898c252',
  ],
  [
    'services/migrations/sql/001_v3_core.sql',
    'e4ae65610ff05da08789181b3beb00c7c547f8ef42b60b500575aa53bed83f0d',
  ],
  [
    'services/migrations/sql/032_v4_enterprise_ai_gateway.sql',
    '388bd520636722e6430a5313f71393a8eae161adcf5addb8b4a925eb39c72a8d',
  ],
]);
const directProviderSdkPackages = [
  '@ai-sdk',
  '@anthropic-ai/sdk',
  '@aws-sdk/client-bedrock-runtime',
  '@azure/openai',
  '@github/copilot-sdk',
  '@google-cloud/vertexai',
  '@google/generative-ai',
  '@google/genai',
  '@huggingface/inference',
  '@mistralai/mistralai',
  '@openrouter/sdk',
  '@xai/sdk',
  'groq-sdk',
  'mistralai',
  'openai',
  'together-ai',
];
const explicitProviderEnvironmentNames = [
  'AI_GATEWAY_API_KEY',
  'ANTHROPIC_AUTH_TOKEN',
  'AWS_BEDROCK_API_KEY',
  'AZURE_OPENAI_API_KEY',
  'AZURE_OPENAI_BASE_URL',
  'AZURE_OPENAI_ENDPOINT',
  'CLOUDFLARE_AI_GATEWAY_API_TOKEN',
  'COPILOT_GITHUB_TOKEN',
  'DASHSCOPE_API_KEY',
  'GEMINI_API_KEY',
  'GITHUB_COPILOT_TOKEN',
  'GOOGLE_APPLICATION_CREDENTIALS',
  'GOOGLE_VERTEX_API_KEY',
  'HF_TOKEN',
  'KIMI_API_KEY',
];
// provider-audit-definition:end v4-provider-detector-data

const exactDetectorDefinitionRanges = new Map([
  [
    'scripts/scan-v3-secrets.mjs',
    new Map([
      ['v3-secret-environment-names', '4e14793f1137a3cb1080d09873c2cd29b258775d2e4866b17e5215773206cd8a'],
    ]),
  ],
  [
    'scripts/scan-v4-secrets.mjs',
    new Map([
      ['v4-provider-detector-data', 'c55806654f1c54591b2c62b1d54e4f6fa1e949fdee05ebd42dff7ca9df2ce422'],
    ]),
  ],
]);

function displayPath(root, path) {
  const candidate = relative(root, path).replaceAll('\\', '/');
  return candidate && !candidate.startsWith('../') ? candidate : basename(path);
}

function isEphemeralStagingPath(path) {
  const normalized = path.replaceAll('\\', '/').toLowerCase();
  return /(?:\.failed-[^/]+|\.after-zip-failure|\.previous-local-check)(?:\/|$)/u.test(normalized);
}

function maskExactHistoricalProviderLines(path, text) {
  const canonicalPath = [...exactHistoricalProviderLines.keys()].find(
    (candidate) => path === candidate || path.endsWith(`/${candidate}`),
  );
  if (!canonicalPath) return text;
  const expectedHash = exactHistoricalProviderFileHashes.get(canonicalPath);
  const actualHash = createHash('sha256').update(text.replaceAll('\r\n', '\n')).digest('hex');
  if (!expectedHash || actualHash !== expectedHash) return text;
  const allowed = exactHistoricalProviderLines.get(canonicalPath);
  if (!allowed) return text;
  const lines = text.split('\n');
  for (const exact of allowed) {
    const matches = lines.flatMap((line, index) => (line.replace(/\r$/u, '') === exact ? [index] : []));
    if (matches.length !== 1) continue;
    const index = matches[0];
    lines[index] = lines[index].replace(/[^\r]/gu, ' ');
  }
  return lines.join('\n');
}

function maskExactDetectorDefinitionRanges(path, text) {
  const definitions = exactDetectorDefinitionRanges.get(path);
  if (!definitions) return text;
  const lines = text.split('\n');
  for (const [name, expectedHash] of definitions) {
    const startMarker = `// provider-audit-definition:start ${name}`;
    const endMarker = `// provider-audit-definition:end ${name}`;
    const starts = lines.flatMap((line, index) => (line.trim() === startMarker ? [index] : []));
    const ends = lines.flatMap((line, index) => (line.trim() === endMarker ? [index] : []));
    if (starts.length !== 1 || ends.length !== 1 || starts[0] >= ends[0]) continue;
    const actualHash = createHash('sha256')
      .update(
        lines
          .slice(starts[0], ends[0] + 1)
          .map((line) => line.replace(/\r$/u, ''))
          .join('\n'),
      )
      .digest('hex');
    if (actualHash !== expectedHash) continue;
    for (let index = starts[0]; index <= ends[0]; index += 1) {
      lines[index] = lines[index].replace(/[^\r]/gu, ' ');
    }
  }
  return lines.join('\n');
}

function providerAuditMaskApplies(path) {
  return (
    exactDetectorDefinitionRanges.has(path) ||
    [...exactHistoricalProviderLines.keys()].some(
      (candidate) => path === candidate || path.endsWith(`/${candidate}`),
    )
  );
}

function fingerprint(value) {
  return createHash('sha256').update(value).digest('hex').slice(0, 12);
}

function isProductionSource(path) {
  const normalized = path.replaceAll('\\', '/');
  const rootName = normalized.includes('/') ? '' : normalized.toLowerCase();
  const rootConfig =
    rootProductionFiles.has(rootName) ||
    /(?:^|\.)config\.(?:cjs|js|json|mjs|mts|ts|yaml|yml)$/u.test(rootName) ||
    rootName.startsWith('dockerfile');
  if (!rootConfig && !productionRoots.some((prefix) => normalized.startsWith(prefix))) return false;
  const segments = normalized.split('/');
  if (segments.some((segment) => ignoredSourceSegments.has(segment))) return false;
  if (normalized === offlinePiCatalogManifest) return false;
  const name = basename(normalized).toLowerCase();
  return (
    productionExtensions.has(extname(name)) ||
    name === 'caddyfile' ||
    name.startsWith('dockerfile') ||
    name.endsWith('dockerfile') ||
    name === '.env.example'
  );
}

async function gitWorktreeFiles(root) {
  const result = await execute('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
    cwd: root,
    encoding: 'buffer',
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
  });
  return result.stdout.toString('utf8').split('\0').filter(Boolean);
}

async function collectArtifactFiles(path, repositoryRoot) {
  let entry;
  try {
    entry = await lstat(path);
  } catch (error) {
    if (error && typeof error === 'object' && error.code === 'ENOENT') return [];
    throw error;
  }
  if (entry.isSymbolicLink()) {
    throw new Error(
      `Artifact root contains a symbolic link or junction: ${displayPath(repositoryRoot, path)}`,
    );
  }
  if (entry.isFile()) return [path];
  if (!entry.isDirectory()) return [];
  const name = basename(path).toLowerCase();
  if (name === '.git') return [];
  // Electron Forge leaves failed/previous local package attempts beside the
  // authoritative package. They are disposable staging debris, not release
  // inputs; scanning every duplicate executable multiplies the native audit.
  // The successful package and maker directories remain fully scanned.
  if (
    name.includes('.failed-') ||
    name.endsWith('.after-zip-failure') ||
    name.endsWith('.previous-local-check')
  )
    return [];
  // Directory enumeration order is platform/filesystem dependent. Sort once
  // before flattening so the bounded worker pool receives a stable source
  // order and findings remain deterministic across runs and hosts.
  const children = (await readdir(path)).sort();
  return (
    await Promise.all(children.map((child) => collectArtifactFiles(resolve(path, child), repositoryRoot)))
  ).flat();
}

async function loadOfflinePiCatalogManifest(repositoryRoot, verifyHashes = true) {
  const result = await verifyPiModelDataCache({
    cacheRoot: resolve(repositoryRoot, offlinePiCatalogPrefix),
    verifyIntegrity: verifyHashes,
  });
  return { files: result.manifest.files, providers: result.providers, endpoints: result.endpoints };
}

async function offlinePiCatalogException(repositoryRoot, path, manifestPromise) {
  const file = displayPath(repositoryRoot, path);
  if (!file.startsWith(offlinePiCatalogPrefix) || file === offlinePiCatalogManifest) {
    return { allowed: false };
  }
  try {
    const manifest = await manifestPromise;
    const name = basename(file);
    const expected = manifest.files[name];
    if (!expected || file !== `${offlinePiCatalogPrefix}${name}`) {
      return { allowed: false, error: 'Offline Pi model catalog file is not listed by its manifest' };
    }
    const actual = createHash('sha256')
      .update(await readFile(path))
      .digest('hex');
    if (actual !== expected) {
      return { allowed: false, error: 'Offline Pi model catalog manifest SHA-256 mismatch' };
    }
    return { allowed: true };
  } catch (error) {
    return {
      allowed: false,
      error: error instanceof Error ? error.message : 'Offline Pi model catalog manifest could not be read',
    };
  }
}

function escapeRegularExpression(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
}

function directProviderEndpointMatches(text, groups) {
  const matches = [];
  for (const [anchor, group] of groups) {
    let index = text.indexOf(anchor);
    while (index >= 0) {
      for (const { endpoint, order } of group) {
        if (text.startsWith(endpoint, index)) matches.push({ index, value: endpoint, order });
      }
      index = text.indexOf(anchor, index + anchor.length);
    }
  }
  return matches
    .sort((left, right) => left.index - right.index || left.order - right.order)
    .map(({ index, value }) => ({ index, value }));
}

const directProviderMatcherCache = new WeakMap();

function directProviderMatcher(catalog) {
  const cached = directProviderMatcherCache.get(catalog);
  if (cached) return cached;

  const endpointGroups = new Map();
  for (const [order, endpoint] of catalog.endpoints.entries()) {
    if (!endpoint) continue;
    const schemeEnd = endpoint.indexOf('://');
    const anchor = schemeEnd >= 0 ? endpoint.slice(0, schemeEnd + 3) : endpoint;
    const group = endpointGroups.get(anchor) ?? [];
    group.push({ endpoint, order });
    endpointGroups.set(anchor, group);
  }

  const providerPattern = catalog.providers
    .map(escapeRegularExpression)
    .sort((a, b) => b.length - a.length)
    .join('|');
  const environmentNames = new Set(explicitProviderEnvironmentNames);
  for (const provider of catalog.providers) {
    const prefix = provider.toUpperCase().replace(/[^A-Z0-9]+/gu, '_');
    environmentNames.add(`${prefix}_API_KEY`);
    environmentNames.add(`${prefix}_BASE_URL`);
    environmentNames.add(`${prefix}_MODEL`);
  }
  const environmentPattern = [...environmentNames]
    .map(escapeRegularExpression)
    .sort((a, b) => b.length - a.length)
    .join('|');
  const expressions = [
    [
      'direct-provider-runtime-environment',
      new RegExp(
        `(?:process\\.env(?:\\.|\\[['"])(?:${environmentPattern})|(?:environment|env)\\[['"](?:${environmentPattern}))`,
        'giu',
      ),
    ],
    ['direct-provider-environment', new RegExp(`\\b(?:${environmentPattern})\\b`, 'giu')],
    [
      'direct-provider-registration',
      new RegExp(`registerProvider\\(\\s*['"](?:${providerPattern})['"]`, 'giu'),
    ],
    [
      'direct-provider-configuration',
      new RegExp(`(?:['"]?provider['"]?)\\s*[:=]\\s*['"](?:${providerPattern})['"]`, 'giu'),
    ],
    [
      'direct-provider-sdk',
      new RegExp(
        `(?:from\\s*|import\\s*\\(|require\\s*\\()\\s*['"](?:${directProviderSdkPackages.map(escapeRegularExpression).join('|')})(?:\\/[^'"]*)?['"]`,
        'giu',
      ),
    ],
  ];
  const matcher = Object.freeze({
    endpointGroups,
    expressions,
    endpoints: catalog.endpoints,
    signalTokensLower: Object.freeze(
      [
        ...new Set([
          ...catalog.providers,
          ...catalog.endpoints,
          ...directProviderSdkPackages,
          ...environmentNames,
        ]),
      ]
        .filter(Boolean)
        .map((token) => token.toLowerCase()),
    ),
  });
  directProviderMatcherCache.set(catalog, matcher);
  return matcher;
}

function directProviderMatchesInText(text, catalog, matcher = directProviderMatcher(catalog)) {
  const findings = [];
  let lineForOffset;
  const lineAt = (offset) => (lineForOffset ??= createLineResolver(text))(offset);
  const add = (detector, match) => {
    if (match) {
      findings.push({
        detector,
        index: match.index,
        line: lineAt(match.index),
        value: match.value,
        fingerprint: fingerprint(match.value),
      });
    }
  };

  const addAll = (detector, matches) => {
    for (const match of matches) add(detector, match);
  };

  addAll('direct-provider-endpoint', directProviderEndpointMatches(text, matcher.endpointGroups));

  const callExpression = /(?:fetch|request|axios\.[a-z]+)\s*\(\s*['"`]([^'"`]+)/giu;
  const calls = [];
  for (const match of text.matchAll(callExpression)) {
    if (matcher.endpoints.some((endpoint) => match[1]?.startsWith(endpoint))) {
      calls.push({ index: match.index, value: match[0] });
    }
  }
  addAll('direct-provider-call', calls);
  for (const [detector, expression] of matcher.expressions) {
    expression.lastIndex = 0;
    addAll(
      detector,
      [...text.matchAll(expression)].map((match) => ({ index: match.index, value: match[0] })),
    );
  }
  return [
    ...new Map(
      findings.map((finding) => [`${finding.detector}\0${finding.index}\0${finding.value}`, finding]),
    ).values(),
  ];
}

function directProviderMatches(value, catalog, options = {}) {
  const matcher = directProviderMatcher(catalog);
  const findings = [];
  const scanInput = (text, index) => {
    const lowerText = index > 0 ? text.toLowerCase() : '';
    if (index > 0 && !matcher.signalTokensLower.some((token) => lowerText.includes(token))) return;
    findings.push(...directProviderMatchesInText(text, catalog, matcher));
  };
  if (Buffer.isBuffer(value)) {
    scanInput(value.toString('utf8'), 0);
    if (!options.utf8Only) forEachUtf16AsciiString(value, (text) => scanInput(text, 1));
  } else {
    scanInput(value, 0);
    if (!options.utf8Only)
      forEachUtf16AsciiString(Buffer.from(value, 'latin1'), (text) => scanInput(text, 1));
  }
  return [
    ...new Map(
      findings.map((finding) => [`${finding.detector}\0${finding.index}\0${finding.value}`, finding]),
    ).values(),
  ];
}

function directProviderFindings(value, catalog) {
  return directProviderMatches(value, catalog).map(({ detector, line, fingerprint: valueFingerprint }) => ({
    detector,
    line,
    fingerprint: valueFingerprint,
  }));
}

async function loadPiBuildSourceLock(repositoryRoot, cacheRoot, reader) {
  const source =
    reader?.trustedPiSource ??
    (await readFile(resolve(repositoryRoot, 'pi-source.lock.json'), 'utf8').then(JSON.parse));
  const lockContent = reader
    ? Buffer.from(reader.sourceLockContent, 'utf8')
    : await readFile(resolve(cacheRoot, 'source-lock.json'));
  const lock = JSON.parse(lockContent.toString('utf8'));
  if (
    !lock ||
    typeof lock !== 'object' ||
    lock.schemaVersion !== 1 ||
    !lock.source ||
    typeof lock.source !== 'object' ||
    !lock.artifacts ||
    typeof lock.artifacts !== 'object' ||
    Array.isArray(lock.artifacts)
  ) {
    throw new Error('Pi build source-lock is invalid');
  }
  if (Object.keys(lock.source).sort().join('\0') !== Object.keys(source).sort().join('\0')) {
    throw new Error('Pi build source-lock source identity fields do not match pi-source.lock.json');
  }
  for (const [name, value] of Object.entries(source)) {
    if (lock.source[name] !== value)
      throw new Error('Pi build source-lock does not match pi-source.lock.json');
  }
  for (const [path, expected] of Object.entries(lock.artifacts)) {
    if (
      !/^(?:node_modules|packages)\//u.test(path) ||
      path.includes('..') ||
      path.includes('\\') ||
      !/^[a-f0-9]{64}$/u.test(String(expected))
    ) {
      throw new Error('Pi build source-lock artifact entry is invalid');
    }
    let content;
    try {
      content = reader
        ? await readPiBuildCacheArtifact(reader, path)
        : await readFile(resolve(cacheRoot, path));
    } catch (error) {
      if (error && typeof error === 'object' && error.code === 'ENOENT') {
        throw new Error(`Pi build source-lock artifact is missing: ${path}`, { cause: error });
      }
      throw error;
    }
    if (createHash('sha256').update(content).digest('hex') !== expected) {
      throw new Error(`Pi build source-lock SHA-256 mismatch: ${path}`);
    }
  }
  const actualArtifacts = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      const artifactPath = relative(cacheRoot, path).replaceAll('\\', '/');
      if (entry.isSymbolicLink()) {
        const error = new Error(`Pi build source-lock contains a symbolic link or junction: ${artifactPath}`);
        error.auditPath = displayPath(repositoryRoot, path);
        throw error;
      }
      if (entry.isDirectory()) await visit(path);
      else if (entry.isFile() && artifactPath !== 'source-lock.json') actualArtifacts.push(artifactPath);
      else if (!entry.isFile()) throw new Error(`Unsupported Pi build cache entry: ${artifactPath}`);
    }
  }
  await visit(cacheRoot);
  const expectedArtifacts = Object.keys(lock.artifacts).sort();
  actualArtifacts.sort();
  const unexpected = actualArtifacts.find((path) => !Object.hasOwn(lock.artifacts, path));
  if (unexpected) {
    const error = new Error(`Pi build source-lock artifact path is not listed: ${unexpected}`);
    error.auditPath = displayPath(repositoryRoot, resolve(cacheRoot, unexpected));
    throw error;
  }
  const missing = expectedArtifacts.find((path) => !actualArtifacts.includes(path));
  if (missing) throw new Error(`Pi build source-lock artifact is missing: ${missing}`);
  return {
    ...lock,
    sourceLockSha256: createHash('sha256').update(lockContent).digest('hex'),
  };
}

function piBuildCacheLocation(repositoryRoot, path) {
  const file = displayPath(repositoryRoot, path);
  const segments = file.split('/');
  const generationIndex = segments.findIndex(
    (segment, index) =>
      index > 0 && segments[index - 1] === '.cache' && piBuildGenerationPattern.test(segment),
  );
  if (generationIndex < 0 || generationIndex === segments.length - 1) return undefined;
  return {
    cacheRoot: resolve(repositoryRoot, ...segments.slice(0, generationIndex + 1)),
    relativePath: segments.slice(generationIndex + 1).join('/'),
  };
}

async function auditPiBuildCacheIntegrity(content, location, lockPromise) {
  if (!location) return { error: 'Pi build cache location is invalid' };
  const { relativePath } = location;
  try {
    const lock = await lockPromise;
    if (relativePath === 'source-lock.json') {
      const actual = createHash('sha256').update(content).digest('hex');
      return actual === lock.sourceLockSha256
        ? {}
        : { error: 'Pi build source-lock manifest SHA-256 mismatch' };
    }
    const expected = lock.artifacts[relativePath];
    if (!expected) {
      return { error: 'Pi build source-lock artifact path is not listed' };
    }
    const actual = createHash('sha256').update(content).digest('hex');
    if (actual !== expected) {
      return { error: 'Pi build source-lock SHA-256 mismatch' };
    }
    return {};
  } catch (error) {
    return {
      ...(error && typeof error === 'object' && 'auditPath' in error ? { path: error.auditPath } : {}),
      error: error instanceof Error ? error.message : 'Pi build source-lock could not be read',
    };
  }
}

async function scanV4DirectProviderPaths(options = {}) {
  const repositoryRoot = resolve(options.repositoryRoot ?? defaultRepositoryRoot);
  const artifactRoots = options.artifactRoots ?? artifactRootsForDirectProviderScan();
  const sources = [];
  const errors = [];
  const excludedArtifactFiles = options.excludedArtifactFiles ?? new Set();
  let piCacheRootPath;
  let piCacheScannedPaths = [];
  const pathKey = (path) => (process.platform === 'win32' ? path.toLowerCase() : path);
  const isExcludedArtifact = (path) =>
    excludedArtifactFiles.has(process.platform === 'win32' ? path.toLowerCase() : path);
  const scannedPaths = new Set();
  const recordScannedPath = (path) => {
    const key = path.toLowerCase();
    scannedPaths.add(key);
    options.scannedFilePaths?.add(key);
  };

  if (options.includeTracked !== false) {
    try {
      const tracked = options.trackedFiles ?? (await gitWorktreeFiles(repositoryRoot));
      for (const path of tracked) {
        const normalized = path.replaceAll('\\', '/');
        if (normalized === 'pi' || normalized.startsWith('pi/') || !isProductionSource(normalized)) continue;
        const absolute = resolve(repositoryRoot, path);
        if (isExcludedArtifact(absolute)) continue;
        let entry;
        try {
          entry = await lstat(absolute);
        } catch (error) {
          if (error && typeof error === 'object' && error.code === 'ENOENT') continue;
          throw error;
        }
        if (entry.isFile() && !entry.isSymbolicLink()) {
          sources.push({ category: 'tracked', path: absolute });
        }
      }
    } catch (error) {
      errors.push({
        category: 'tracked',
        path: '.',
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  for (const root of artifactRoots) {
    try {
      let absoluteRoot;
      if (root.piCache) {
        // The content-addressed Pi build cache has its own explicit integrity gate.
        // Resolve and hash the complete published generation once per scan. The
        // snapshot is the integrity authority; scanning every cache artifact a
        // second time only repeats the same I/O and caused Release timeouts.
        const layout = await resolvePiCacheReaderLayout({ repositoryRoot });
        const snapshot = await resolvePublishedPiBuildCache(layout);
        absoluteRoot = snapshot.root;
        piCacheRootPath = absoluteRoot;
        let sourceLock;
        try {
          sourceLock = JSON.parse(snapshot.sourceLockContent);
        } catch (error) {
          throw new Error('The published Pi build source-lock is invalid JSON', { cause: error });
        }
        if (!sourceLock || typeof sourceLock !== 'object' || !sourceLock.artifacts) {
          throw new Error('The published Pi build source-lock artifact map is invalid');
        }
        piCacheScannedPaths = [
          resolve(absoluteRoot, 'source-lock.json'),
          ...Object.keys(sourceLock.artifacts).map((artifactPath) => resolve(absoluteRoot, artifactPath)),
        ];
        sources.push({
          category: root.category,
          path: resolve(repositoryRoot, root.path),
          piCachePointer: true,
        });
        continue;
      }
      absoluteRoot = resolve(repositoryRoot, root.path);
      let entry;
      try {
        entry = await lstat(absoluteRoot);
      } catch (error) {
        if (error && typeof error === 'object' && error.code === 'ENOENT') {
          if (root.required) {
            errors.push({
              category: root.category,
              path: root.path,
              error: 'Required artifact root is missing',
            });
          }
          continue;
        }
        throw error;
      }
      if (root.required && entry.isSymbolicLink()) {
        errors.push({
          category: root.category,
          path: root.path,
          error: 'Required artifact root must not be a symbolic link',
        });
        continue;
      }
      for (const path of await collectArtifactFiles(absoluteRoot, repositoryRoot)) {
        if (!isEphemeralStagingPath(path) && !isExcludedArtifact(path))
          sources.push({ category: root.category, path });
      }
    } catch (error) {
      errors.push({
        category: root.category,
        path: root.path,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  const uniqueSources = new Map();
  for (const source of sources) {
    const pathKey = process.platform === 'win32' ? source.path.toLowerCase() : source.path;
    const key = `${source.category}:${pathKey}`;
    if (!uniqueSources.has(key)) uniqueSources.set(key, source);
  }

  for (const path of piCacheScannedPaths) recordScannedPath(path);
  let manifestPromise;
  const piBuildLockPromises = new Map();
  let catalogErrorReported = false;
  const sourceResults = await mapScansInOrder(
    [...uniqueSources.values()],
    async (source) => {
      const findingsForSource = [];
      const sourceErrors = [];
      const path = displayPath(repositoryRoot, source.path);
      if (source.piCachePointer) {
        recordScannedPath(source.path);
        return { findings: findingsForSource, errors: sourceErrors };
      }
      if (path.startsWith(offlinePiCatalogPrefix) && path !== offlinePiCatalogManifest) {
        manifestPromise ??= loadOfflinePiCatalogManifest(repositoryRoot);
        const exception = await offlinePiCatalogException(repositoryRoot, source.path, manifestPromise);
        if (exception.allowed) {
          recordScannedPath(source.path);
          return { findings: findingsForSource, errors: sourceErrors };
        }
        if (exception.error) {
          sourceErrors.push({ category: source.category, path, error: exception.error });
          catalogErrorReported = true;
        }
      }
      try {
        const location = piBuildCacheLocation(repositoryRoot, source.path);
        const content = await readFile(source.path);
        recordScannedPath(source.path);
        if (location) {
          const cacheKey = pathKey(location.cacheRoot);
          let piBuildLockPromise = cacheKey ? piBuildLockPromises.get(cacheKey) : undefined;
          if (location && cacheKey && !piBuildLockPromise) {
            piBuildLockPromise = loadPiBuildSourceLock(repositoryRoot, location.cacheRoot, undefined);
            piBuildLockPromises.set(cacheKey, piBuildLockPromise);
          }
          const integrity = await auditPiBuildCacheIntegrity(
            content,
            location,
            piBuildLockPromise ?? Promise.reject(new Error('Pi build cache location is invalid')),
          );
          if (integrity.error) {
            sourceErrors.push({
              category: source.category,
              path: integrity.path ?? path,
              error: integrity.error,
            });
          }
        }
        let auditInput = content;
        if (providerAuditMaskApplies(path)) {
          const text = content.toString('utf8');
          const auditText = maskExactHistoricalProviderLines(
            path,
            maskExactDetectorDefinitionRanges(path, text),
          );
          if (auditText !== text) auditInput = auditText;
        }
        manifestPromise ??= loadOfflinePiCatalogManifest(repositoryRoot);
        let catalog;
        try {
          catalog = await manifestPromise;
        } catch (error) {
          if (!catalogErrorReported) {
            sourceErrors.push({
              category: 'provider-catalog',
              path: offlinePiCatalogManifest,
              error: error instanceof Error ? error.message : String(error),
            });
            catalogErrorReported = true;
          }
          try {
            catalog = await loadOfflinePiCatalogManifest(repositoryRoot, false);
          } catch {
            return { findings: findingsForSource, errors: sourceErrors };
          }
        }
        // Electron executables are audited by auditElectronExecutable below,
        // which already scans their native and embedded string surfaces. Avoid
        // repeating the four-way UTF-16 provider walk over a 200MB+ binary;
        // source text, ASAR contents and other artifacts retain the direct
        // provider detector path.
        // const sourceFindings = directProviderFindings(auditInput, catalog);
        const sourceFindings = isPackagedElectronMainExecutable(path)
          ? [{ detector: 'electron-executable-audit', line: 0, fingerprint: 'electron-executable-audit' }]
          : directProviderFindings(auditInput, catalog);
        findingsForSource.push(
          ...sourceFindings.map((finding) => ({ category: source.category, path, ...finding })),
        );
      } catch (error) {
        sourceErrors.push({
          category: source.category,
          path,
          error: error instanceof Error ? error.message : String(error),
        });
      }
      return { findings: findingsForSource, errors: sourceErrors };
    },
    options.concurrency,
  );
  const findings = sourceResults.flatMap((result) => result.findings);
  errors.push(...sourceResults.flatMap((result) => result.errors));

  const uniqueErrors = [
    ...new Map(errors.map((error) => [`${error.category}\0${error.path}\0${error.error}`, error])).values(),
  ];
  return {
    findings,
    errors: uniqueErrors,
    scannedFiles: scannedPaths.size,
    categories: [...new Set([...uniqueSources.values()].map(({ category }) => category))].sort(),
    piCacheRootPath,
  };
}

function artifactRootsForDirectProviderScan() {
  return artifactRoots.filter(({ category }) => directProviderArtifactCategories.has(category));
}

export function v4SecretCanaries(environment) {
  return v4SecretEnvironmentNames.flatMap((name) => {
    const value = environment[name];
    return value && value.length >= 8 ? [{ id: `environment:${name}`, value }] : [];
  });
}

async function collectStructuredAsarArtifacts(repositoryRoot, roots) {
  const archives = new Map();
  for (const root of roots) {
    try {
      for (const path of await collectArtifactFiles(resolve(repositoryRoot, root.path), repositoryRoot)) {
        if (isEphemeralStagingPath(path)) continue;
        if (extname(path).toLowerCase() !== '.asar') continue;
        const key = process.platform === 'win32' ? path.toLowerCase() : path;
        if (!archives.has(key)) archives.set(key, { category: root.category, path });
      }
    } catch {
      // The authoritative root collectors report inaccessible paths. Avoid duplicating their error here.
    }
  }
  return [...archives.values()];
}

function isPackagedElectronMainExecutable(path) {
  if (extname(path).toLowerCase() !== '.exe') return false;
  const executableName = basename(path, extname(path)).toLowerCase();
  const packageDirectory = basename(dirname(path)).toLowerCase();
  return packageDirectory === executableName || packageDirectory.startsWith(`${executableName}-`);
}

function deduplicateAuditItems(items, selector) {
  return [...new Map(items.map((item) => [selector(item), item])).values()];
}

function findingPathKey(path) {
  return process.platform === 'win32' ? path.toLowerCase() : path;
}

async function verifiedGatewayBundleFindingPaths(repositoryRoot, findings) {
  const passiveDetectors = new Set([
    'direct-provider-endpoint',
    'direct-provider-environment',
    'direct-provider-runtime-environment',
  ]);
  const candidates = new Set(
    findings
      .filter(
        ({ detector, path }) =>
          passiveDetectors.has(detector) &&
          !path.includes('!/') &&
          /(?:^|\/)\.cache\/pi-gateway-runtime-[a-f0-9]{64}\/runtime\.mjs$/u.test(path),
      )
      .map(({ path }) => path.replaceAll('\\', '/')),
  );
  const verified = new Set();
  for (const path of candidates) {
    const segments = path.split('/');
    const cacheIndex = segments.lastIndexOf('.cache');
    if (cacheIndex < 0 || segments.slice(0, cacheIndex).some((segment) => segment === '..')) continue;
    const productRoot = resolve(repositoryRoot, ...segments.slice(0, cacheIndex));
    const bundlePath = resolve(repositoryRoot, ...segments);
    try {
      const snapshot = await readPiGatewayRuntimeSnapshot({ repositoryRoot: productRoot });
      if (
        resolve(snapshot.bundleFile.path) === bundlePath &&
        hasGatewayOnlyPiRuntimeBoundary(snapshot.bundleFile.content.toString('utf8'))
      ) {
        verified.add(findingPathKey(path));
      }
    } catch {
      // Invalid or self-inconsistent copies remain ordinary findings.
    }
  }
  return { passiveDetectors, verified };
}

export async function scanV4Secrets(options = {}) {
  const environment = options.env ?? process.env;
  const activeArtifactRoots = options.artifactRoots ?? artifactRoots;
  const repositoryRoot = resolve(options.repositoryRoot ?? defaultRepositoryRoot);
  const structuredArchives = await collectStructuredAsarArtifacts(repositoryRoot, activeArtifactRoots);
  const excludedArtifactFiles = new Set(
    structuredArchives.map(({ path }) => (process.platform === 'win32' ? path.toLowerCase() : path)),
  );
  const scannedFilePaths = new Set();
  const [secrets, directProviders] = await Promise.all([
    scanV3Secrets({
      ...options,
      env: {},
      canaries: [...v4SecretCanaries(environment), ...(options.canaries ?? [])],
      artifactRoots: activeArtifactRoots,
      excludedArtifactFiles,
      scannedFilePaths,
      filterMatches: ({ source, buffer, matches }) =>
        isPackagedElectronMainExecutable(source.path)
          ? []
          : filterExactVendorArtifactSecrets(displayPath(repositoryRoot, source.path), buffer, matches),
    }),
    scanV4DirectProviderPaths({
      repositoryRoot: options.repositoryRoot,
      includeTracked: options.includeTracked,
      trackedFiles: options.trackedFiles,
      artifactRoots: activeArtifactRoots.filter(({ category }) =>
        directProviderArtifactCategories.has(category),
      ),
      excludedArtifactFiles,
      scannedFilePaths,
    }),
  ]);
  const canaries = [...v4SecretCanaries(environment), ...(options.canaries ?? [])];
  const structuredResults = [];
  let catalog;
  try {
    catalog = await loadOfflinePiCatalogManifest(repositoryRoot);
  } catch {
    try {
      catalog = await loadOfflinePiCatalogManifest(repositoryRoot, false);
    } catch {
      catalog = undefined;
    }
  }
  for (const archive of structuredArchives) {
    const audit = {
      kind: 'asar',
      ...(await auditAsarArtifact({
        repositoryRoot,
        archivePath: archive.path,
        category: archive.category,
        canaries,
        providerMatches: catalog ? (text) => directProviderMatches(text, catalog) : () => [],
      })),
    };
    if (!catalog) {
      audit.errors.push({
        category: archive.category,
        path: audit.rawPath,
        error: 'Provider catalog is unavailable; structured ASAR direct-provider coverage is incomplete',
      });
    }
    structuredResults.push(audit);
  }
  if (catalog) {
    const executableFindings = deduplicateAuditItems(
      directProviders.findings.filter(({ path }) => isPackagedElectronMainExecutable(path)),
      ({ category, path }) => `${category}\0${path.toLowerCase()}`,
    );
    for (const executable of executableFindings) {
      structuredResults.push({
        kind: 'electron',
        ...(await auditElectronExecutable({
          repositoryRoot,
          executablePath: resolve(repositoryRoot, executable.path),
          category: executable.category,
          providerMatches: (text) => directProviderMatches(text, catalog, { utf8Only: true }),
          // The executable is already compared against the exact Electron
          // baseline. Scan its native byte representation once; UTF-16
          // variants are covered for source/ASAR artifacts and repeating them
          // over a 200MB+ executable dominates the release gate.
          secretMatches: (buffer) =>
            scanBufferForSecrets(buffer, canaries, { includeOffsets: true, utf8Only: true }),
        })),
      });
    }
  }
  const structuredKey = (item) => `${item.category}\0${item.path.toLowerCase()}`;
  const acceptedAsarRawPaths = new Set(
    structuredResults
      .filter((result) => result.kind === 'asar' && result.complete)
      .map((result) => result.rawPath.toLowerCase()),
  );
  const acceptedElectronRawPaths = new Set(
    structuredResults
      .filter((result) => result.kind === 'electron' && result.complete)
      .map((result) => result.rawPath.toLowerCase()),
  );
  const structuredFindings = structuredResults
    .flatMap((result) => result.findings)
    .filter((finding) => !isEphemeralStagingPath(finding.path));
  const structuredErrors = structuredResults
    .flatMap((result) => result.errors)
    .filter((error) => !isEphemeralStagingPath(error.path));
  const unstructuredFindings = [...secrets.findings, ...directProviders.findings];
  const gatewayBundles = await verifiedGatewayBundleFindingPaths(repositoryRoot, unstructuredFindings);
  let buildOnlyPiPrefix;
  if (directProviders.piCacheRootPath) {
    buildOnlyPiPrefix = `${displayPath(repositoryRoot, directProviders.piCacheRootPath)}/`;
  }
  const isAcceptedBuildInput = ({ path }) =>
    Boolean(buildOnlyPiPrefix && path.replaceAll('\\', '/').startsWith(buildOnlyPiPrefix));
  const isAcceptedPassiveGatewayString = ({ path, detector }) =>
    gatewayBundles.passiveDetectors.has(detector) &&
    gatewayBundles.verified.has(findingPathKey(path.replaceAll('\\', '/')));
  const findings = deduplicateAuditItems(
    [
      ...secrets.findings.filter(
        (finding) =>
          !isEphemeralStagingPath(finding.path) &&
          !acceptedAsarRawPaths.has(finding.path.toLowerCase()) &&
          !acceptedElectronRawPaths.has(finding.path.toLowerCase()) &&
          !isAcceptedBuildInput(finding),
      ),
      ...directProviders.findings.filter(
        (finding) =>
          !isEphemeralStagingPath(finding.path) &&
          finding.detector !== 'electron-executable-audit' &&
          !acceptedAsarRawPaths.has(finding.path.toLowerCase()) &&
          !acceptedElectronRawPaths.has(finding.path.toLowerCase()) &&
          !isAcceptedBuildInput(finding) &&
          !isAcceptedPassiveGatewayString(finding),
      ),
      ...structuredFindings,
    ],
    (finding) => `${structuredKey(finding)}\0${finding.line}\0${finding.detector}\0${finding.fingerprint}`,
  );
  const errors = deduplicateAuditItems(
    [...secrets.errors, ...directProviders.errors, ...structuredErrors],
    (error) => `${structuredKey(error)}\0${error.error}`,
  );
  const structuredFileCount = structuredResults
    .filter((result) => result.kind === 'asar' && result.complete)
    .reduce((total, result) => total + (result.scannedFiles ?? 0), 0);
  return {
    findings,
    errors,
    scannedFiles: scannedFilePaths.size + structuredFileCount,
    categories: [...new Set([...secrets.categories, ...directProviders.categories])].sort(),
  };
}

function parseArtifactRoot(argument, value, required) {
  const separator = value.indexOf('=');
  if (separator <= 0 || separator === value.length - 1) {
    throw new Error(`${argument} must use category=path`);
  }
  return {
    category: value.slice(0, separator),
    path: value.slice(separator + 1),
    ...(required ? { required: true } : {}),
  };
}

function parseArguments(argv) {
  const options = { canaries: [], artifactRoots: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--no-tracked') {
      options.includeTracked = false;
      continue;
    }
    if (
      argument === '--canary' ||
      argument === '--canary-env' ||
      argument === '--root' ||
      argument === '--required-root'
    ) {
      const value = argv[index + 1];
      if (!value) throw new Error(`${argument} requires a value`);
      index += 1;
      if (argument === '--canary') options.canaries.push({ id: `cli-${options.canaries.length + 1}`, value });
      if (argument === '--canary-env') {
        const canary = process.env[value];
        if (!canary) throw new Error(`Canary environment variable is missing: ${value}`);
        options.canaries.push({ id: `environment:${value}`, value: canary });
      }
      if (argument === '--root') options.artifactRoots.push(parseArtifactRoot(argument, value, false));
      if (argument === '--required-root') {
        options.artifactRoots.push(parseArtifactRoot(argument, value, true));
      }
      continue;
    }
    throw new Error(`Unknown argument: ${argument}`);
  }
  if (options.artifactRoots.length === 0) delete options.artifactRoots;
  return options;
}

async function main() {
  const result = await scanV4Secrets(parseArguments(process.argv.slice(2)));
  console.log(
    `[v4-secret-scan] scanned ${result.scannedFiles} files; categories=${result.categories.join(',') || 'none'}`,
  );
  for (const finding of result.findings) {
    console.error(
      `[v4-secret-scan] ${finding.path}:${finding.line} [${finding.category}/${finding.detector}] fingerprint=${finding.fingerprint}`,
    );
  }
  for (const error of result.errors) {
    console.error(`[v4-secret-scan] ERROR ${error.path} [${error.category}]: ${error.error}`);
  }
  if (result.errors.length > 0) process.exitCode = 2;
  else if (result.findings.length > 0) process.exitCode = 1;
  else
    console.log(
      '[v4-secret-scan] PASS: no configured canary, known secret shape, or direct-provider exit was found.',
    );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
