import { createHash, randomUUID } from 'node:crypto';
import { lstat, mkdir, open, readdir, realpath, rename, rm, writeFile } from 'node:fs/promises';
import { builtinModules } from 'node:module';
import { basename, isAbsolute, relative, resolve, sep } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

import {
  acquirePiBuildCacheLock,
  readPiBuildCacheArtifact,
  pinPublishedPiBuildCache,
  resolveSafePiCacheLayout,
} from './pi-cache-publication.mjs';
import { normalizePiSourceLock } from './pi-source-boundary.mjs';

const gatewayPointerName = 'pi-gateway-runtime-current.json';
const gatewayGenerationPattern = /^pi-gateway-runtime-[a-f0-9]{64}$/u;
const gatewayProvider = 'enterprise-gateway';
const gatewayApi = 'openai-completions';
/**
 * Exact export surface of the gateway-only Pi runtime bundle. Shared with the
 * packaged-artifact audit so a new export cannot silently diverge between the
 * build and the release gate.
 */
export const gatewayRuntimeRequiredExports = Object.freeze([
  'ModelRuntime',
  'SessionManager',
  'createAgentSessionFromServices',
  'createAgentSessionRuntime',
  'createAgentSessionServices',
  'createEditToolDefinition',
  'createReadToolDefinition',
  'detectSupportedImageMimeType',
  'createWriteToolDefinition',
  'parseFrontmatter',
]);
const requiredExports = gatewayRuntimeRequiredExports;
const codingEntrypoints = [
  'packages/coding-agent/dist/core/agent-session-runtime.js',
  'packages/coding-agent/dist/core/session-manager.js',
  'packages/coding-agent/dist/core/model-runtime.js',
  'packages/coding-agent/dist/core/tools/read.js',
  'packages/coding-agent/dist/core/tools/write.js',
  'packages/coding-agent/dist/utils/frontmatter.js',
  'packages/coding-agent/dist/core/skills.js',
  'packages/coding-agent/dist/core/tools/edit.js',
  'packages/coding-agent/dist/core/prompt-templates.js',
];
const GATEWAY_POINTER_RENAME_RETRY_LIMIT = 12;
const GATEWAY_POINTER_RENAME_RETRY_DELAY_MS = 25;
const GATEWAY_SNAPSHOT_RETRY_LIMIT = 8;
const GATEWAY_SNAPSHOT_RETRY_DELAY_MS = 25;

export function hasGatewayOnlyPiRuntimeBoundary(source) {
  return (
    source.startsWith(
      "import { createRequire as __workdudeCreateRequire } from 'node:module';\n" +
        'const require = __workdudeCreateRequire(import.meta.url);\n' +
        'const WORKDUDE_PI_GATEWAY_BUNDLE_POLICY = Object.freeze({"provider":"enterprise-gateway","api":"openai-completions","builtinProviders":false});\n',
    ) &&
    /function builtinProviders\(\) \{\s*return \[\];\s*\}/u.test(source) &&
    /target\.origin !== base\.origin \|\| target\.pathname !== allowedPath \|\| target\.search \|\| target\.hash \|\| target\.username \|\| target\.password \|\| method !== "POST"/u.test(
      source,
    ) &&
    source.includes('Pi provider request was blocked outside the enterprise gateway') &&
    source.includes('Pi completion correction is invalid') &&
    source.includes('Pi model registration is restricted to the enterprise gateway') &&
    source.includes('Pi native provider registration is restricted to the enterprise gateway') &&
    source.includes('Pi runtime credentials are restricted to the enterprise gateway') &&
    source.includes('Enterprise gateway fetch overrides are disabled') &&
    source.includes('Enterprise gateway credential overrides are disabled') &&
    /const opaqueGatewayApiKey = ["']workdude-opaque-gateway-key["'];/u.test(source) &&
    source.includes('Enterprise gateway transformHeaders option is invalid') &&
    source.includes('Enterprise gateway transformHeaders result is invalid') &&
    source.includes('Enterprise gateway login is managed by WorkDude authentication') &&
    source.includes('const redactGatewayError =') &&
    source.includes('const trustedInternalFacade = Object.freeze') &&
    source.includes('runtimeRecord.trustedInternalFacade') &&
    /redirect:\s*["']manual["']/u.test(source) &&
    source.includes('Enterprise gateway redirects are disabled') &&
    /\[301, 302, 303, 307, 308\]\.includes\(response\.status\)/u.test(source) &&
    source.includes('Enterprise gateway provider configuration') &&
    source.includes('Gateway resource loader options') &&
    source.includes('contains a disallowed property') &&
    source.includes('const frozenFacade = Object.freeze(facade);') &&
    source.includes('gatewayFacades.add(frozenFacade);') &&
    source.includes('Pi Agent services require the gateway-only ModelRuntime facade') &&
    source.includes('Pi Agent runtime factory must return gateway-issued session tokens') &&
    source.includes('Enterprise gateway base URL cannot change after registration')
  );
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function canonicalJson(value) {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalJson(value[key])]),
  );
}

function plainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value, keys) {
  return plainObject(value) && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
}

function isNodeBuiltin(path) {
  return path.startsWith('node:') || builtinModules.includes(path);
}

function jsonLine(value) {
  return `${JSON.stringify(canonicalJson(value))}\n`;
}

function inside(parent, child) {
  const route = relative(parent, child);
  return route === '' || (!route.startsWith('..') && !isAbsolute(route));
}

function samePath(first, second) {
  return process.platform === 'win32'
    ? first.toLocaleLowerCase('en-US') === second.toLocaleLowerCase('en-US')
    : first === second;
}

function sameStableFile(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.nlink === second.nlink &&
    first.size === second.size &&
    first.mode === second.mode &&
    first.mtimeNs === second.mtimeNs &&
    first.ctimeNs === second.ctimeNs
  );
}

function sameFileIdentity(first, second) {
  return first.dev === second.dev && first.ino === second.ino && first.nlink === second.nlink;
}

function sameStableDirectory(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.nlink === second.nlink &&
    first.mode === second.mode
  );
}

function isTransientGatewayPointerRenameError(error) {
  return (
    process.platform === 'win32' &&
    error !== null &&
    typeof error === 'object' &&
    'code' in error &&
    ['EPERM', 'EACCES', 'EBUSY'].includes(error.code)
  );
}

async function renameGatewayPointerWithRetry(renameOperation, source, destination) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await renameOperation(source, destination);
      return;
    } catch (error) {
      if (!isTransientGatewayPointerRenameError(error) || attempt >= GATEWAY_POINTER_RENAME_RETRY_LIMIT) {
        throw error;
      }
      await delay(GATEWAY_POINTER_RENAME_RETRY_DELAY_MS * (attempt + 1));
    }
  }
}

function assertPlainFile(entry, label) {
  if (entry.isSymbolicLink() || !entry.isFile()) {
    throw new Error(`${label} must be a plain file, not a symbolic link or junction`);
  }
  if (entry.nlink !== 1n) throw new Error(`${label} must not be a hard link`);
}

function assertPlainDirectory(entry, label) {
  if (entry.isSymbolicLink() || !entry.isDirectory()) {
    throw new Error(`${label} must be a plain directory, not a symbolic link, junction, or reparse point`);
  }
}

function assertContainedPath(root, path, label, allowRoot = false) {
  if (!inside(root, path) || (!allowRoot && samePath(root, path))) {
    throw new Error(`${label} resolves outside its trusted root`);
  }
}

async function resolvePlainGatewayDirectory(path, { trustedRoot, label }) {
  const resolvedPath = resolve(path);
  assertContainedPath(trustedRoot, resolvedPath, label);
  const entry = await lstat(resolvedPath, { bigint: true });
  assertPlainDirectory(entry, label);
  const canonicalPath = await realpath(resolvedPath);
  assertContainedPath(trustedRoot, canonicalPath, label);
  if (!samePath(canonicalPath, resolvedPath)) {
    throw new Error(`${label} must not traverse a symbolic link, junction, or reparse point`);
  }
  return Object.freeze({ path: canonicalPath, entry, label, trustedRoot });
}

async function assertStableGatewayDirectory(directory) {
  const entry = await lstat(directory.path, { bigint: true });
  assertPlainDirectory(entry, directory.label);
  const canonicalPath = await realpath(directory.path);
  assertContainedPath(directory.trustedRoot, canonicalPath, directory.label);
  if (!samePath(canonicalPath, directory.path) || !sameStableDirectory(directory.entry, entry)) {
    throw new Error(`${directory.label} changed while the gateway snapshot was read`);
  }
}

async function readStableGatewayFile(path, { repositoryRoot, trustedRoot, label }) {
  const resolvedPath = resolve(path);
  assertContainedPath(repositoryRoot, resolvedPath, label);
  assertContainedPath(trustedRoot, resolvedPath, label);
  const pathBefore = await lstat(resolvedPath, { bigint: true });
  assertPlainFile(pathBefore, label);
  const realPathBefore = await realpath(resolvedPath);
  assertContainedPath(repositoryRoot, realPathBefore, label);
  assertContainedPath(trustedRoot, realPathBefore, label);
  if (!samePath(realPathBefore, resolvedPath)) {
    throw new Error(`${label} must not traverse a symbolic link, junction, or reparse point`);
  }

  const handle = await open(resolvedPath, 'r');
  try {
    const handleBefore = await handle.stat({ bigint: true });
    assertPlainFile(handleBefore, label);
    if (!sameStableFile(pathBefore, handleBefore)) {
      if (label === 'The Pi gateway runtime pointer' && !sameFileIdentity(pathBefore, handleBefore)) {
        throw new Error(`${label} replaced before it could be read`);
      }
      throw new Error(`${label} changed before it could be read`);
    }
    const content = await handle.readFile();
    const handleAfter = await handle.stat({ bigint: true });
    assertPlainFile(handleAfter, label);
    const pathAfter = await lstat(resolvedPath, { bigint: true });
    assertPlainFile(pathAfter, label);
    const realPathAfter = await realpath(resolvedPath);
    assertContainedPath(repositoryRoot, realPathAfter, label);
    assertContainedPath(trustedRoot, realPathAfter, label);
    if (!samePath(realPathBefore, realPathAfter) || !samePath(realPathAfter, resolvedPath)) {
      throw new Error(`${label} changed while it was read`);
    }
    const identityChanged =
      !sameFileIdentity(handleBefore, handleAfter) || !sameFileIdentity(handleAfter, pathAfter);
    if (identityChanged) {
      if (label === 'The Pi gateway runtime pointer') {
        throw new Error(`${label} replaced while it was read`);
      }
      throw new Error(`${label} changed while it was read`);
    }
    if (!sameStableFile(handleBefore, handleAfter) || !sameStableFile(handleAfter, pathAfter)) {
      throw new Error(`${label} changed while it was read`);
    }
    return Object.freeze({
      path: resolvedPath,
      realPath: realPathAfter,
      entry: pathAfter,
      content,
      repositoryRoot,
      trustedRoot,
      label,
    });
  } finally {
    await handle.close();
  }
}

