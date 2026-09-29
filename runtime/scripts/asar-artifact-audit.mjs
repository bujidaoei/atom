import { Buffer } from 'node:buffer';
import { createHash } from 'node:crypto';
import { lstat, open, readdir } from 'node:fs/promises';
import { builtinModules } from 'node:module';
import { basename, extname, relative, resolve } from 'node:path';
import { posix } from 'node:path';
import { TextDecoder } from 'node:util';

import { SourceMapConsumer } from 'source-map-js';

import {
  gatewayRuntimeRequiredExports,
  hasGatewayOnlyPiRuntimeBoundary,
  readPiGatewayRuntimeSnapshot,
} from './pi-gateway-runtime.mjs';
import { scanBufferForSecrets } from './scan-v3-secrets.mjs';

const defaultLimits = Object.freeze({
  archiveBytes: 1024 * 1024 * 1024,
  entryBytes: 512 * 1024 * 1024,
  headerBytes: 32 * 1024 * 1024,
  opaqueFallbackBytes: 64 * 1024 * 1024,
  entries: 100_000,
  depth: 64,
});
const piBuildGenerationPathPattern = /^\.cache\/pi-build-generation-[a-f0-9]{64}\//u;
const piBuildPointerPath = '.cache/pi-build-current.json';
const piGatewayGenerationPathPattern = /^\.cache\/(pi-gateway-runtime-[a-f0-9]{64})\/.+/u;
const piGatewayPointerPath = '.cache/pi-gateway-runtime-current.json';
const passiveGatewayBundleDetectors = new Set([
  'direct-provider-endpoint',
  'direct-provider-environment',
  'direct-provider-runtime-environment',
]);
const runtimeSourcePath = 'packages/agent-runtime/src/product-agent-runtime.ts';
const configurationSourcePath = 'packages/product-contracts/src/server-configuration.ts';
const historicalSqliteSourcePath = 'packages/data-access/src/v3/sqlite-execution-repository.ts';
const historicalSqliteLine = [
  '        provider TEXT NOT NULL CHECK (',
  'provider',
  ' = ',
  "'deepseek'",
  '),',
].join('');
const historicalProviderValue = ['provider', ' = ', "'deepseek'"].join('');
const historicalProviderValues = new Set([historicalProviderValue, ['"', historicalProviderValue].join('')]);
const sourceRoots = ['apps/', 'packages/', 'services/', 'scripts/'];
const vendorSecretSourceRules = new Map([
  [
    'node_modules/jose/dist/webapi/key/import.js',
    {
      sha256: '25584bb5c583442b5f5bb7f8fc17bdd0731b9ceaa2b457230a6f79e4a7f46b8a',
      findings: new Set([['20', 'private-key', '3021d90eb943'].join('\0')]),
    },
  ],
  [
    '../../../../node_modules/office-oxide-wasm/bundler/office_oxide_bg.wasm?vite-wasm-instance',
    {
      sha256: '7115d5e1cb5379d7a1fa7c5ebcdc102a04608b8489b186d482644eeb81f68df3',
      findings: new Set([
        ['3', 'cloud-access-key', '4beec471640d'].join('\0'),
        ['3', 'cloud-access-key', 'aa2db9ea6f35'].join('\0'),
      ]),
    },
  ],
  [
    'node_modules/ssh2/lib/protocol/constants.js',
    {
      sha256: 'a3894fdd8e294109b55f06fbda69e467741f15a250801b744b6b0487bbf32529',
      findings: new Set([['16', 'private-key', '3021d90eb943'].join('\0')]),
    },
  ],
  [
    'node_modules/ssh2/lib/protocol/keyParser.js',
    {
      sha256: 'ba4f40a5a9edef15ff49a38226e2be2e66f75aa2673840dd18b807bb7943eca9',
      findings: new Set([['467', 'private-key', '03d104c669e3'].join('\0')]),
    },
  ],
  [
    'node_modules/ssh2/lib/keygen.js',
    {
      sha256: '03d0be43e78ca4f82d4c96d084a39c0242f9c56f343da17a819f8bd0d873f06c',
      findings: new Set([['435', 'private-key', '03d104c669e3'].join('\0')]),
    },
  ],
]);
const vendorSecretEntryRules = new Map([
  [
    'node_modules/tesseract.js-core/tesseract-core-simd-lstm.wasm.js',
    {
      sha256: 'c58b46a4c796c0b8afccf77591d5b875b6896b45d402bbce8caa6f5362447b38',
      findings: new Set([['116', 'cloud-access-key', '4d1fe63fb844'].join('\0')]),
    },
  ],
  [
    'node_modules/tesseract.js-core/tesseract-core-simd.wasm.js',
    {
      sha256: '6b61ef4e911b5cf57e656bbfe983d6e2b3711a02dd164154ddda064566e8e09d',
      findings: new Set([['116', 'cloud-access-key', 'e3486fcf59d5'].join('\0')]),
    },
  ],
  [
    'node_modules/tesseract.js-core/tesseract-core.wasm.js',
    {
      sha256: '0bc6ce3e5fbbd0cd89706cf2fd70960e3372f4f01ee24265b26990808aaeb286',
      findings: new Set([['116', 'cloud-access-key', 'e3486fcf59d5'].join('\0')]),
    },
  ],
]);
const utf8ArtifactExtensions = new Set([
  '.cjs',
  '.css',
  '.html',
  '.js',
  '.json',
  '.jsx',
  '.map',
  '.md',
  '.mjs',
  '.mts',
  '.sql',
  '.svg',
  '.ts',
  '.tsx',
  '.txt',
  '.yaml',
  '.yml',
]);

function sha256(content) {
  return createHash('sha256').update(content).digest('hex');
}

function secretFindingKey(finding) {
  return `${finding.line}\0${finding.detector}\0${finding.fingerprint}`;
}

function vendorSecretRule(source, normalized, content) {
  const rule = vendorSecretSourceRules.get(normalized ?? source);
  return rule && sha256(content) === rule.sha256 ? rule : undefined;
}

function filterAllowedVendorSecrets(matches, rule) {
  if (!rule) return matches;
  return matches.filter((match) => !rule.findings.has(secretFindingKey(match)));
}

function vendorRuleAllowsFingerprint(rule, match) {
  if (!rule) return false;
  return [...rule.findings].some((key) => {
    const [, detector, fingerprint] = key.split('\0');
    return detector === match.detector && fingerprint === match.fingerprint;
  });
}

function mappedVendorSecretAllowed(mapAudit, text, match) {
  if (!mapAudit || !Number.isSafeInteger(match.offset)) return false;
  const original = mapAudit.consumer.originalPositionFor(textPosition(text, match.offset));
  if (!original.source) return false;
  const normalized = normalizeSourcePath(original.source, mapAudit.mapEntryPath);
  const disposition =
    mapAudit.dispositions.get(original.source) ??
    [...mapAudit.dispositions.values()].find(
      (candidate) => normalized && candidate.normalized === normalized,
    );
  return Boolean(disposition?.verified && vendorRuleAllowsFingerprint(disposition.vendorSecrets, match));
}

function filterEntryVendorSecrets(entry, matches) {
  const rule = vendorSecretEntryRules.get(entry.path);
  if (!rule || entry.actualHash !== rule.sha256) return matches;
  return matches.filter((match) => !rule.findings.has(secretFindingKey(match)));
}

export function filterExactVendorArtifactSecrets(path, content, matches) {
  const normalized = path.replaceAll('\\', '/');
  const nodeModulesIndex = normalized.lastIndexOf('node_modules/');
  const artifactPath = nodeModulesIndex >= 0 ? normalized.slice(nodeModulesIndex) : normalized;
  const rule = vendorSecretSourceRules.get(artifactPath) ?? vendorSecretEntryRules.get(artifactPath);
  if (!rule || sha256(content) !== rule.sha256) return matches;
  return filterAllowedVendorSecrets(matches, rule);
}

function displayPath(repositoryRoot, path) {
  const candidate = relative(repositoryRoot, path).replaceAll('\\', '/');
  return candidate && !candidate.startsWith('../') ? candidate : basename(path);
}

function archiveEntryPath(archiveDisplayPath, entryPath) {
  return `${archiveDisplayPath}!/${entryPath}`;
}

function plainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value, allowed) {
  return Object.keys(value).every((key) => allowed.has(key));
}

function isNodeBuiltin(path) {
  return path.startsWith('node:') || builtinModules.includes(path);
}

function sameFileIdentity(left, right) {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.size === right.size &&
    left.nlink === right.nlink &&
    left.mtimeMs === right.mtimeMs &&
    left.birthtimeMs === right.birthtimeMs
  );
}

async function readStableRegularFile(path) {
  const before = await lstat(path);
  if (!before.isFile() || before.isSymbolicLink()) throw new Error('file is not a regular non-link file');
  if (before.nlink !== 1) throw new Error('file has an external hard-link topology');
  const handle = await open(path, 'r');
  try {
    const opened = await handle.stat();
    if (opened.nlink !== 1 || !sameFileIdentity(before, opened)) {
      throw new Error('file changed while it was being opened or has an external hard link');
    }
    const content = await handle.readFile();
    const after = await handle.stat();
    if (after.nlink !== 1 || !sameFileIdentity(opened, after)) {
      throw new Error('file changed while it was being read or has an external hard link');
    }
    return content;
  } finally {
    await handle.close();
  }
}

async function readAsarHeader(handle, archiveSize, limits) {
  const prefix = Buffer.alloc(8);
  const prefixRead = await handle.read(prefix, 0, prefix.length, 0);
  if (prefixRead.bytesRead !== prefix.length || prefix.readUInt32LE(0) !== 4) {
    throw new Error('ASAR archive header prefix is malformed');
  }
  const headerSize = prefix.readUInt32LE(4);
  if (headerSize < 8 || headerSize > limits.headerBytes) {
    throw new Error('ASAR archive header exceeds the configured size bound');
  }
  if (8 + headerSize > archiveSize) throw new Error('ASAR archive header exceeds the archive size');
  const headerBuffer = Buffer.alloc(headerSize);
  const headerRead = await handle.read(headerBuffer, 0, headerSize, 8);
  if (headerRead.bytesRead !== headerSize)
    throw new Error('ASAR archive header could not be read completely');
  const payloadSize = headerBuffer.readUInt32LE(0);
  const stringSize = headerBuffer.readUInt32LE(4);
  if (payloadSize !== headerSize - 4 || stringSize > headerSize - 8) {
    throw new Error('ASAR archive header pickle is malformed');
  }
  const trailing = headerBuffer.subarray(8 + stringSize);
  if (trailing.some((byte) => byte !== 0)) throw new Error('ASAR archive header has non-padding bytes');
  let headerString;
  try {
    headerString = new TextDecoder('utf-8', { fatal: true }).decode(headerBuffer.subarray(8, 8 + stringSize));
  } catch (error) {
    throw new Error('ASAR archive header is not valid UTF-8', { cause: error });
  }
  try {
    return { headerString, header: JSON.parse(headerString), headerSize };
  } catch (error) {
    throw new Error('ASAR archive header JSON is malformed', { cause: error });
  }
}

function validateIntegrityShape(integrity) {
  return (
    plainObject(integrity) &&
    exactKeys(integrity, new Set(['algorithm', 'hash', 'blockSize', 'blocks'])) &&
    integrity.algorithm === 'SHA256' &&
    /^[a-f0-9]{64}$/u.test(String(integrity.hash)) &&
    Number.isSafeInteger(integrity.blockSize) &&
    integrity.blockSize > 0 &&
    integrity.blockSize <= 16 * 1024 * 1024 &&
    Array.isArray(integrity.blocks) &&
    integrity.blocks.every((hash) => /^[a-f0-9]{64}$/u.test(String(hash)))
  );
}