async function assertStableGatewayFile(file) {
  const entry = await lstat(file.path, { bigint: true });
  assertPlainFile(entry, file.label);
  const canonicalPath = await realpath(file.path);
  assertContainedPath(file.repositoryRoot, canonicalPath, file.label);
  assertContainedPath(file.trustedRoot, canonicalPath, file.label);
  if (!samePath(canonicalPath, file.realPath) || !samePath(canonicalPath, file.path)) {
    throw new Error(`${file.label} changed while the gateway snapshot was validated`);
  }
  if (!sameFileIdentity(file.entry, entry)) {
    if (file.label === 'The Pi gateway runtime pointer') {
      throw new Error(`${file.label} replaced while the snapshot was validated`);
    }
    throw new Error(`${file.label} changed while the gateway snapshot was validated`);
  }
  if (!sameStableFile(file.entry, entry)) {
    throw new Error(`${file.label} changed while the gateway snapshot was validated`);
  }
}

function safeArtifactPath(path) {
  return (
    typeof path === 'string' &&
    path.length > 0 &&
    !isAbsolute(path) &&
    !path.includes('\\') &&
    path.split('/').every((segment) => segment && segment !== '.' && segment !== '..')
  );
}

function modulePath(root, path) {
  return JSON.stringify(resolve(root, ...path.split('/')).replaceAll('\\', '/'));
}

function gatewayCompatSource(piRoot) {
  return `
export { clampThinkingLevel, getSupportedThinkingLevels, modelsAreEqual } from ${modulePath(piRoot, 'packages/ai/dist/models.js')};
export { cleanupSessionResources } from ${modulePath(piRoot, 'packages/ai/dist/session-resources.js')};
export { isContextOverflow, isRecoverableLength } from ${modulePath(piRoot, 'packages/ai/dist/utils/overflow.js')};
export { isRetryableAssistantError } from ${modulePath(piRoot, 'packages/ai/dist/utils/retry.js')};
import { openAICompletionsApi } from ${modulePath(piRoot, 'packages/ai/dist/api/openai-completions.lazy.js')};

const streams = openAICompletionsApi();
const expectedProvider = ${JSON.stringify(gatewayProvider)};
const expectedApi = ${JSON.stringify(gatewayApi)};
// Capture the platform fetch once, before any caller-controlled extension or
// session code can replace globalThis.fetch.  A caller-supplied fetch is not a
// transport adapter: it is an alternate egress implementation, so it is
// rejected instead of being trusted merely because its input URL was checked.
const trustedGatewayFetch = globalThis.fetch;
const runtimeBindingSymbol = Symbol('workdude-gateway-runtime-binding');
const runtimeBindings = new WeakMap();

const credentialHeaderNames = new Set([
  'authorization',
  'proxy-authorization',
  'api-key',
  'x-api-key',
  'x-goog-api-key',
  'x-anthropic-api-key',
  'x-azure-api-key',
  'x-litellm-api-key',
  'cf-aig-authorization',
  'cookie',
  'x-auth-token',
  'x-access-token',
  'x-session-token',
]);

function runtimeBindingFor(options) {
  const token = options && typeof options === 'object' ? options[runtimeBindingSymbol] : undefined;
  const readApiKey = token && typeof token === 'object' ? runtimeBindings.get(token) : undefined;
  return readApiKey ? readApiKey() : undefined;
}

function requestOptionDescriptors(options) {
  const prototype = options && typeof options === 'object' ? Object.getPrototypeOf(options) : undefined;
  if (
    !options ||
    typeof options !== 'object' ||
    Array.isArray(options) ||
    (prototype !== Object.prototype && prototype !== null)
  ) {
    throw new Error('Enterprise gateway credential overrides are disabled');
  }
  const descriptors = Object.getOwnPropertyDescriptors(options);
  for (const name of ['fetch', 'apiKey', 'headers']) {
    const descriptor = descriptors[name];
    if (
      descriptor &&
      (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value'))
    ) {
      throw new Error('Enterprise gateway credential overrides are disabled');
    }
  }
  return descriptors;
}

function assertCredentialHeaders(options, descriptors = requestOptionDescriptors(options)) {
  const apiKey = runtimeBindingFor(options);
  if (typeof apiKey !== 'string' || !apiKey) {
    throw new Error('Enterprise gateway runtime binding is missing');
  }
  if (
    descriptors.apiKey &&
    descriptors.apiKey.value !== undefined &&
    descriptors.apiKey.value !== apiKey
  ) {
    throw new Error('Enterprise gateway credential overrides are disabled');
  }
  const headers = descriptors.headers?.value;
  if (headers === undefined) return undefined;
  if (
    !headers ||
    typeof headers !== 'object' ||
    Array.isArray(headers) ||
    (Object.getPrototypeOf(headers) !== Object.prototype && Object.getPrototypeOf(headers) !== null)
  ) {
    throw new Error('Enterprise gateway credential overrides are disabled');
  }
  if (Object.getOwnPropertySymbols(headers).length > 0) {
    throw new Error('Enterprise gateway credential overrides are disabled');
  }
  const headerDescriptors = Object.getOwnPropertyDescriptors(headers);
  const normalizedHeaderNames = new Set();
  for (const [name, descriptor] of Object.entries(headerDescriptors)) {
    if (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
      throw new Error('Enterprise gateway credential overrides are disabled');
    }
    const value = descriptor.value;
    if (value !== null && typeof value !== 'string') {
      throw new Error('Enterprise gateway credential overrides are disabled');
    }
    const normalizedName = name.toLowerCase();
    if (normalizedHeaderNames.has(normalizedName)) {
      throw new Error('Enterprise gateway credential overrides are disabled');
    }
    normalizedHeaderNames.add(normalizedName);
    if (!credentialHeaderNames.has(normalizedName)) continue;
    if (
      normalizedName === 'authorization' &&
      typeof apiKey === 'string' &&
      value === \`Bearer \${apiKey}\`
    ) {
      continue;
    }
    throw new Error('Enterprise gateway credential overrides are disabled');
  }
  const snapshot = Object.create(null);
  for (const [name, descriptor] of Object.entries(headerDescriptors)) {
    snapshot[name] = descriptor.value;
  }
  return Object.freeze(snapshot);
}

function assertGatewayModel(model) {
  if (model?.provider !== expectedProvider || model?.api !== expectedApi || typeof model?.baseUrl !== 'string') {
    throw new Error('Pi model execution is restricted to the enterprise gateway');
  }
  const base = new URL(model.baseUrl);
  const loopback = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(base.hostname);
  if (
    (base.protocol !== 'https:' && base.protocol !== 'http:') ||
    (base.protocol === 'http:' && !loopback) ||
    base.username ||
    base.password
  ) {
    throw new Error('Enterprise gateway model base URL is invalid');
  }
  return base;
}

function guardedOptions(model, options = {}) {
  const base = assertGatewayModel(model);
  const descriptors = requestOptionDescriptors(options);
  if (descriptors.fetch?.value !== undefined) {
    throw new Error('Enterprise gateway fetch overrides are disabled');
  }
  const safeHeaders = assertCredentialHeaders(options, descriptors);
  if (typeof trustedGatewayFetch !== 'function') throw new Error('Enterprise gateway fetch is unavailable');
  const basePath = base.pathname.replace(/\\/$/u, '');
  const allowedPath = \`\${basePath}/chat/completions\`.replace(/^\\/{2,}/u, '/');
  const safeOptions = Object.create(null);
  for (const [name, descriptor] of Object.entries(descriptors)) safeOptions[name] = descriptor.value;
  const bindingToken = options[runtimeBindingSymbol];
  if (bindingToken && typeof bindingToken === 'object') {
    Object.defineProperty(safeOptions, runtimeBindingSymbol, {
      value: bindingToken,
      enumerable: true,
      writable: false,
      configurable: false,
    });
  }
  if (safeHeaders !== undefined) safeOptions.headers = safeHeaders;
  return {
    ...safeOptions,
    fetch: async (input, init) => {
      const target = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
      const method = String(init?.method ?? (typeof input === 'object' && 'method' in input ? input.method : 'GET')).toUpperCase();
      if (
        target.origin !== base.origin ||
        target.pathname !== allowedPath ||
        target.search ||
        target.hash ||
        target.username ||
        target.password ||
        method !== 'POST'
      ) {
        throw new Error('Pi provider request was blocked outside the enterprise gateway');
      }
      // Node 24.14 fetch with redirect:error can lose stream abort linkage after
      // GC. Manual mode preserves cancellation while never following redirects.
      const response = await trustedGatewayFetch(input, { ...(init ?? {}), redirect: 'manual' });
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        await response.body?.cancel().catch(() => undefined);
        throw new Error('Enterprise gateway redirects are disabled');
      }
      return response;
    },
  };
}

export function createTrustedGatewayRuntimeBinding() {
  let apiKey;
  const token = Object.freeze({});
  runtimeBindings.set(token, () => apiKey);
  return Object.freeze({
    setApiKey(value) {
      if (typeof value !== 'string' || !value) {
        throw new Error('Enterprise gateway credential is invalid');
      }
      apiKey = value;
    },
    decorate(options) {
      if (
        options !== undefined &&
        (!options || typeof options !== 'object' || Array.isArray(options))
      ) {
        throw new Error('Enterprise gateway request options are invalid');
      }
      const decorated = options === undefined ? {} : { ...options };
      Object.defineProperty(decorated, runtimeBindingSymbol, {
        value: token,
        enumerable: true,
        writable: false,
        configurable: false,
      });
      return decorated;
    },
  });
}

export function getApiProvider(api) {
  return api === expectedApi
    ? {
        stream: (model, context, options) => streams.stream(model, context, guardedOptions(model, options)),
        streamSimple: (model, context, options) =>
          streams.streamSimple(model, context, guardedOptions(model, options)),
      }
    : undefined;
}
export function getApiProviders() {
  return [getApiProvider(expectedApi)];
}
export function resetApiProviders() {}
export function stream(model, context, options) {
  return getApiProvider(model.api)?.stream(model, context, options) ??
    (() => { throw new Error('Only enterprise gateway completions are permitted'); })();
}
export function streamSimple(model, context, options) {
  return getApiProvider(model.api)?.streamSimple(model, context, options) ??
    (() => { throw new Error('Only enterprise gateway completions are permitted'); })();
}
export async function complete(model, context, options) {
  return stream(model, context, options).result();
}
export async function completeSimple(model, context, options) {
  return streamSimple(model, context, options).result();
}
`;
}

function gatewayProvidersSource() {
  return `
export function builtinProviders() { return []; }
export function builtinModels() { throw new Error('Builtin providers are disabled by the enterprise gateway boundary'); }
export function getBuiltinModelDataGeneratedAt() { return undefined; }
export function radiusProvider() { throw new Error('Radius providers are disabled by the enterprise gateway boundary'); }
export function getBuiltinModel() { return undefined; }
export function getBuiltinModels() { return []; }
export function getBuiltinProviders() { return []; }
`;
}

function gatewayEntrySource(piRoot) {
  return `
import {
  createAgentSessionFromServices as createPiAgentSessionFromServices,
  createAgentSessionRuntime as createPiAgentSessionRuntime,
  createAgentSessionServices as createPiAgentSessionServices,
} from ${modulePath(piRoot, codingEntrypoints[0])};
export { SessionManager } from ${modulePath(piRoot, codingEntrypoints[1])};
export { createReadToolDefinition } from ${modulePath(piRoot, codingEntrypoints[3])};
export { detectSupportedImageMimeType } from ${modulePath(piRoot, 'packages/coding-agent/dist/utils/mime.js')};
export { createWriteToolDefinition } from ${modulePath(piRoot, codingEntrypoints[4])};
export { createEditToolDefinition } from ${modulePath(piRoot, codingEntrypoints[7])};
export { parseFrontmatter } from ${modulePath(piRoot, codingEntrypoints[5])};
import { loadSkills as loadNativeSkills } from ${modulePath(piRoot, codingEntrypoints[6])};
import { loadPromptTemplates as loadNativePromptTemplates } from ${modulePath(piRoot, codingEntrypoints[8])};
import { ModelRuntime as PiModelRuntime } from ${modulePath(piRoot, codingEntrypoints[2])};
import { createTrustedGatewayRuntimeBinding as createCompatGatewayRuntimeBinding } from '@earendil-works/pi-ai/compat';

const expectedProvider = ${JSON.stringify(gatewayProvider)};
const expectedApi = ${JSON.stringify(gatewayApi)};
const gatewayFacades = new WeakSet();
const gatewayFacadeRecords = new WeakMap();
const gatewayServiceRecords = new WeakMap();
const safeServicesByRaw = new WeakMap();
const gatewaySessionRecords = new WeakMap();
const safeSessionsByRaw = new WeakMap();

function snapshotDataRecord(value, allowedKeys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(label + ' must be a plain data record');
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new Error(label + ' must be a plain data record');
  }
  if (Object.getOwnPropertySymbols(value).length > 0) {
    throw new Error(label + ' must not contain symbol properties');
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Object.keys(descriptors);
  if (keys.some((key) => !allowedKeys.includes(key))) {
    throw new Error(label + ' contains a disallowed property');
  }
  const snapshot = {};
  for (const key of keys) {
    const descriptor = descriptors[key];
    if (!descriptor || !descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
      throw new Error(label + ' properties must be enumerable data properties');
    }
    snapshot[key] = descriptor.value;
  }
  return snapshot;
}

function cloneData(value, label, seen = new WeakMap()) {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'undefined'
  ) {
    return value;
  }
  if (typeof value !== 'object') throw new Error(label + ' must contain data only');
  if (seen.has(value)) return seen.get(value);
  if (Array.isArray(value)) {
    if (Object.getPrototypeOf(value) !== Array.prototype || Object.keys(value).length !== value.length) {
      throw new Error(label + ' must contain plain arrays');
    }
    const copy = [];
    seen.set(value, copy);
    for (let index = 0; index < value.length; index += 1) {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      if (!descriptor || !descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
        throw new Error(label + ' array items must be data properties');
      }
      copy.push(cloneData(descriptor.value, label, seen));
    }
    return Object.freeze(copy);
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new Error(label + ' must contain plain objects');
  }
  if (Object.getOwnPropertySymbols(value).length > 0) {
    throw new Error(label + ' must not contain symbol properties');
  }
  const copy = {};
  seen.set(value, copy);
  for (const [key, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(value))) {
    if (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
      throw new Error(label + ' object fields must be data properties');
    }
    copy[key] = cloneData(descriptor.value, label, seen);
  }
  return Object.freeze(copy);
}

function canonicalGatewayBaseUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error('Enterprise gateway base URL is invalid');
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(url.hostname);
  if (
    (url.protocol !== 'https:' && url.protocol !== 'http:') ||
    (url.protocol === 'http:' && !loopback) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error('Enterprise gateway base URL is invalid');
  }
  const path = url.pathname.replace(/\\/+$/u, '') || '/';
  return \`\${url.origin}\${path}\`;
}

function cloneAndFreeze(value, seen = new WeakMap()) {
  if (!value || typeof value !== 'object') return value;
  if (seen.has(value)) return seen.get(value);
  const copy = Array.isArray(value) ? [] : {};
  seen.set(value, copy);
  for (const [key, child] of Object.entries(value)) copy[key] = cloneAndFreeze(child, seen);
  return Object.freeze(copy);
}

function assertProviderConfiguration(provider, configuration) {
  const input = snapshotDataRecord(
    configuration,
    ['name', 'baseUrl', 'apiKey', 'api', 'authHeader', 'headers', 'models'],
    'Enterprise gateway provider configuration',
  );
  const baseUrl = typeof input.baseUrl === 'string' ? canonicalGatewayBaseUrl(input.baseUrl) : undefined;
  const models = Array.isArray(input.models)
    ? snapshotArrayValues(input.models, 'Enterprise gateway models').map((value) => {
        const model = snapshotDataRecord(
          value,
          ['id', 'name', 'api', 'baseUrl', 'reasoning', 'input', 'cost', 'contextWindow', 'maxTokens'],
          'Enterprise gateway model configuration',
        );
        return Object.freeze({
          ...model,
          input: cloneData(model.input, 'Enterprise gateway model input'),
          cost: cloneData(model.cost, 'Enterprise gateway model cost'),
        });
      })
    : undefined;
  if (
    provider !== expectedProvider ||
    input.api !== expectedApi ||
    !baseUrl ||
    typeof input.apiKey !== 'string' ||
    !input.apiKey ||
    (input.authHeader !== undefined && input.authHeader !== true) ||
    !models ||
    models.length === 0 ||
    models.some(
      (model) =>
        typeof model.id !== 'string' ||
        !model.id ||
        (model.name !== undefined && typeof model.name !== 'string') ||
        model.api !== expectedApi ||
        (model.baseUrl !== undefined &&
          (typeof model.baseUrl !== 'string' || canonicalGatewayBaseUrl(model.baseUrl) !== baseUrl)) ||
        (model.reasoning !== undefined && typeof model.reasoning !== 'boolean') ||
        !Array.isArray(model.input) ||
        model.input.length === 0 ||
        model.input.some((kind) => kind !== 'text' && kind !== 'image') ||
        !model.cost ||
        typeof model.cost !== 'object' ||
        ['input', 'output', 'cacheRead', 'cacheWrite'].some(
          (name) => typeof model.cost[name] !== 'number' || !Number.isFinite(model.cost[name]),
        ) ||
        !Number.isSafeInteger(model.contextWindow) ||
        model.contextWindow <= 0 ||
        !Number.isSafeInteger(model.maxTokens) ||
        model.maxTokens <= 0,
    )
  ) {
    throw new Error('Pi model registration is restricted to the enterprise gateway');
  }
  const headers = input.headers === undefined ? undefined : cloneData(input.headers, 'Enterprise gateway headers');
  if (
    headers !== undefined &&
    (!headers ||
      Array.isArray(headers) ||
      Object.values(headers).some((value) => value !== null && typeof value !== 'string'))
  ) {
    throw new Error('Pi model registration is restricted to the enterprise gateway');
  }
  const safeModels = models.map((model) =>
    Object.freeze({ ...model, reasoning: model.reasoning === true }),
  );
  return Object.freeze({
    baseUrl,
    configuration: Object.freeze({
      ...(typeof input.name === 'string' ? { name: input.name } : {}),
      baseUrl,
      apiKey: input.apiKey,
      api: expectedApi,
      authHeader: true,
      ...(headers ? { headers } : {}),
      models: Object.freeze(safeModels),
    }),
  });
}

function snapshotArrayValues(value, label) {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype) {
    throw new Error(label + ' must be a plain array');
  }
  const snapshot = [];
  for (let index = 0; index < value.length; index += 1) {
    const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
    if (
      !descriptor ||
      !descriptor.enumerable ||
      !Object.prototype.hasOwnProperty.call(descriptor, 'value')
    ) {
      throw new Error(label + ' items must be data properties');
    }
    snapshot.push(descriptor.value);
  }
  if (Object.keys(value).length !== snapshot.length) {
    throw new Error(label + ' must not contain additional properties');
  }
  return Object.freeze(snapshot);
}

function snapshotStringArray(value, label) {
  const snapshot = snapshotArrayValues(value, label);
  if (snapshot.some((item) => typeof item !== 'string')) {
    throw new Error(label + ' must be a plain string array');
  }
  return snapshot;
}

function safeResourceLoaderOptions(value, cwd, agentDir) {
  const input = value === undefined
    ? {}
    : snapshotDataRecord(
        value,
        [
          'noExtensions',
          'noSkills',
          'noPromptTemplates',
          'noThemes',
          'noContextFiles',
          'additionalSkillPaths',
          'pluginSkills',
          'pluginCommands',
          'systemPrompt',
        ],
        'Gateway resource loader options',
      );
  if (input.systemPrompt !== undefined && typeof input.systemPrompt !== 'string') {
    throw new Error('Gateway resource loader system prompt must be text');
  }
  const additionalSkillPaths =
    input.additionalSkillPaths === undefined
      ? Object.freeze([])
      : snapshotStringArray(input.additionalSkillPaths, 'Gateway additional Skill paths');
  const pluginSkills = input.pluginSkills === undefined ? [] : snapshotArrayValues(input.pluginSkills, 'Gateway plugin Skill inventory');
  const pluginInventory = pluginSkills.map((entry) => {
    const record = snapshotDataRecord(entry, ['namespace', 'paths'], 'Gateway plugin Skill inventory');
    if (typeof record.namespace !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(record.namespace)) {
      throw new Error('Gateway plugin Skill namespace is invalid');
    }
    return Object.freeze({ namespace: record.namespace, paths: snapshotStringArray(record.paths, 'Gateway plugin Skill paths') });
  });
  const pluginCommands = input.pluginCommands === undefined ? [] : snapshotArrayValues(input.pluginCommands, 'Gateway plugin command inventory');
  const commandInventory = pluginCommands.map((entry) => {
    const record = snapshotDataRecord(entry, ['namespace', 'paths'], 'Gateway plugin command inventory');
    if (typeof record.namespace !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(record.namespace)) {
      throw new Error('Gateway plugin command namespace is invalid');
    }
    return Object.freeze({ namespace: record.namespace, paths: snapshotStringArray(record.paths, 'Gateway plugin command paths') });
  });
  return Object.freeze({
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    additionalSkillPaths,
    ...(commandInventory.length ? { promptsOverride(base) {
      const prompts = [...base.prompts];
      const diagnostics = [...base.diagnostics];
      const names = new Set(prompts.map((prompt) => prompt.name));
      for (const entry of commandInventory) {
        const loaded = loadNativePromptTemplates({ cwd, agentDir, promptPaths: entry.paths, includeDefaults: false });
        if (loaded.templates.length !== entry.paths.length) throw new Error('Gateway plugin command could not be loaded');
        diagnostics.push(...loaded.diagnostics);
        for (const prompt of loaded.templates) {
          const name = entry.namespace + ':' + prompt.name;
          if (names.has(name)) throw new Error('Gateway plugin command identity is duplicated');
          names.add(name);
          prompts.push({ ...prompt, name });
        }
      }
      return { prompts, diagnostics };
    }} : {}),
    ...(pluginInventory.length ? { skillsOverride(base) {
      const skills = [...base.skills];
      const diagnostics = [...base.diagnostics];
      const names = new Set(skills.map((skill) => skill.name));
      for (const entry of pluginInventory) {
        const discovered = loadNativeSkills({ cwd, agentDir, skillPaths: entry.paths, includeDefaults: false });
        if (discovered.diagnostics.some((diagnostic) => diagnostic.type === 'collision')) {
          throw new Error('Gateway plugin Skill inventory contains duplicate names');
        }
        diagnostics.push(...discovered.diagnostics);
        for (const skill of discovered.skills) {
          const name = entry.namespace + ':' + skill.name;
          if (names.has(name)) throw new Error('Gateway plugin Skill qualified identity is duplicated');
          names.add(name);
          skills.push({ ...skill, name });
        }
      }
      return { skills, diagnostics };
    } } : {}),
    ...(input.systemPrompt === undefined ? {} : { systemPrompt: input.systemPrompt }),
  });
}

function safeDiagnostics(value) {
  if (!Array.isArray(value)) return Object.freeze([]);
  return Object.freeze(
    value.map((diagnostic) =>
      Object.freeze({
        type: diagnostic?.type === 'error' || diagnostic?.type === 'warning' ? diagnostic.type : 'info',
        message: typeof diagnostic?.message === 'string' ? diagnostic.message : String(diagnostic?.message ?? ''),
      }),
    ),
  );
}

export const ModelRuntime = Object.freeze({
  async create(options) {
    const runtime = await PiModelRuntime.create({
      ...(options ?? {}),
      modelsPath: null,
      refreshOnCreate: false,
      allowModelNetwork: false,
    });
    const registerProvider = runtime.registerProvider.bind(runtime);
    const setRuntimeApiKey = runtime.setRuntimeApiKey.bind(runtime);
    const getModel = runtime.getModel.bind(runtime);
    const getModels = runtime.getModels.bind(runtime);
    const getProviders = runtime.getProviders.bind(runtime);
    const getProvider = runtime.getProvider.bind(runtime);
    const getAvailable = runtime.getAvailable.bind(runtime);
    const getAvailableSnapshot = runtime.getAvailableSnapshot.bind(runtime);
    const checkAuth = runtime.checkAuth.bind(runtime);
    const getAuth = runtime.getAuth.bind(runtime);
    const hasConfiguredAuth = runtime.hasConfiguredAuth.bind(runtime);
    const isUsingOAuth = runtime.isUsingOAuth.bind(runtime);
    const isUsingSubscription = runtime.isUsingSubscription.bind(runtime);
    const refresh = runtime.refresh.bind(runtime);
    const getError = runtime.getError.bind(runtime);
    const listCredentials = runtime.listCredentials.bind(runtime);
    const getProviderAuthStatus = runtime.getProviderAuthStatus.bind(runtime);
    const stream = runtime.stream.bind(runtime);
    const complete = runtime.complete.bind(runtime);
    const streamSimple = runtime.streamSimple.bind(runtime);
    const completeSimple = runtime.completeSimple.bind(runtime);
    const fetchDeferred = runtime.fetchDeferred.bind(runtime);
    const cancelDeferred = runtime.cancelDeferred.bind(runtime);
    const logout = runtime.logout.bind(runtime);
    let gatewayBaseUrl;
    let gatewayApiKey;
    const compatGatewayRuntimeBinding = createCompatGatewayRuntimeBinding();
    const safeModelCache = new WeakMap();

    const currentModel = (candidate) => {
      if (!candidate || typeof candidate !== 'object') {
        throw new Error('Pi model execution is restricted to the enterprise gateway');
      }
      if (candidate.provider !== expectedProvider || candidate.api !== expectedApi) {
        throw new Error('Pi model execution is restricted to the enterprise gateway');
      }
      const modelId = typeof candidate.id === 'string' ? candidate.id : '';
      const current = modelId ? getModel(expectedProvider, modelId) : undefined;
      if (!current || current.provider !== expectedProvider || current.api !== expectedApi) {
        throw new Error('Pi model execution is restricted to the enterprise gateway');
      }
      const currentBase =
        typeof current.baseUrl === 'string'
          ? canonicalGatewayBaseUrl(current.baseUrl)
          : gatewayBaseUrl;
      if (!gatewayBaseUrl || !currentBase || currentBase !== gatewayBaseUrl) {
        throw new Error('Pi model execution is restricted to the enterprise gateway');
      }
      if (candidate.baseUrl !== undefined && canonicalGatewayBaseUrl(candidate.baseUrl) !== currentBase) {
        throw new Error('Pi model execution is restricted to the enterprise gateway');
      }
      return current;
    };

    const safeModel = (model) => {
      if (!model) return model;
      const cached = safeModelCache.get(model);
      if (cached) return cached;
      const frozen = cloneAndFreeze(model);
      safeModelCache.set(model, frozen);
      return frozen;
    };
    const safeModels = (models) => Object.freeze([...models].map(safeModel));
    const credentialHeaderNames = new Set([
      'authorization',
      'proxy-authorization',
      'api-key',
      'x-api-key',
      'x-goog-api-key',
      'x-anthropic-api-key',
      'x-azure-api-key',
      'x-litellm-api-key',
      'cf-aig-authorization',
      'cookie',
      'x-auth-token',
      'x-access-token',
      'x-session-token',
    ]);
    const opaqueGatewayApiKey = 'workdude-opaque-gateway-key';
    const normalizeRequestOptions = (options) => {
      if (!options || typeof options !== 'object') {
        return options;
      }
      if (Object.getOwnPropertySymbols(options).length > 0) {
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
      const apiKeyDescriptor = Object.getOwnPropertyDescriptor(options, 'apiKey');
      if (
        !apiKeyDescriptor ||
        !apiKeyDescriptor.enumerable ||
        !Object.prototype.hasOwnProperty.call(apiKeyDescriptor, 'value') ||
        apiKeyDescriptor.value !== opaqueGatewayApiKey
      ) {
        return options;
      }
      const sanitized = {};
      for (const [name, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(options))) {
        if (name === 'apiKey') continue;
        if (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
          throw new Error('Enterprise gateway request options are invalid');
        }
        sanitized[name] = descriptor.value;
      }
      return sanitized;
    };
    const assertRequestOptions = (options) => {
      if (options === undefined) return;
      if (
        !options ||
        typeof options !== 'object' ||
        Array.isArray(options) ||
        (Object.getPrototypeOf(options) !== Object.prototype && Object.getPrototypeOf(options) !== null)
      ) {
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
      if (Object.getOwnPropertySymbols(options).length > 0) {
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
      const optionDescriptors = Object.getOwnPropertyDescriptors(options);
      // transformHeaders runs after Pi resolves the configured auth. The
      // adapter wraps it below so caller code sees only non-credential headers.
      const transformHeadersDescriptor = optionDescriptors.transformHeaders;
      if (
        transformHeadersDescriptor &&
        (!transformHeadersDescriptor.enumerable ||
          !Object.prototype.hasOwnProperty.call(transformHeadersDescriptor, 'value') ||
          (transformHeadersDescriptor.value !== undefined &&
            typeof transformHeadersDescriptor.value !== 'function'))
      ) {
        throw new Error('Enterprise gateway transformHeaders option is invalid');
      }
      const fetchDescriptor = optionDescriptors.fetch;
      if (fetchDescriptor) {
        if (
          !fetchDescriptor.enumerable ||
          !Object.prototype.hasOwnProperty.call(fetchDescriptor, 'value') ||
          fetchDescriptor.value !== undefined
        ) {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
      }
      const apiKeyDescriptor = optionDescriptors.apiKey;
      if (apiKeyDescriptor) {
        if (!apiKeyDescriptor.enumerable || !Object.prototype.hasOwnProperty.call(apiKeyDescriptor, 'value')) {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
        const value = apiKeyDescriptor.value;
        if (
          value !== undefined &&
          value !== opaqueGatewayApiKey &&
          (typeof gatewayApiKey !== 'string' || value !== gatewayApiKey)
        ) {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
      }
      const headersDescriptor = optionDescriptors.headers;
      if (!headersDescriptor) return;
      if (!headersDescriptor.enumerable || !Object.prototype.hasOwnProperty.call(headersDescriptor, 'value')) {
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
      const headers = headersDescriptor.value;
      if (headers === undefined) return;
      if (
        !headers ||
        typeof headers !== 'object' ||
        Array.isArray(headers) ||
        (Object.getPrototypeOf(headers) !== Object.prototype && Object.getPrototypeOf(headers) !== null)
      ) {
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
      if (Object.getOwnPropertySymbols(headers).length > 0) {
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
      const normalizedHeaderNames = new Set();
      for (const [name, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(headers))) {
        if (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
        const normalizedName = name.toLowerCase();
        if (normalizedHeaderNames.has(normalizedName)) {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
        normalizedHeaderNames.add(normalizedName);
        if (descriptor.value !== null && typeof descriptor.value !== 'string') {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
        if (!credentialHeaderNames.has(normalizedName)) continue;
        if (descriptor.value === null) {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
        if (
          normalizedName === 'authorization' &&
          typeof gatewayApiKey === 'string' &&
          descriptor.value === \`Bearer \${gatewayApiKey}\`
        ) {
          continue;
        }
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
    };
    const wrapTransformHeaders = (options) => {
      if (!options || typeof options !== 'object') return options;
      if (Object.getOwnPropertySymbols(options).length > 0) {
        throw new Error('Enterprise gateway credential overrides are disabled');
      }
      const transformDescriptor = Object.getOwnPropertyDescriptor(options, 'transformHeaders');
      if (
        !transformDescriptor ||
        !transformDescriptor.enumerable ||
        !Object.prototype.hasOwnProperty.call(transformDescriptor, 'value') ||
        typeof transformDescriptor.value !== 'function'
      ) {
        return options;
      }
      const transformHeaders = transformDescriptor.value;
      const wrapped = {};
      for (const [name, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(options))) {
        if (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
          throw new Error('Enterprise gateway request options are invalid');
        }
        wrapped[name] = descriptor.value;
      }
      wrapped.transformHeaders = async (headers) => {
        const original = headers && typeof headers === 'object' && !Array.isArray(headers) ? headers : {};
        const visible = Object.fromEntries(
          Object.entries(original).filter(([name]) => !credentialHeaderNames.has(name.toLowerCase())),
        );
        const transformed = await transformHeaders(Object.freeze(visible));
        const output = {};
        for (const [name, value] of Object.entries(original)) {
          if (credentialHeaderNames.has(name.toLowerCase())) output[name] = value;
        }
        if (transformed === undefined) {
          for (const [name, value] of Object.entries(original)) {
            if (!credentialHeaderNames.has(name.toLowerCase())) output[name] = value;
          }
          return output;
        }
        if (
          !transformed ||
          typeof transformed !== 'object' ||
          Array.isArray(transformed) ||
          (Object.getPrototypeOf(transformed) !== Object.prototype &&
            Object.getPrototypeOf(transformed) !== null)
        ) {
          throw new Error('Enterprise gateway transformHeaders result is invalid');
        }
        for (const [name, value] of Object.entries(transformed)) {
          if (!credentialHeaderNames.has(name.toLowerCase())) output[name] = value;
        }
        return output;
      };
      return wrapped;
    };
    const guardedStream = (method, model, ...args) => {
      const normalized = wrapTransformHeaders(normalizeRequestOptions(args[1]));
      assertRequestOptions(normalized);
      const requestArgs = [...args];
      requestArgs[1] = compatGatewayRuntimeBinding.decorate(normalized);
      return method(currentModel(model), ...requestArgs);
    };
    const redactGatewayError = (error) => {
      const message = error instanceof Error ? error.message : String(error);
      return gatewayApiKey ? message.replaceAll(gatewayApiKey, '[REDACTED]') : message;
    };
    const safeRefresh = (options = {}) =>
      refresh({ ...options, allowNetwork: false }).then((result) => ({
        ...result,
        errors: new Map(
          [...result.errors].map(([provider, error]) => [provider, new Error(redactGatewayError(error))]),
        ),
      }));
    const protectedProvider = (provider) => {
      if (!provider || provider.id !== expectedProvider) return undefined;
      return Object.freeze({
        id: expectedProvider,
        name: provider.name,
        baseUrl: gatewayBaseUrl,
        getModels: () => safeModels(provider.getModels()),
        stream: (model, context, options) => guardedStream(stream, model, context, options),
        streamSimple: (model, context, options) => guardedStream(streamSimple, model, context, options),
        ...(provider.fetchDeferred
          ? { fetchDeferred: (model, handle, options) => guardedStream(fetchDeferred, model, handle, options) }
          : {}),
        ...(provider.cancelDeferred
          ? { cancelDeferred: (model, handle, options) => guardedStream(cancelDeferred, model, handle, options) }
          : {}),
      });
    };
    const facade = {
      getProviders() {
        if (!gatewayBaseUrl) return Object.freeze([]);
        const provider = protectedProvider(getProvider(expectedProvider));
        return provider ? Object.freeze([provider]) : Object.freeze([]);
      },
      getProvider(provider) {
        return provider === expectedProvider ? protectedProvider(getProvider(provider)) : undefined;
      },
      getModels(provider) {
        return provider && provider !== expectedProvider ? Object.freeze([]) : safeModels(getModels(expectedProvider));
      },
      getModel(provider, model) {
        if (provider !== expectedProvider) return undefined;
        return safeModel(getModel(provider, model));
      },
      getAvailable(provider, options) {
        if (provider && provider !== expectedProvider) return Promise.resolve(Object.freeze([]));
        return getAvailable(expectedProvider, options).then(safeModels);
      },
      getAvailableSnapshot() {
        return safeModels(getAvailableSnapshot());
      },
      checkAuth(provider, options) {
        if (provider !== expectedProvider) return Promise.resolve(undefined);
        assertRequestOptions(options);
        return checkAuth(provider, options);
      },
      getAuth(providerOrModel, options) {
        assertRequestOptions(options);
        const resolve =
          typeof providerOrModel === 'string'
            ? providerOrModel === expectedProvider
              ? getAuth(providerOrModel, options)
              : Promise.resolve(undefined)
            : getAuth(currentModel(providerOrModel), options);
        // Auth resolution is an internal Pi operation, but this facade is
        // caller-visible.  Return only non-secret metadata; apiKey, headers,
        // and provider-scoped env values must never cross the boundary.
        return resolve.then((result) =>
          result
            ? Object.freeze({
                auth: Object.freeze({
                  apiKey: opaqueGatewayApiKey,
                  ...(typeof result.auth?.baseUrl === 'string'
                    ? { baseUrl: canonicalGatewayBaseUrl(result.auth.baseUrl) }
                    : {}),
                }),
                source: 'enterprise-gateway',
              })
            : undefined,
        );
      },
      hasConfiguredAuth(provider) {
        return provider === expectedProvider && hasConfiguredAuth(provider);
      },
      isUsingOAuth(provider) {
        return provider === expectedProvider && isUsingOAuth(provider);
      },
      isUsingSubscription(provider) {
        return provider === expectedProvider && isUsingSubscription(provider);
      },
      refresh(options = {}) {
        return safeRefresh(options);
      },
      getError() {
        const error = getError();
        return error === undefined ? undefined : redactGatewayError(error);
      },
      listCredentials,
      getProviderAuthStatus(provider) {
        return provider === expectedProvider ? getProviderAuthStatus(provider) : { configured: false };
      },
      stream(model, context, options) {
        return guardedStream(stream, model, context, options);
      },
      complete(model, context, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return complete(currentModel(model), context, compatGatewayRuntimeBinding.decorate(normalized));
      },
      streamSimple(model, context, options) {
        return guardedStream(streamSimple, model, context, options);
      },
      completeSimple(model, context, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return completeSimple(currentModel(model), context, compatGatewayRuntimeBinding.decorate(normalized));
      },
      fetchDeferred(model, handle, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return fetchDeferred(currentModel(model), handle, compatGatewayRuntimeBinding.decorate(normalized));
      },
      cancelDeferred(model, handle, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return cancelDeferred(currentModel(model), handle, compatGatewayRuntimeBinding.decorate(normalized));
      },
      registerProvider(provider, configuration) {
        const registration = assertProviderConfiguration(provider, configuration);
        if (gatewayBaseUrl && gatewayBaseUrl !== registration.baseUrl) {
          throw new Error('Enterprise gateway base URL cannot change after registration');
        }
        if (gatewayApiKey && gatewayApiKey !== registration.configuration.apiKey) {
          throw new Error('Enterprise gateway credential cannot change after registration');
        }
        const result = registerProvider(provider, registration.configuration);
        gatewayBaseUrl = registration.baseUrl;
        gatewayApiKey = registration.configuration.apiKey;
        compatGatewayRuntimeBinding.setApiKey(gatewayApiKey);
        return result;
      },
      registerNativeProvider() {
        throw new Error('Pi native provider registration is restricted to the enterprise gateway');
      },
      unregisterProvider() {
        throw new Error('Pi provider removal is restricted to the enterprise gateway');
      },
      setRuntimeApiKey(provider, key) {
        if (provider !== expectedProvider) {
          throw new Error('Pi runtime credentials are restricted to the enterprise gateway');
        }
        if (typeof gatewayApiKey !== 'string' || key !== gatewayApiKey) {
          throw new Error('Enterprise gateway credential overrides are disabled');
        }
        return setRuntimeApiKey(provider, key).then(() => {
          compatGatewayRuntimeBinding.setApiKey(key);
        });
      },
      login(provider, type, interaction) {
        if (provider !== expectedProvider) throw new Error('Pi provider login is restricted to the enterprise gateway');
        throw new Error('Enterprise gateway login is managed by WorkDude authentication');
      },
      logout(provider, options) {
        if (provider !== expectedProvider) throw new Error('Pi provider logout is restricted to the enterprise gateway');
        return logout(provider, options);
      },
    };
    const trustedInternalFacade = Object.freeze({
      ...facade,
      stream(model, context, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return stream(currentModel(model), context, compatGatewayRuntimeBinding.decorate(normalized));
      },
      streamSimple(model, context, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return streamSimple(currentModel(model), context, compatGatewayRuntimeBinding.decorate(normalized));
      },
      complete(model, context, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return complete(currentModel(model), context, compatGatewayRuntimeBinding.decorate(normalized));
      },
      completeSimple(model, context, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return completeSimple(currentModel(model), context, compatGatewayRuntimeBinding.decorate(normalized));
      },
      fetchDeferred(model, handle, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return fetchDeferred(currentModel(model), handle, compatGatewayRuntimeBinding.decorate(normalized));
      },
      cancelDeferred(model, handle, options) {
        const normalized = wrapTransformHeaders(normalizeRequestOptions(options));
        assertRequestOptions(normalized);
        return cancelDeferred(currentModel(model), handle, compatGatewayRuntimeBinding.decorate(normalized));
      },
    });
    const frozenFacade = Object.freeze(facade);
    gatewayFacades.add(frozenFacade);
    gatewayFacadeRecords.set(frozenFacade, Object.freeze({ currentModel, trustedInternalFacade }));
    return frozenFacade;
  },
});

export async function createAgentSessionServices(options) {
  const input = snapshotDataRecord(
    options,
    ['cwd', 'agentDir', 'modelRuntime', 'resourceLoaderOptions'],
    'Pi Agent service options',
  );
  const modelRuntime = input.modelRuntime;
  const runtimeRecord = gatewayFacadeRecords.get(modelRuntime);
  if (!gatewayFacades.has(modelRuntime) || !runtimeRecord) {
    throw new Error('Pi Agent services require the gateway-only ModelRuntime facade');
  }
  if (typeof input.cwd !== 'string' || !input.cwd || typeof input.agentDir !== 'string' || !input.agentDir) {
    throw new Error('Pi Agent service paths are invalid');
  }
  const rawServices = await createPiAgentSessionServices({
    cwd: input.cwd,
    agentDir: input.agentDir,
    modelRuntime: runtimeRecord.trustedInternalFacade,
    resourceLoaderOptions: safeResourceLoaderOptions(input.resourceLoaderOptions, input.cwd, input.agentDir),
  });
  const safeServices = Object.freeze({
    cwd: rawServices.cwd,
    agentDir: rawServices.agentDir,
    modelRuntime,
    settingsManager: rawServices.settingsManager,
    getSkills() {
      return Object.freeze(rawServices.resourceLoader.getSkills().skills.map(({ name, filePath }) =>
        Object.freeze({ name, filePath }),
      ));
    },
    diagnostics: safeDiagnostics(rawServices.diagnostics),
  });
  const record = Object.freeze({
    rawServices,
    safeServices,
    modelRuntime,
    currentModel: runtimeRecord.currentModel,
  });
  gatewayServiceRecords.set(safeServices, record);
  safeServicesByRaw.set(rawServices, safeServices);
  return safeServices;
}

function safeSessionFacade(rawSession, safeServices) {
  const existing = safeSessionsByRaw.get(rawSession);
  if (existing) return existing;
  const facade = Object.freeze({
    sessionManager: rawSession.sessionManager,
    subscribe: rawSession.subscribe.bind(rawSession),
    afterToolTurn(check) {
      if (typeof check !== 'function') throw new Error('Pi delivery check must be a function');
      return rawSession.agent.subscribe(async (event, signal) => {
        if (event.type !== 'turn_end' || !event.toolResults.length ||
            !['stop', 'toolUse'].includes(event.message.stopReason)) return;
        signal.throwIfAborted();
        const message = await check(signal);
        signal.throwIfAborted();
        if (message === undefined) return;
        if (typeof message !== 'string' || !message.trim() || message.length > 100000)
          throw new Error('Pi host delivery text is invalid');
        await rawSession.steer(message);
      });
    },
    beforeNaturalCompletion(check) {
      if (typeof check !== 'function') throw new Error('Pi completion check must be a function');
      return rawSession.agent.subscribe(async (event, signal) => {
        if (event.type !== 'turn_end' || event.message.role !== 'assistant' ||
            event.message.stopReason !== 'stop' || event.toolResults.length ||
            event.message.content.some((part) => part.type === 'toolCall')) return;
        // Pi may still have host-delivered work queued after this assistant turn.
        // Let its native loop consume that work before asking the host to settle.
        if (rawSession.agent.hasQueuedMessages()) return;
        signal.throwIfAborted();
        const correction = await check(signal);
        signal.throwIfAborted();
        if (correction === undefined) return;
        if (typeof correction !== 'string' || !correction.trim() || correction.length > 100000) {
          throw new Error('Pi completion correction is invalid');
        }
        await rawSession.followUp(correction);
      });
    },
    abort: rawSession.abort.bind(rawSession),
    async steer(text) {
      if (typeof text !== 'string' || !text.trim() || text.length > 100000) {
        throw new Error('Pi host steering text is invalid');
      }
      await rawSession.steer(text);
    },
    prompt: rawSession.prompt.bind(rawSession),
  });
  gatewaySessionRecords.set(
    facade,
    Object.freeze({ rawSession, safeSession: facade, safeServices }),
  );
  safeSessionsByRaw.set(rawSession, facade);
  return facade;
}

export async function createAgentSessionFromServices(options) {
  const input = snapshotDataRecord(
    options,
    [
      'services',
      'sessionManager',
      'sessionStartEvent',
      'model',
      'thinkingLevel',
      'scopedModels',
      'tools',
      'excludeTools',
      'noTools',
      'customTools',
    ],
    'Pi Agent session options',
  );
  const serviceRecord = gatewayServiceRecords.get(input.services);
  if (!serviceRecord || !gatewayFacades.has(serviceRecord.modelRuntime)) {
    throw new Error('Pi Agent services require the gateway-only ModelRuntime facade');
  }
  if (!input.sessionManager || typeof input.sessionManager !== 'object') {
    throw new Error('Pi Agent session manager is invalid');
  }
  const rawOptions = {
    services: serviceRecord.rawServices,
    sessionManager: input.sessionManager,
    ...(input.sessionStartEvent === undefined
      ? {}
      : { sessionStartEvent: cloneData(input.sessionStartEvent, 'Pi Agent session start event') }),
    ...(input.model === undefined ? {} : { model: serviceRecord.currentModel(input.model) }),
    ...(input.thinkingLevel === undefined ? {} : { thinkingLevel: input.thinkingLevel }),
    ...(input.scopedModels === undefined
      ? {}
      : {
          scopedModels: snapshotArrayValues(input.scopedModels, 'Pi Agent scoped models').map((entry) => {
            const scoped = snapshotDataRecord(entry, ['model', 'thinkingLevel'], 'Pi Agent scoped model');
            return Object.freeze({
              model: serviceRecord.currentModel(scoped.model),
              ...(scoped.thinkingLevel === undefined ? {} : { thinkingLevel: scoped.thinkingLevel }),
            });
          }),
        }),
    ...(input.tools === undefined ? {} : { tools: snapshotStringArray(input.tools, 'Pi Agent tools') }),
    ...(input.excludeTools === undefined
      ? {}
      : { excludeTools: snapshotStringArray(input.excludeTools, 'Pi Agent excluded tools') }),
    ...(input.noTools === undefined ? {} : { noTools: input.noTools }),
    ...(input.customTools === undefined
      ? {}
      : { customTools: snapshotArrayValues(input.customTools, 'Pi Agent custom tools') }),
  };
  const created = await createPiAgentSessionFromServices(rawOptions);
  const safeSession = safeSessionFacade(created.session, serviceRecord.safeServices);
  return Object.freeze({
    session: safeSession,
    ...(typeof created.modelFallbackMessage === 'string'
      ? { modelFallbackMessage: created.modelFallbackMessage }
      : {}),
  });
}

export async function createAgentSessionRuntime(createRuntime, options) {
  if (typeof createRuntime !== 'function') throw new Error('Pi Agent runtime factory is invalid');
  const input = snapshotDataRecord(
    options,
    ['cwd', 'agentDir', 'sessionManager', 'sessionStartEvent'],
    'Pi Agent runtime options',
  );
  if (
    typeof input.cwd !== 'string' ||
    !input.cwd ||
    typeof input.agentDir !== 'string' ||
    !input.agentDir ||
    !input.sessionManager ||
    typeof input.sessionManager !== 'object'
  ) {
    throw new Error('Pi Agent runtime options are invalid');
  }
  const wrappedFactory = async (factoryOptions) => {
    const result = await createRuntime(
      Object.freeze({
        cwd: factoryOptions.cwd,
        agentDir: factoryOptions.agentDir,
        sessionManager: factoryOptions.sessionManager,
        ...(factoryOptions.sessionStartEvent === undefined
          ? {}
          : { sessionStartEvent: cloneData(factoryOptions.sessionStartEvent, 'Pi Agent session start event') }),
      }),
    );
    const snapshot = snapshotDataRecord(
      result,
      ['session', 'services', 'diagnostics', 'modelFallbackMessage', 'extensionsResult'],
      'Pi Agent runtime factory result',
    );
    const sessionRecord = gatewaySessionRecords.get(snapshot.session);
    const serviceRecord = gatewayServiceRecords.get(snapshot.services);
    if (
      !sessionRecord ||
      !serviceRecord ||
      sessionRecord.safeServices !== snapshot.services ||
      serviceRecord.safeServices !== snapshot.services
    ) {
      throw new Error('Pi Agent runtime factory must return gateway-issued session tokens');
    }
    return {
      session: sessionRecord.rawSession,
      services: serviceRecord.rawServices,
      diagnostics: safeDiagnostics(snapshot.diagnostics ?? snapshot.services.diagnostics),
      ...(typeof snapshot.modelFallbackMessage === 'string'
        ? { modelFallbackMessage: snapshot.modelFallbackMessage }
        : {}),
    };
  };
  const rawRuntime = await createPiAgentSessionRuntime(wrappedFactory, {
    cwd: input.cwd,
    agentDir: input.agentDir,
    sessionManager: input.sessionManager,
    ...(input.sessionStartEvent === undefined
      ? {}
      : { sessionStartEvent: cloneData(input.sessionStartEvent, 'Pi Agent session start event') }),
  });
  return Object.freeze({
    get session() {
      const session = safeSessionsByRaw.get(rawRuntime.session);
      if (!session) throw new Error('Pi Agent runtime session is outside the gateway boundary');
      return session;
    },
    get services() {
      const services = safeServicesByRaw.get(rawRuntime.services);
      if (!services) throw new Error('Pi Agent runtime services are outside the gateway boundary');
      return services;
    },
    get diagnostics() {
      return safeDiagnostics(rawRuntime.diagnostics);
    },
    get modelFallbackMessage() {
      return rawRuntime.modelFallbackMessage;
    },
    get cwd() {
      return rawRuntime.cwd;
    },
    dispose: rawRuntime.dispose.bind(rawRuntime),
  });
}
`;
}