function parseAsarHeader(rawHeader, archiveSize, limits) {
  if (!plainObject(rawHeader) || !plainObject(rawHeader.header)) {
    throw new Error('ASAR archive header is malformed');
  }
  if (!Number.isSafeInteger(rawHeader.headerSize) || rawHeader.headerSize > limits.headerBytes) {
    throw new Error('ASAR archive header exceeds the configured size bound');
  }
  if (!exactKeys(rawHeader.header, new Set(['files'])) || !plainObject(rawHeader.header.files)) {
    throw new Error('ASAR archive root header is malformed');
  }
  const dataStart = 8 + rawHeader.headerSize;
  if (dataStart > archiveSize) throw new Error('ASAR archive header exceeds the archive size');

  const entries = [];
  let totalDeclaredBytes = 0;
  function visit(files, parentSegments) {
    if (parentSegments.length >= limits.depth) {
      throw new Error(`ASAR archive entry depth exceeds ${limits.depth}`);
    }
    for (const [name, node] of Object.entries(files)) {
      if (
        !name ||
        name === '.' ||
        name === '..' ||
        name.includes('/') ||
        name.includes('\\') ||
        [...name].some((character) => character.codePointAt(0) <= 0x1f)
      ) {
        throw new Error(`ASAR archive contains a traversal or invalid path segment: ${name}`);
      }
      if (!plainObject(node)) throw new Error('ASAR archive entry metadata is malformed');
      const segments = [...parentSegments, name];
      const entryPath = segments.join('/');
      if (entries.length >= limits.entries) {
        throw new Error(`ASAR archive contains more than ${limits.entries} entries`);
      }
      if (Object.hasOwn(node, 'link')) {
        throw new Error(`ASAR archive link entries are forbidden: ${entryPath}`);
      }
      if (Object.hasOwn(node, 'files')) {
        if (
          !exactKeys(node, new Set(['files', 'unpacked'])) ||
          !plainObject(node.files) ||
          (Object.hasOwn(node, 'unpacked') && typeof node.unpacked !== 'boolean')
        ) {
          throw new Error(`ASAR archive directory metadata is malformed: ${entryPath}`);
        }
        visit(node.files, segments);
        continue;
      }
      if (
        !exactKeys(node, new Set(['size', 'offset', 'integrity', 'unpacked', 'executable'])) ||
        !Number.isSafeInteger(node.size) ||
        node.size < 0 ||
        node.size > limits.entryBytes ||
        !validateIntegrityShape(node.integrity) ||
        (Object.hasOwn(node, 'unpacked') && typeof node.unpacked !== 'boolean') ||
        (Object.hasOwn(node, 'executable') && typeof node.executable !== 'boolean')
      ) {
        throw new Error(`ASAR archive file metadata is malformed: ${entryPath}`);
      }
      const unpacked = node.unpacked === true;
      totalDeclaredBytes += node.size;
      if (!Number.isSafeInteger(totalDeclaredBytes) || totalDeclaredBytes > limits.archiveBytes) {
        throw new Error('ASAR archive total declared entry bytes exceed the configured bound');
      }
      let offset;
      if (!unpacked) {
        if (!/^\d+$/u.test(String(node.offset))) {
          throw new Error(`ASAR archive file offset is malformed: ${entryPath}`);
        }
        offset = BigInt(node.offset);
        if (offset + BigInt(node.size) > BigInt(archiveSize - dataStart)) {
          throw new Error(`ASAR archive file range is out of bounds: ${entryPath}`);
        }
      } else if (Object.hasOwn(node, 'offset')) {
        throw new Error(`ASAR unpacked entry has an unexpected packed offset: ${entryPath}`);
      }
      entries.push({
        path: entryPath,
        size: node.size,
        unpacked,
        offset,
        integrity: node.integrity,
      });
    }
  }
  visit(rawHeader.header.files, []);

  const ranges = entries
    .filter((entry) => !entry.unpacked && entry.size > 0)
    .map((entry) => ({ start: entry.offset, end: entry.offset + BigInt(entry.size), path: entry.path }))
    .sort((left, right) => (left.start < right.start ? -1 : left.start > right.start ? 1 : 0));
  let cursor = 0n;
  for (const range of ranges) {
    if (range.start !== cursor) {
      throw new Error(`ASAR archive has an overlapping or unaccounted data range near: ${range.path}`);
    }
    cursor = range.end;
  }
  if (cursor !== BigInt(archiveSize - dataStart)) {
    throw new Error('ASAR archive contains unaccounted trailing or missing payload bytes');
  }
  return { dataStart, entries };
}

async function collectUnpackedFiles(root, archivePath) {
  const files = [];
  async function visit(path, segments) {
    let entry;
    try {
      entry = await lstat(path);
    } catch (error) {
      if (error && typeof error === 'object' && error.code === 'ENOENT') return;
      throw error;
    }
    if (entry.isSymbolicLink()) {
      throw new Error(`ASAR unpacked tree contains a link: ${segments.join('/') || archivePath}`);
    }
    if (entry.isFile()) {
      if (entry.nlink !== 1) {
        throw new Error(`ASAR unpacked tree contains a hard link: ${segments.join('/')}`);
      }
      files.push(segments.join('/'));
      return;
    }
    if (!entry.isDirectory()) {
      throw new Error(`ASAR unpacked tree contains an unsupported entry: ${segments.join('/')}`);
    }
    for (const name of await readdir(path)) {
      if (!name || name === '.' || name === '..' || name.includes('/') || name.includes('\\')) {
        throw new Error(`ASAR unpacked tree contains an invalid path segment: ${name}`);
      }
      await visit(resolve(path, name), [...segments, name]);
    }
  }
  await visit(root, []);
  return files.sort();
}

function verifyEntryIntegrity(entry, content) {
  const errors = [];
  if (content.length !== entry.size) errors.push('size mismatch');
  if (sha256(content) !== entry.integrity.hash) errors.push('SHA-256 integrity mismatch');
  const blocks = [];
  for (let offset = 0; offset < content.length || offset === 0; offset += entry.integrity.blockSize) {
    blocks.push(
      sha256(content.subarray(offset, Math.min(content.length, offset + entry.integrity.blockSize))),
    );
    if (content.length === 0) break;
  }
  if (
    blocks.length !== entry.integrity.blocks.length ||
    blocks.some((hash, index) => hash !== entry.integrity.blocks[index])
  ) {
    errors.push('block integrity mismatch');
  }
  return errors;
}