function gatewayBoundaryPlugin(piRoot, compatSource, providersSource) {
  return {
    name: 'workdude-pi-gateway-boundary',
    setup(build) {
      build.onResolve({ filter: /^(?:@earendil-works|@mariozechner)\/pi-ai\/compat$/ }, () => ({
        path: 'compat',
        namespace: 'workdude-gateway',
        sideEffects: false,
      }));
      build.onResolve({ filter: /^(?:@earendil-works|@mariozechner)\/pi-ai\/providers\/all$/ }, () => ({
        path: 'providers',
        namespace: 'workdude-gateway',
        sideEffects: false,
      }));
      build.onLoad({ filter: /.*/, namespace: 'workdude-gateway' }, ({ path }) => ({
        contents: path === 'compat' ? compatSource : providersSource,
        loader: 'js',
        resolveDir: piRoot,
      }));
    },
  };
}

/** Package Pi's unchanged Photon dependency into the immutable single-file runtime.
 * Its Node entry reads WASM relative to __dirname, which no longer exists after
 * bundling. Only that asset-loading statement is translated; image processing
 * remains the official Pi/Photon implementation and both inputs stay source locked.
 */
function gatewayPhotonAssetPlugin(reader) {
  const entryName = 'node_modules/@silvia-odwyer/photon-node/photon_rs.js';
  const wasmName = 'node_modules/@silvia-odwyer/photon-node/photon_rs_bg.wasm';
  return {
    name: 'workdude-pi-photon-asset',
    setup(build) {
      build.onLoad({ filter: /photon-node[\\/]photon_rs\.js$/ }, async ({ path }) => {
        if (!samePath(resolve(path), resolve(reader.root, entryName)))
          throw new Error('Photon entry is outside the pinned Pi build');
        const source = (await readPiBuildCacheArtifact(reader, entryName)).toString('utf8');
        const assetRead =
          "const path = require('path').join(__dirname, 'photon_rs_bg.wasm');\nconst bytes = require('fs').readFileSync(path);";
        if (source.split(assetRead).length !== 2)
          throw new Error('Pinned Photon asset loader changed; review the bundling adapter');
        return {
          contents: source.replace(assetRead, "const bytes = require('./photon_rs_bg.wasm');"),
          loader: 'js',
          resolveDir: resolve(reader.root, 'node_modules/@silvia-odwyer/photon-node'),
        };
      });
      build.onLoad({ filter: /photon-node[\\/]photon_rs_bg\.wasm$/ }, async ({ path }) => {
        if (!samePath(resolve(path), resolve(reader.root, wasmName)))
          throw new Error('Photon WASM is outside the pinned Pi build');
        const bytes = await readPiBuildCacheArtifact(reader, wasmName);
        // Hex keeps binary bytes from accidentally resembling credential tokens
        // in source scanners. The decoded WASM remains the pinned official asset;
        // no scanner rule or allowlist is weakened for this dependency.
        return {
          contents: `module.exports = new Uint8Array(Buffer.from(${JSON.stringify(bytes.toString('hex'))}, 'hex'));`,
          loader: 'js',
        };
      });
    },
  };
}