function normalizeSourcePath(source, mapEntryPath) {
  const raw = String(source);
  if (
    raw.includes('\0') ||
    raw.startsWith('/') ||
    raw.startsWith('\\') ||
    /^[a-z]:[\\/]/iu.test(raw) ||
    /^[a-z][a-z0-9+.-]*:\/\//iu.test(raw)
  ) {
    return undefined;
  }
  const normalized = raw.replaceAll('\\', '/');
  if (normalized.includes('?') || normalized.includes('#')) return undefined;
  if (normalized.startsWith('.')) {
    const repositoryRelative = posix.normalize(
      posix.join('apps/desktop', posix.dirname(mapEntryPath), normalized),
    );
    if (
      repositoryRelative &&
      !repositoryRelative.startsWith('../') &&
      !posix.isAbsolute(repositoryRelative) &&
      safeRelativeSourcePath(repositoryRelative)
    ) {
      return repositoryRelative;
    }
  }
  for (const root of sourceRoots) {
    if (normalized.startsWith(root)) {
      return safeRelativeSourcePath(normalized) ? normalized : undefined;
    }
  }
  return safeRelativeSourcePath(normalized) ? normalized : undefined;
}

function safeRelativeSourcePath(path) {
  return (
    typeof path === 'string' &&
    path.length > 0 &&
    !posix.isAbsolute(path) &&
    posix.normalize(path) === path &&
    !path.includes('\\') &&
    path.split('/').every((segment) => segment && segment !== '.' && segment !== '..')
  );
}

function textPosition(text, index) {
  const prefix = text.slice(0, index);
  const lines = prefix.split('\n');
  return { line: lines.length, column: lines.at(-1)?.length ?? 0 };
}

function maskHistoricalSqliteLine(text) {
  const lines = text.split('\n');
  const matches = lines.flatMap((line, index) =>
    line.replace(/\r$/u, '') === historicalSqliteLine ? [index] : [],
  );
  if (matches.length !== 1) return text;
  lines[matches[0]] = lines[matches[0]].replace(/[^\r]/gu, ' ');
  return lines.join('\n');
}

function validateEmbeddedPiGatewayRuntime(entryByPath, repositorySourceLockContent, externalGateway) {
  const errors = [];
  const paths = [...entryByPath.keys()];
  const forbiddenBuildPaths = paths.filter(
    (path) => path === piBuildPointerPath || piBuildGenerationPathPattern.test(path),
  );
  if (forbiddenBuildPaths.length > 0) {
    errors.push('Packaged application contains the build-only full Pi cache');
  }
  const generationPaths = paths.filter((path) => piGatewayGenerationPathPattern.test(path));
  const pointerEntry = entryByPath.get(piGatewayPointerPath);
  if (generationPaths.length === 0 && !pointerEntry) {
    return {
      present: forbiddenBuildPaths.length > 0,
      valid: false,
      prefix: undefined,
      bundlePath: undefined,
      errors,
    };
  }

  let pointer;
  try {
    pointer = JSON.parse(pointerEntry?.content.toString('utf8') ?? '');
  } catch {
    pointer = undefined;
  }
  const pointerKeys = new Set([
    'schemaVersion',
    'generation',
    'manifestSha256',
    'bundleSha256',
    'sourceLockSha256',
    'piSourceManifestSha256',
  ]);
  if (
    !plainObject(pointer) ||
    !exactKeys(pointer, pointerKeys) ||
    Object.keys(pointer).length !== pointerKeys.size ||
    pointer.schemaVersion !== 1 ||
    typeof pointer.generation !== 'string' ||
    !/^pi-gateway-runtime-[a-f0-9]{64}$/u.test(pointer.generation) ||
    pointer.manifestSha256 !== pointer.generation.slice('pi-gateway-runtime-'.length) ||
    !/^[a-f0-9]{64}$/u.test(String(pointer.bundleSha256)) ||
    !/^[a-f0-9]{64}$/u.test(String(pointer.sourceLockSha256)) ||
    !/^[a-f0-9]{64}$/u.test(String(pointer.piSourceManifestSha256))
  ) {
    errors.push('Embedded Pi gateway runtime pointer is missing, malformed, or source-unbound');
    return {
      present: true,
      valid: false,
      prefix: undefined,
      bundlePath: undefined,
      errors,
    };
  }

  const prefix = `.cache/${pointer.generation}/`;
  const manifestPath = `${prefix}manifest.json`;
  const bundlePath = `${prefix}runtime.mjs`;
  const expectedPaths = [manifestPath, bundlePath].sort();
  if (
    generationPaths.length !== expectedPaths.length ||
    generationPaths.sort().some((path, index) => path !== expectedPaths[index])
  ) {
    errors.push('Embedded Pi gateway runtime must contain exactly one manifest and one bundle');
  }
  const manifestEntry = entryByPath.get(manifestPath);
  const bundleEntry = entryByPath.get(bundlePath);
  const embeddedSourceLock = entryByPath.get('pi-source.lock.json');
  if (!manifestEntry || !bundleEntry || !embeddedSourceLock) {
    errors.push('Embedded Pi gateway runtime manifest, bundle, or Pi source lock is missing');
  }
  if (
    [pointerEntry, manifestEntry, bundleEntry, embeddedSourceLock].some((entry) => entry?.unpacked !== true)
  ) {
    errors.push(
      'Embedded Pi gateway runtime pointer, manifest, bundle, and source lock must be physical unpacked files',
    );
  }
  if (
    !externalGateway ||
    !pointerEntry?.content.equals(externalGateway.pointerContent) ||
    !manifestEntry?.content.equals(externalGateway.manifestContent) ||
    !bundleEntry?.content.equals(externalGateway.bundleContent)
  ) {
    errors.push('Embedded Pi gateway runtime is not byte-identical to the pinned local generation');
  }
  if (
    !repositorySourceLockContent ||
    !embeddedSourceLock?.content.equals(repositorySourceLockContent) ||
    pointer.piSourceManifestSha256 !== externalGateway?.reader.manifest.source.piSourceManifestSha256
  ) {
    errors.push('Embedded Pi gateway runtime does not match the trusted Pi source lock');
  }
  if (
    manifestEntry?.actualHash !== pointer.manifestSha256 ||
    bundleEntry?.actualHash !== pointer.bundleSha256
  ) {
    errors.push('Embedded Pi gateway runtime hash does not match its pointer');
  }
  let manifest;
  try {
    manifest = JSON.parse(manifestEntry?.content.toString('utf8') ?? '');
  } catch {
    manifest = undefined;
  }
  const manifestKeys = new Set([
    'schemaVersion',
    'source',
    'policy',
    'bundle',
    'virtualModules',
    'inputs',
    'externalImports',
    'exports',
  ]);
  if (
    !plainObject(manifest) ||
    !exactKeys(manifest, manifestKeys) ||
    Object.keys(manifest).length !== manifestKeys.size ||
    manifest.schemaVersion !== 1 ||
    manifest.source?.piSourceManifestSha256 !== pointer.piSourceManifestSha256 ||
    manifest.source?.sourceLockSha256 !== pointer.sourceLockSha256 ||
    manifest.policy?.provider !== 'enterprise-gateway' ||
    manifest.policy?.api !== 'openai-completions' ||
    manifest.policy?.builtinProviders !== false ||
    manifest.policy?.allowedRequestPath !== 'chat/completions' ||
    manifest.bundle?.path !== 'runtime.mjs' ||
    manifest.bundle?.sha256 !== pointer.bundleSha256 ||
    manifest.bundle?.bytes !== bundleEntry?.content.length ||
    !Array.isArray(manifest.externalImports) ||
    manifest.externalImports.some((path) => typeof path !== 'string' || !isNodeBuiltin(path)) ||
    JSON.stringify(manifest.exports) !== JSON.stringify(gatewayRuntimeRequiredExports) ||
    !hasGatewayOnlyPiRuntimeBoundary(bundleEntry?.content.toString('utf8') ?? '')
  ) {
    errors.push('Embedded Pi gateway runtime policy or executable boundary is invalid');
  }
  return {
    present: true,
    valid: errors.length === 0,
    prefix,
    bundlePath,
    errors,
  };
}