function normalizeInputPath(repositoryRoot, piRoot, path) {
  const absolute = resolve(repositoryRoot, path);
  if (!inside(piRoot, absolute)) return undefined;
  const name = relative(piRoot, absolute).split(sep).join('/');
  return safeArtifactPath(name) ? name : undefined;
}

async function lockedInputArtifacts(repositoryRoot, reader, sourceLock, metafile) {
  const output = Object.values(metafile.outputs)[0];
  const inputs = {};
  for (const [path, details] of Object.entries(output.inputs ?? {})) {
    if (
      !details.bytesInOutput ||
      path.startsWith('workdude:') ||
      path.replaceAll('\\', '/').endsWith('/workdude-pi-gateway-entry.mjs') ||
      path === 'workdude-pi-gateway-entry.mjs'
    ) {
      continue;
    }
    const name = normalizeInputPath(repositoryRoot, reader.root, path);
    if (!name) continue;
    const expected = sourceLock.artifacts[name];
    if (!/^[a-f0-9]{64}$/u.test(String(expected))) {
      throw new Error(`Pi gateway bundle input is not source locked: ${name}`);
    }
    const actual = sha256(await readPiBuildCacheArtifact(reader, name));
    if (actual !== expected) throw new Error(`Pi gateway bundle input changed after cache pinning: ${name}`);
    inputs[name] = expected;
  }
  return Object.fromEntries(Object.entries(inputs).sort(([left], [right]) => left.localeCompare(right)));
}

async function existingGeneration(path, manifestContent, bundleHash) {
  try {
    const directoryPath = resolve(path);
    const directoryEntry = await lstat(directoryPath, { bigint: true });
    assertPlainDirectory(directoryEntry, 'The existing Pi gateway runtime generation');
    const canonicalDirectory = await realpath(directoryPath);
    if (!samePath(canonicalDirectory, directoryPath)) {
      throw new Error('generation directory is not a plain directory');
    }

    const expectedNames = ['manifest.json', 'runtime.mjs'];
    const children = await readdir(directoryPath, { withFileTypes: true });
    if (
      children.length !== expectedNames.length ||
      children.some(
        (child) => !child.isFile() || child.isSymbolicLink() || !expectedNames.includes(child.name),
      )
    ) {
      throw new Error('generation must contain exactly manifest.json and runtime.mjs as plain files');
    }
    const [manifestFile, bundleFile] = await Promise.all([
      readStableGatewayFile(resolve(directoryPath, 'manifest.json'), {
        repositoryRoot: directoryPath,
        trustedRoot: directoryPath,
        label: 'The existing Pi gateway runtime manifest',
      }),
      readStableGatewayFile(resolve(directoryPath, 'runtime.mjs'), {
        repositoryRoot: directoryPath,
        trustedRoot: directoryPath,
        label: 'The existing Pi gateway runtime bundle',
      }),
    ]);
    const finalChildren = await readdir(directoryPath, { withFileTypes: true });
    if (
      finalChildren.length !== expectedNames.length ||
      finalChildren.some(
        (child) => !child.isFile() || child.isSymbolicLink() || !expectedNames.includes(child.name),
      )
    ) {
      throw new Error('generation changed while its exact files were read');
    }
    const finalDirectoryEntry = await lstat(directoryPath, { bigint: true });
    assertPlainDirectory(finalDirectoryEntry, 'The existing Pi gateway runtime generation');
    if (!sameStableDirectory(directoryEntry, finalDirectoryEntry)) {
      throw new Error('generation directory changed while its files were read');
    }
    return (
      manifestFile.content.toString('utf8') === manifestContent && sha256(bundleFile.content) === bundleHash
    );
  } catch (error) {
    if (error && typeof error === 'object' && error.code === 'ENOENT') return false;
    const reason = error instanceof Error ? `: ${error.message}` : '';
    throw new Error(`Existing Pi gateway runtime generation is invalid${reason}`, { cause: error });
  }
}