async function exactRepositorySource(repositoryRoot, path, content) {
  if (!safeRelativeSourcePath(path) || !sourceRoots.some((root) => path.startsWith(root))) return false;
  try {
    return (await readStableRegularFile(resolve(repositoryRoot, path))).toString('utf8') === content;
  } catch {
    return false;
  }
}

function runtimeProof(runtimeSource, configurationSource) {
  if (!runtimeSource || !configurationSource) return false;
  const createIsNetworkClosed =
    /ModelRuntime\.create\(\s*\{\s*modelsPath:\s*null,\s*refreshOnCreate:\s*false,\s*allowModelNetwork:\s*false,\s*\}\s*\)/u.test(
      runtimeSource,
    );
  const registrations = [...runtimeSource.matchAll(/\bmodelRuntime\.registerProvider\(\s*([^,\s)]+)/gu)].map(
    (match) => match[1],
  );
  const gatewayIdentity =
    /export\s+const\s+ENTERPRISE_AI_GATEWAY_PROVIDER\s*=\s*['"]enterprise-gateway['"]/u.test(
      configurationSource,
    );
  return (
    createIsNetworkClosed &&
    gatewayIdentity &&
    registrations.length === 1 &&
    registrations[0] === 'ENTERPRISE_AI_GATEWAY_PROVIDER'
  );
}

function generatedRuntimeProof(generatedSource) {
  const createIsNetworkClosed =
    /(?:await\s+)?ModelRuntime\.create\(\s*\{\s*modelsPath:\s*null,\s*refreshOnCreate:\s*false,\s*allowModelNetwork:\s*false\s*\}\s*\)/u.test(
      generatedSource,
    );
  const registrations = [
    ...generatedSource.matchAll(/\bmodelRuntime\.registerProvider\(\s*([^,\s)]+)/gu),
  ].map((match) => match[1]);
  const gatewayIdentity = /\bENTERPRISE_AI_GATEWAY_PROVIDER\s*=\s*['"]enterprise-gateway['"]/u.test(
    generatedSource,
  );
  return (
    createIsNetworkClosed &&
    gatewayIdentity &&
    registrations.length === 1 &&
    registrations[0] === 'ENTERPRISE_AI_GATEWAY_PROVIDER'
  );
}

function appendMatches(findings, category, path, matches) {
  findings.push(
    ...matches.map(({ line, detector, fingerprint }) => ({
      category,
      path,
      line,
      detector,
      fingerprint,
    })),
  );
}

function deduplicateFindings(findings) {
  return [
    ...new Map(
      findings.map((finding) => [
        `${finding.category}\0${finding.path}\0${finding.line}\0${finding.detector}\0${finding.fingerprint}`,
        finding,
      ]),
    ).values(),
  ];
}