export async function buildPiGatewayRuntime({ repositoryRoot = process.cwd() } = {}) {
  const root = resolve(repositoryRoot);
  const esbuild = await import('esbuild');
  const reader = await pinPublishedPiBuildCache({ repositoryRoot: root });
  const trustedSource = reader.trustedPiSource;
  const sourceLock = JSON.parse(reader.sourceLockContent);
  const normalizedTrusted = normalizePiSourceLock(trustedSource);
  if (
    sourceLock.schemaVersion !== 1 ||
    JSON.stringify(normalizePiSourceLock(sourceLock.source)) !== JSON.stringify(normalizedTrusted) ||
    !sourceLock.artifacts ||
    typeof sourceLock.artifacts !== 'object' ||
    Array.isArray(sourceLock.artifacts)
  ) {
    throw new Error('Pi gateway runtime source lock is invalid');
  }

  const compatSource = gatewayCompatSource(reader.root);
  const providersSource = gatewayProvidersSource();
  const entrySource = gatewayEntrySource(reader.root);
  const result = await esbuild.build({
    absWorkingDir: root,
    stdin: {
      contents: entrySource,
      resolveDir: reader.root,
      sourcefile: 'workdude-pi-gateway-entry.mjs',
      loader: 'js',
    },
    bundle: true,
    write: false,
    platform: 'node',
    format: 'esm',
    target: 'node24',
    treeShaking: true,
    sourcemap: false,
    legalComments: 'none',
    metafile: true,
    logLevel: 'silent',
    banner: {
      js: `import { createRequire as __workdudeCreateRequire } from 'node:module';
const require = __workdudeCreateRequire(import.meta.url);
const WORKDUDE_PI_GATEWAY_BUNDLE_POLICY = Object.freeze(${JSON.stringify({ provider: gatewayProvider, api: gatewayApi, builtinProviders: false })});`,
    },
    plugins: [
      gatewayBoundaryPlugin(reader.root, compatSource, providersSource),
      gatewayPhotonAssetPlugin(reader),
    ],
  });
  if (result.outputFiles.length !== 1) throw new Error('Pi gateway runtime build emitted multiple files');
  const outputMetadata = Object.values(result.metafile.outputs);
  if (outputMetadata.length !== 1) throw new Error('Pi gateway runtime metadata emitted multiple files');
  const actualExports = [...(outputMetadata[0].exports ?? [])].sort();
  if (JSON.stringify(actualExports) !== JSON.stringify([...requiredExports].sort())) {
    throw new Error('Pi gateway runtime build emitted exports outside the product boundary');
  }
  const externalImports = [
    ...new Set((outputMetadata[0].imports ?? []).filter(({ external }) => external).map(({ path }) => path)),
  ].sort();
  const nonNodeExternalImports = externalImports.filter((path) => !isNodeBuiltin(path));
  if (nonNodeExternalImports.length > 0) {
    throw new Error(
      `Pi gateway runtime build retained non-Node external dependencies: ${nonNodeExternalImports.join(', ')}`,
    );
  }
  const bundle = result.outputFiles[0].contents;
  const bundleSha256 = sha256(bundle);
  const inputs = await lockedInputArtifacts(root, reader, sourceLock, result.metafile);
  const manifest = {
    schemaVersion: 1,
    source: {
      piGeneration: reader.generation,
      piManifestSha256: reader.manifestSha256,
      sourceLockSha256: reader.sourceLockSha256,
      piSourceManifestSha256: reader.piSourceManifestSha256,
    },
    policy: {
      provider: gatewayProvider,
      api: gatewayApi,
      builtinProviders: false,
      allowedRequestPath: 'chat/completions',
    },
    bundle: { path: 'runtime.mjs', sha256: bundleSha256, bytes: bundle.byteLength },
    virtualModules: {
      entrySha256: sha256(entrySource),
      compatSha256: sha256(compatSource),
      providersSha256: sha256(providersSource),
    },
    inputs,
    externalImports,
    exports: requiredExports,
  };
  const manifestContent = jsonLine(manifest);
  const manifestSha256 = sha256(manifestContent);
  const generation = `pi-gateway-runtime-${manifestSha256}`;
  const layout = await resolveSafePiCacheLayout({ repositoryRoot: root });
  const generationRoot = resolve(layout.cacheParent, generation);
  const lock = await acquirePiBuildCacheLock(layout);
  try {
    if (!(await existingGeneration(generationRoot, manifestContent, bundleSha256))) {
      const stage = resolve(layout.cacheParent, `pi-gateway-runtime-stage-${randomUUID()}`);
      await mkdir(stage);
      try {
        await Promise.all([
          writeFile(resolve(stage, 'runtime.mjs'), bundle, { flag: 'wx' }),
          writeFile(resolve(stage, 'manifest.json'), manifestContent, { flag: 'wx' }),
        ]);
        await rename(stage, generationRoot);
      } catch (error) {
        await rm(stage, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }).catch(
          () => undefined,
        );
        throw error;
      }
    }
    const pointerPath = resolve(layout.cacheParent, gatewayPointerName);
    const temporaryPointer = `${pointerPath}.${randomUUID()}.tmp`;
    await writeFile(
      temporaryPointer,
      jsonLine({
        schemaVersion: 1,
        generation,
        manifestSha256,
        bundleSha256,
        sourceLockSha256: reader.sourceLockSha256,
        piSourceManifestSha256: reader.piSourceManifestSha256,
      }),
      { flag: 'wx' },
    );
    await renameGatewayPointerWithRetry(rename, temporaryPointer, pointerPath);
  } finally {
    await lock.release();
  }
  return Object.freeze({ generation, root: generationRoot, manifest, manifestSha256, bundleSha256 });
}

function validateGatewayPointer(pointer) {
  if (
    !exactKeys(pointer, [
      'schemaVersion',
      'generation',
      'manifestSha256',
      'bundleSha256',
      'sourceLockSha256',
      'piSourceManifestSha256',
    ]) ||
    pointer.schemaVersion !== 1 ||
    typeof pointer.generation !== 'string' ||
    !gatewayGenerationPattern.test(pointer.generation) ||
    pointer.generation !== `pi-gateway-runtime-${pointer.manifestSha256}` ||
    !/^[a-f0-9]{64}$/u.test(String(pointer.manifestSha256)) ||
    !/^[a-f0-9]{64}$/u.test(String(pointer.bundleSha256)) ||
    !/^[a-f0-9]{64}$/u.test(String(pointer.sourceLockSha256)) ||
    !/^[a-f0-9]{64}$/u.test(String(pointer.piSourceManifestSha256))
  ) {
    throw new Error('Pi gateway runtime pointer is invalid');
  }
  return pointer;
}