export async function auditAsarArtifact(options) {
  const repositoryRoot = resolve(options.repositoryRoot);
  const archivePath = resolve(options.archivePath);
  const archiveDisplayPath = displayPath(repositoryRoot, archivePath);
  const category = options.category;
  const limits = { ...defaultLimits, ...(options.limits ?? {}) };
  const errors = [];
  const findings = [];
  let archive;
  let handle;
  let openedArchive;
  try {
    archive = await lstat(archivePath);
    if (!archive.isFile() || archive.isSymbolicLink() || archive.nlink !== 1) {
      throw new Error('ASAR artifact must be a regular file with no symbolic or external hard links');
    }
    if (archive.size > limits.archiveBytes) throw new Error('ASAR archive exceeds the configured size bound');
    handle = await open(archivePath, 'r');
    openedArchive = await handle.stat();
    if (openedArchive.nlink !== 1 || !sameFileIdentity(archive, openedArchive)) {
      throw new Error('ASAR archive changed while it was being opened');
    }
    let rawHeader;
    try {
      rawHeader = await readAsarHeader(handle, openedArchive.size, limits);
    } catch (error) {
      throw new Error(
        `ASAR archive header could not be read: ${error instanceof Error ? error.message : String(error)}`,
        { cause: error },
      );
    }
    const parsed = parseAsarHeader(rawHeader, openedArchive.size, limits);
    const expectedUnpacked = parsed.entries
      .filter((entry) => entry.unpacked)
      .map((entry) => entry.path)
      .sort();
    const actualUnpacked = await collectUnpackedFiles(`${archivePath}.unpacked`, archiveDisplayPath);
    const extraUnpacked = actualUnpacked.find((path) => !expectedUnpacked.includes(path));
    const missingUnpacked = expectedUnpacked.find((path) => !actualUnpacked.includes(path));
    if (extraUnpacked) errors.push(`ASAR unpacked file is not listed by the header: ${extraUnpacked}`);
    if (missingUnpacked) errors.push(`ASAR unpacked file is missing: ${missingUnpacked}`);

    const entryByPath = new Map();
    for (const entry of parsed.entries) {
      let content;
      try {
        if (entry.unpacked) {
          content = await readStableRegularFile(resolve(`${archivePath}.unpacked`, ...entry.path.split('/')));
        } else {
          content = Buffer.alloc(entry.size);
          const { bytesRead } = await handle.read(
            content,
            0,
            entry.size,
            parsed.dataStart + Number(entry.offset),
          );
          if (bytesRead !== entry.size) throw new Error('short read');
        }
      } catch (error) {
        errors.push(
          `ASAR entry could not be read: ${entry.path}: ${error instanceof Error ? error.message : String(error)}`,
        );
        continue;
      }
      for (const integrityError of verifyEntryIntegrity(entry, content)) {
        errors.push(`ASAR entry ${integrityError}: ${entry.path}`);
      }
      entryByPath.set(entry.path, {
        ...entry,
        content,
        actualHash: sha256(content),
        secretMatches: scanBufferForSecrets(content, options.canaries, {
          includeOffsets: true,
          utf8Only: utf8ArtifactExtensions.has(extname(entry.path).toLowerCase()),
        }),
      });
    }
    const complete = entryByPath.size === parsed.entries.length;
    let repositorySourceLockContent;
    let externalGateway;
    try {
      const snapshot = await readPiGatewayRuntimeSnapshot({ repositoryRoot });
      repositorySourceLockContent = snapshot.trustedFile.content;
      externalGateway = {
        reader: snapshot.reader,
        pointerContent: snapshot.pointerFile.content,
        manifestContent: snapshot.manifestFile.content,
        bundleContent: snapshot.bundleFile.content,
      };
    } catch {
      repositorySourceLockContent = undefined;
      externalGateway = undefined;
    }
    const piGateway = validateEmbeddedPiGatewayRuntime(
      entryByPath,
      repositorySourceLockContent,
      externalGateway,
    );
    errors.push(...piGateway.errors);

    const mapAudits = new Map();
    let packagedRuntimeProof = false;
    for (const entry of entryByPath.values()) {
      if (
        (piGateway.prefix && entry.path.startsWith(piGateway.prefix)) ||
        extname(entry.path).toLowerCase() !== '.map'
      )
        continue;
      const mapPath = archiveEntryPath(archiveDisplayPath, entry.path);
      let rawMap;
      try {
        rawMap = JSON.parse(entry.content.toString('utf8'));
        if (
          !plainObject(rawMap) ||
          !Array.isArray(rawMap.sources) ||
          !Array.isArray(rawMap.sourcesContent) ||
          rawMap.sources.length !== rawMap.sourcesContent.length ||
          rawMap.sources.length > limits.entries ||
          !rawMap.sources.every((source) => typeof source === 'string') ||
          !rawMap.sourcesContent.every((content) => typeof content === 'string')
        ) {
          throw new Error('source map sources and sourcesContent must be complete');
        }
      } catch (error) {
        errors.push(
          `ASAR source map is malformed: ${entry.path}: ${error instanceof Error ? error.message : String(error)}`,
        );
        appendMatches(findings, category, mapPath, scanBufferForSecrets(entry.content, options.canaries));
        appendMatches(findings, category, mapPath, options.providerMatches(entry.content.toString('utf8')));
        continue;
      }
      const dispositions = new Map();
      let runtimeSource;
      let configurationSource;
      for (let index = 0; index < rawMap.sources.length; index += 1) {
        const source = rawMap.sources[index];
        const content = rawMap.sourcesContent[index];
        const normalized = normalizeSourcePath(source, entry.path);
        const sourceFindingPath = `${mapPath}#source=${normalized ?? '[invalid]'}`;
        const vendorSecrets = vendorSecretRule(source, normalized, content);
        if (!normalized) {
          dispositions.set(source, {
            kind: vendorSecrets ? 'vendor' : 'other',
            verified: Boolean(vendorSecrets),
            normalized: source,
            content,
            vendorSecrets,
          });
          appendMatches(
            findings,
            category,
            sourceFindingPath,
            filterAllowedVendorSecrets(
              scanBufferForSecrets(Buffer.from(content), options.canaries),
              vendorSecrets,
            ),
          );
          appendMatches(findings, category, sourceFindingPath, options.providerMatches(content));
          continue;
        }
        const exactRepositoryCopy = sourceRoots.some((root) => normalized.startsWith(root))
          ? await exactRepositorySource(repositoryRoot, normalized, content)
          : false;
        const historical =
          normalized === historicalSqliteSourcePath &&
          exactRepositoryCopy &&
          content.split('\n').filter((line) => line.replace(/\r$/u, '') === historicalSqliteLine).length ===
            1;
        dispositions.set(source, {
          kind: historical ? 'historical' : vendorSecrets ? 'vendor' : 'other',
          verified: historical || exactRepositoryCopy || Boolean(vendorSecrets),
          normalized,
          content,
          vendorSecrets,
        });
        if (normalized === runtimeSourcePath && exactRepositoryCopy) runtimeSource = content;
        if (normalized === configurationSourcePath && exactRepositoryCopy) configurationSource = content;
        appendMatches(
          findings,
          category,
          sourceFindingPath,
          filterAllowedVendorSecrets(
            scanBufferForSecrets(Buffer.from(content), options.canaries),
            vendorSecrets,
          ),
        );
        appendMatches(
          findings,
          category,
          sourceFindingPath,
          options.providerMatches(historical ? maskHistoricalSqliteLine(content) : content),
        );
      }
      const structuralMap = { ...rawMap, sourcesContent: rawMap.sourcesContent.map(() => '') };
      const structuralText = JSON.stringify(structuralMap);
      appendMatches(
        findings,
        category,
        mapPath,
        scanBufferForSecrets(Buffer.from(structuralText), options.canaries),
      );
      appendMatches(findings, category, mapPath, options.providerMatches(structuralText));
      try {
        const consumer = new SourceMapConsumer(rawMap);
        const generatedPath = entry.path.slice(0, -'.map'.length);
        mapAudits.set(generatedPath, { consumer, dispositions, mapEntryPath: entry.path });
        if (entry.path === '.vite/build/local-agent-host.mjs.map') {
          const mappedSources = new Set();
          consumer.eachMapping((mapping) => {
            const normalized = mapping.source ? normalizeSourcePath(mapping.source, entry.path) : undefined;
            if (normalized) mappedSources.add(normalized);
          });
          const generatedEntry = entryByPath.get(generatedPath);
          const generatedSource = generatedEntry?.content.toString('utf8');
          const sourceMapFooter = /\/\/# sourceMappingURL=local-agent-host\.mjs\.map\s*$/u.test(
            generatedSource ?? '',
          );
          packagedRuntimeProof =
            sourceMapFooter &&
            mappedSources.has(runtimeSourcePath) &&
            mappedSources.has(configurationSourcePath) &&
            runtimeProof(runtimeSource, configurationSource) &&
            generatedRuntimeProof(generatedSource);
        }
      } catch (error) {
        errors.push(
          `ASAR source map mappings are malformed: ${entry.path}: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    if (piGateway.present && piGateway.valid && !packagedRuntimeProof) {
      errors.push(
        'Packaged ProductAgentRuntime proof is missing or does not enforce modelsPath null, network-closed runtime, and exactly enterprise-gateway registration',
      );
    }

    for (const entry of entryByPath.values()) {
      const findingPath = archiveEntryPath(archiveDisplayPath, entry.path);
      const isMap = extname(entry.path).toLowerCase() === '.map';
      if (isMap) {
        if (piGateway.prefix && entry.path.startsWith(piGateway.prefix)) {
          appendMatches(findings, category, findingPath, entry.secretMatches);
        }
        continue;
      }
      const text = entry.content.toString('utf8');
      const mapAudit = mapAudits.get(entry.path);
      const secretMatches = filterEntryVendorSecrets(entry, entry.secretMatches).filter(
        (match) => !mappedVendorSecretAllowed(mapAudit, text, match),
      );
      appendMatches(findings, category, findingPath, secretMatches);
      const providerMatches = options
        .providerMatches(text)
        .filter(
          (match) =>
            !(
              piGateway.valid &&
              entry.path === piGateway.bundlePath &&
              passiveGatewayBundleDetectors.has(match.detector)
            ),
        );
      if (providerMatches.length === 0) continue;
      if (!mapAudit) {
        appendMatches(findings, category, findingPath, providerMatches);
        continue;
      }
      let historicalMatchAccepted = false;
      const verifiedHistoricalSource = [...mapAudit.dispositions.values()].some(
        (candidate) => candidate.kind === 'historical' && candidate.verified,
      );
      const generatedHistoricalLineCount = text
        .split('\n')
        .filter((line) => line.replace(/\r$/u, '') === historicalSqliteLine).length;
      for (const match of providerMatches) {
        const generated = textPosition(text, match.index);
        const original = mapAudit.consumer.originalPositionFor(generated);
        const normalizedOriginal = original.source
          ? normalizeSourcePath(original.source, mapAudit.mapEntryPath)
          : undefined;
        const disposition = original.source
          ? (mapAudit.dispositions.get(original.source) ??
            [...mapAudit.dispositions.values()].find(
              ({ normalized }) => normalizedOriginal && normalized === normalizedOriginal,
            ))
          : undefined;
        const exactGeneratedHistoricalFallback =
          !historicalMatchAccepted &&
          packagedRuntimeProof &&
          verifiedHistoricalSource &&
          generatedHistoricalLineCount === 1 &&
          match.detector === 'direct-provider-configuration' &&
          historicalProviderValues.has(match.value) &&
          text.split('\n')[generated.line - 1]?.replace(/\r$/u, '') === historicalSqliteLine;
        const mappedHistoricalLine =
          !historicalMatchAccepted &&
          match.detector === 'direct-provider-configuration' &&
          historicalProviderValues.has(match.value) &&
          disposition?.kind === 'historical' &&
          disposition.verified &&
          original.line !== null &&
          disposition.content.split('\n')[original.line - 1]?.replace(/\r$/u, '') === historicalSqliteLine;
        if (!mappedHistoricalLine && !exactGeneratedHistoricalFallback) {
          appendMatches(findings, category, findingPath, [match]);
        } else {
          historicalMatchAccepted = true;
        }
      }
    }
    const finalArchive = await handle.stat();
    if (!sameFileIdentity(openedArchive, finalArchive)) {
      errors.push('ASAR archive changed while it was being scanned');
    }
    const finalUnpacked = await collectUnpackedFiles(`${archivePath}.unpacked`, archiveDisplayPath);
    if (actualUnpacked.join('\0') !== finalUnpacked.join('\0')) {
      errors.push('ASAR unpacked tree changed while it was being scanned');
    }
    for (const path of expectedUnpacked) {
      try {
        const finalContent = await readStableRegularFile(
          resolve(`${archivePath}.unpacked`, ...path.split('/')),
        );
        if (sha256(finalContent) !== entryByPath.get(path)?.actualHash) {
          errors.push(`ASAR unpacked file changed while it was being scanned: ${path}`);
        }
      } catch (error) {
        errors.push(
          `ASAR unpacked file could not be revalidated: ${path}: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    return {
      findings: deduplicateFindings(findings),
      errors: errors.map((error) => ({ category, path: archiveDisplayPath, error })),
      scannedFiles: entryByPath.size,
      complete,
      rawPath: archiveDisplayPath,
    };
  } catch (error) {
    if (handle && openedArchive && openedArchive.size <= limits.opaqueFallbackBytes) {
      try {
        const raw = Buffer.alloc(openedArchive.size);
        const { bytesRead } = await handle.read(raw, 0, raw.length, 0);
        const afterFallbackRead = await handle.stat();
        if (bytesRead !== raw.length || !sameFileIdentity(openedArchive, afterFallbackRead)) {
          errors.push('ASAR archive changed during opaque fallback scanning');
        } else {
          appendMatches(findings, category, archiveDisplayPath, scanBufferForSecrets(raw, options.canaries));
          appendMatches(
            findings,
            category,
            archiveDisplayPath,
            options.providerMatches(raw.toString('utf8')),
          );
        }
      } catch (fallbackError) {
        errors.push(
          `ASAR opaque fallback scan failed: ${fallbackError instanceof Error ? fallbackError.message : String(fallbackError)}`,
        );
      }
    } else if (openedArchive) {
      errors.push('ASAR opaque fallback scan exceeds the configured size bound');
    }
    return {
      findings: deduplicateFindings(findings),
      errors: [
        ...errors.map((item) => ({ category, path: archiveDisplayPath, error: item })),
        {
          category,
          path: archiveDisplayPath,
          error: error instanceof Error ? error.message : String(error),
        },
      ],
      scannedFiles: 0,
      complete: false,
      rawPath: archiveDisplayPath,
    };
  } finally {
    await handle?.close();
  }
}

function packageVersion(value) {
  return plainObject(value) && typeof value.version === 'string' ? value.version : undefined;
}

function occurrenceKey(match) {
  return `${match.detector}\0${match.index}\0${match.value}`;
}

function secretOccurrenceKey(match) {
  return `${match.detector}\0${match.offset}\0${match.fingerprint}`;
}

export async function auditElectronExecutable(options) {
  const repositoryRoot = resolve(options.repositoryRoot);
  const executablePath = resolve(options.executablePath);
  const executableDisplayPath = displayPath(repositoryRoot, executablePath);
  const category = options.category;
  try {
    const [rootPackage, electronPackage, distVersion, baseline, executable] = await Promise.all([
      readStableRegularFile(resolve(repositoryRoot, 'package.json')).then((value) =>
        JSON.parse(value.toString('utf8')),
      ),
      readStableRegularFile(resolve(repositoryRoot, 'node_modules/electron/package.json')).then((value) =>
        JSON.parse(value.toString('utf8')),
      ),
      readStableRegularFile(resolve(repositoryRoot, 'node_modules/electron/dist/version')).then((value) =>
        value.toString('utf8').trim(),
      ),
      readStableRegularFile(resolve(repositoryRoot, 'node_modules/electron/dist/electron.exe')),
      readStableRegularFile(executablePath),
    ]);
    const configured = rootPackage.devDependencies?.electron ?? rootPackage.dependencies?.electron;
    const installed = packageVersion(electronPackage);
    if (typeof configured !== 'string' || configured !== installed || installed !== distVersion) {
      throw new Error('Electron executable baseline is not bound to the exact configured Electron version');
    }
    const baselineMatches = options.providerMatches(baseline.toString('latin1'));
    const executableMatches = options.providerMatches(executable.toString('latin1'));
    const baselineSecretMatches = options.secretMatches?.(baseline) ?? [];
    const executableSecretMatches = options.secretMatches?.(executable) ?? [];
    const baselineSet = new Set(baselineMatches.map(occurrenceKey));
    const executableSet = new Set(executableMatches.map(occurrenceKey));
    const baselineSecretSet = new Set(baselineSecretMatches.map(secretOccurrenceKey));
    const executableSecretSet = new Set(executableSecretMatches.map(secretOccurrenceKey));
    const extra = executableMatches.filter((match) => !baselineSet.has(occurrenceKey(match)));
    const missing = baselineMatches.filter((match) => !executableSet.has(occurrenceKey(match)));
    const extraSecrets = executableSecretMatches.filter(
      (match) => !baselineSecretSet.has(secretOccurrenceKey(match)),
    );
    const missingSecrets = baselineSecretMatches.filter(
      (match) => !executableSecretSet.has(secretOccurrenceKey(match)),
    );
    const findings = [
      ...extra.map((match) => ({
        category,
        path: executableDisplayPath,
        line: match.line,
        detector: match.detector,
        fingerprint: match.fingerprint,
      })),
      ...extraSecrets.map((match) => ({
        category,
        path: executableDisplayPath,
        line: match.line,
        detector: match.detector,
        fingerprint: match.fingerprint,
      })),
    ];
    const errors =
      missing.length > 0 || extra.length > 0 || missingSecrets.length > 0
        ? [
            {
              category,
              path: executableDisplayPath,
              error:
                'Electron provider/secret occurrence fingerprint/offset set does not exactly match the locked vendor binary',
            },
          ]
        : [];
    return { findings, errors, complete: true, rawPath: executableDisplayPath };
  } catch (error) {
    return {
      findings: [],
      errors: [
        {
          category,
          path: executableDisplayPath,
          error: error instanceof Error ? error.message : String(error),
        },
      ],
      complete: false,
      rawPath: executableDisplayPath,
    };
  }
}