async function readPiGatewayRuntimeSnapshotOnce({ repositoryRoot = process.cwd() } = {}) {
  const requestedRoot = resolve(repositoryRoot);
  assertPlainDirectory(
    await lstat(requestedRoot, { bigint: true }),
    'The Pi gateway runtime repository root',
  );
  const root = await realpath(requestedRoot);
  const cache = await resolvePlainGatewayDirectory(resolve(root, '.cache'), {
    trustedRoot: root,
    label: 'The Pi gateway runtime cache',
  });
  const [pointerFile, trustedFile] = await Promise.all([
    readStableGatewayFile(resolve(cache.path, gatewayPointerName), {
      repositoryRoot: root,
      trustedRoot: cache.path,
      label: 'The Pi gateway runtime pointer',
    }),
    readStableGatewayFile(resolve(root, 'pi-source.lock.json'), {
      repositoryRoot: root,
      trustedRoot: root,
      label: 'The trusted Pi source lock',
    }),
  ]);
  const pointerContent = pointerFile.content.toString('utf8');
  const trustedContent = trustedFile.content.toString('utf8');
  const pointer = validateGatewayPointer(JSON.parse(pointerContent));
  const trusted = normalizePiSourceLock(JSON.parse(trustedContent));
  if (trusted.manifestSha256 !== pointer.piSourceManifestSha256) {
    throw new Error('Pi gateway runtime pointer does not match the trusted Pi source');
  }
  const generationPath = resolve(cache.path, pointer.generation);
  if (relative(cache.path, generationPath) !== pointer.generation) {
    throw new Error('Pi gateway runtime generation pointer escapes the trusted cache');
  }
  const generation = await resolvePlainGatewayDirectory(generationPath, {
    trustedRoot: cache.path,
    label: 'The Pi gateway runtime generation',
  });
  const generationChildren = await readdir(generation.path, { withFileTypes: true });
  if (
    generationChildren.length !== 2 ||
    generationChildren.some(
      (entry) =>
        !entry.isFile() ||
        entry.isSymbolicLink() ||
        (entry.name !== 'manifest.json' && entry.name !== 'runtime.mjs'),
    )
  ) {
    throw new Error('Pi gateway runtime generation must contain exactly its manifest and bundle');
  }
  const [manifestFile, bundleFile] = await Promise.all([
    readStableGatewayFile(resolve(generation.path, 'manifest.json'), {
      repositoryRoot: root,
      trustedRoot: generation.path,
      label: 'The Pi gateway runtime manifest',
    }),
    readStableGatewayFile(resolve(generation.path, 'runtime.mjs'), {
      repositoryRoot: root,
      trustedRoot: generation.path,
      label: 'The Pi gateway runtime bundle',
    }),
  ]);
  const manifestContent = manifestFile.content.toString('utf8');
  const bundle = bundleFile.content;
  if (sha256(manifestContent) !== pointer.manifestSha256 || sha256(bundle) !== pointer.bundleSha256) {
    throw new Error('Pi gateway runtime generation does not match its pointer');
  }
  if (!hasGatewayOnlyPiRuntimeBoundary(bundle.toString('utf8'))) {
    throw new Error('Pi gateway runtime executable boundary is invalid');
  }
  const manifest = JSON.parse(manifestContent);
  if (
    !exactKeys(manifest, [
      'schemaVersion',
      'source',
      'policy',
      'bundle',
      'virtualModules',
      'inputs',
      'externalImports',
      'exports',
    ]) ||
    manifest.schemaVersion !== 1 ||
    !exactKeys(manifest.source, [
      'piGeneration',
      'piManifestSha256',
      'sourceLockSha256',
      'piSourceManifestSha256',
    ]) ||
    !/^pi-build-generation-[a-f0-9]{64}$/u.test(String(manifest.source?.piGeneration)) ||
    !/^[a-f0-9]{64}$/u.test(String(manifest.source?.piManifestSha256)) ||
    manifest.source?.piManifestSha256 !==
      manifest.source?.piGeneration.slice('pi-build-generation-'.length) ||
    manifest.source?.sourceLockSha256 !== pointer.sourceLockSha256 ||
    manifest.source?.piSourceManifestSha256 !== pointer.piSourceManifestSha256 ||
    !exactKeys(manifest.policy, ['provider', 'api', 'builtinProviders', 'allowedRequestPath']) ||
    manifest.bundle?.sha256 !== pointer.bundleSha256 ||
    !exactKeys(manifest.bundle, ['path', 'sha256', 'bytes']) ||
    manifest.bundle?.path !== 'runtime.mjs' ||
    manifest.bundle?.bytes !== bundle.byteLength ||
    manifest.policy?.provider !== gatewayProvider ||
    manifest.policy?.api !== gatewayApi ||
    manifest.policy?.builtinProviders !== false ||
    manifest.policy?.allowedRequestPath !== 'chat/completions' ||
    !exactKeys(manifest.virtualModules, ['entrySha256', 'compatSha256', 'providersSha256']) ||
    Object.values(manifest.virtualModules).some((hash) => !/^[a-f0-9]{64}$/u.test(String(hash))) ||
    !plainObject(manifest.inputs) ||
    Object.keys(manifest.inputs).length === 0 ||
    Object.entries(manifest.inputs).some(
      ([path, hash]) =>
        !safeArtifactPath(path) ||
        !/^(?:node_modules|packages)\//u.test(path) ||
        !/^[a-f0-9]{64}$/u.test(String(hash)),
    ) ||
    !Array.isArray(manifest.externalImports) ||
    manifest.externalImports.some((path) => typeof path !== 'string' || !isNodeBuiltin(path)) ||
    JSON.stringify([...manifest.externalImports].sort()) !== JSON.stringify(manifest.externalImports) ||
    !Array.isArray(manifest.exports) ||
    JSON.stringify(manifest.exports) !== JSON.stringify(requiredExports)
  ) {
    throw new Error('Pi gateway runtime manifest is invalid or incomplete');
  }
  const finalGenerationChildren = await readdir(generation.path, { withFileTypes: true });
  if (
    finalGenerationChildren.length !== 2 ||
    finalGenerationChildren.some(
      (entry) =>
        !entry.isFile() ||
        entry.isSymbolicLink() ||
        (entry.name !== 'manifest.json' && entry.name !== 'runtime.mjs'),
    )
  ) {
    throw new Error('Pi gateway runtime generation changed while its exact contents were read');
  }
  await Promise.all([
    assertStableGatewayFile(pointerFile),
    assertStableGatewayFile(trustedFile),
    assertStableGatewayFile(manifestFile),
    assertStableGatewayFile(bundleFile),
    assertStableGatewayDirectory(cache),
    assertStableGatewayDirectory(generation),
  ]);
  const reader = Object.freeze({
    generation: pointer.generation,
    manifest,
    manifestSha256: pointer.manifestSha256,
    bundleSha256: pointer.bundleSha256,
    root: generation.path,
    bundlePath: bundleFile.path,
  });
  return Object.freeze({
    repositoryRoot: root,
    reader,
    pointerFile,
    trustedFile,
    manifestFile,
    bundleFile,
  });
}

function isRetryableGatewaySnapshotError(error) {
  return (
    error instanceof Error &&
    /^The Pi gateway runtime pointer replaced (?:before it could be read|while it was read|while the snapshot was validated)$/u.test(
      error.message,
    )
  );
}

export async function readPiGatewayRuntimeSnapshot(options = {}) {
  let lastError;
  for (let attempt = 0; attempt < GATEWAY_SNAPSHOT_RETRY_LIMIT; attempt += 1) {
    try {
      return await readPiGatewayRuntimeSnapshotOnce(options);
    } catch (error) {
      if (!isRetryableGatewaySnapshotError(error)) throw error;
      lastError = error;
      if (attempt + 1 < GATEWAY_SNAPSHOT_RETRY_LIMIT) {
        await delay(GATEWAY_SNAPSHOT_RETRY_DELAY_MS * (attempt + 1));
      }
    }
  }
  throw new Error('The Pi gateway runtime pointer changed too frequently to read safely', {
    cause: lastError,
  });
}

export async function pinPiGatewayRuntime(options = {}) {
  return (await readPiGatewayRuntimeSnapshot(options)).reader;
}

export async function exportPiGatewayRuntime({ repositoryRoot = process.cwd(), destinationRoot }) {
  const snapshot = await readPiGatewayRuntimeSnapshot({ repositoryRoot });
  const root = snapshot.repositoryRoot;
  const requestedDestination = resolve(destinationRoot);
  const requestedParent = resolve(requestedDestination, '..');
  const parentEntry = await lstat(requestedParent, { bigint: true });
  assertPlainDirectory(parentEntry, 'The Pi gateway runtime export parent');
  const destinationParent = await realpath(requestedParent);
  const destination = resolve(destinationParent, basename(requestedDestination));
  if (
    !samePath(destinationParent, requestedParent) ||
    !samePath(destination, requestedDestination) ||
    samePath(destination, root) ||
    inside(resolve(root, 'pi'), destination) ||
    inside(resolve(root, '.cache'), destination)
  ) {
    throw new Error('Pi gateway runtime export destination is unsafe');
  }
  try {
    await lstat(destination);
    throw new Error('Pi gateway runtime export destination already exists');
  } catch (error) {
    if (!error || typeof error !== 'object' || error.code !== 'ENOENT') throw error;
  }
  const reader = snapshot.reader;
  const cacheRoot = resolve(destination, '.cache');
  const generationRoot = resolve(cacheRoot, reader.generation);
  await mkdir(destination);
  await mkdir(cacheRoot);
  await mkdir(generationRoot);
  await Promise.all([
    writeFile(resolve(cacheRoot, gatewayPointerName), snapshot.pointerFile.content, { flag: 'wx' }),
    writeFile(resolve(destination, 'pi-source.lock.json'), snapshot.trustedFile.content, { flag: 'wx' }),
    writeFile(resolve(generationRoot, 'manifest.json'), snapshot.manifestFile.content, { flag: 'wx' }),
    writeFile(resolve(generationRoot, 'runtime.mjs'), snapshot.bundleFile.content, { flag: 'wx' }),
  ]);
  const exported = await pinPiGatewayRuntime({ repositoryRoot: destination });
  if (
    exported.generation !== reader.generation ||
    exported.manifestSha256 !== reader.manifestSha256 ||
    exported.bundleSha256 !== reader.bundleSha256
  ) {
    throw new Error('Pi gateway runtime export does not match its trusted source snapshot');
  }
  return Object.freeze({ destination, generation: reader.generation });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const result = await buildPiGatewayRuntime();
  const exportIndex = process.argv.indexOf('--export');
  if (exportIndex >= 0 && !process.argv[exportIndex + 1]) {
    throw new Error('--export requires a destination directory');
  }
  const exported =
    exportIndex >= 0
      ? await exportPiGatewayRuntime({ destinationRoot: process.argv[exportIndex + 1] })
      : undefined;
  process.stdout.write(
    `${JSON.stringify({
      generation: result.generation,
      bundleSha256: result.bundleSha256,
      inputCount: Object.keys(result.manifest.inputs).length,
      bytes: result.manifest.bundle.bytes,
      ...(exported ? { exportRoot: exported.destination } : {}),
    })}\n`,
  );
}
