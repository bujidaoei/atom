import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';

import type { SandboxClient } from '../../product-contracts/src/index.ts';
import type { V3WorkflowNode } from '../../product-contracts/src/v3.ts';

const MAX_HTTP_RESPONSE_BYTES = 1024 * 1024;
const MAX_REDIRECTS = 4;

type ActionNode = Extract<V3WorkflowNode, { type: 'action' }>;

export interface V3WorkflowActionExecutionInput {
  node: ActionNode;
  args: unknown;
  target: string;
  executionKey: string;
}

export interface V3WorkflowActionExecutorOptions {
  workspaceId: string;
  sandbox?: SandboxClient;
  fetch?: typeof fetch;
  resolveHost?: (hostname: string) => Promise<string[]>;
  signal?: AbortSignal;
  timeoutMs?: number;
  maxResponseBytes?: number;
}

function privateIpv4(address: string): boolean {
  const octets = address.split('.').map(Number);
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) {
    return true;
  }
  const [a, b] = octets as [number, number, number, number];
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 198 && (b === 18 || b === 19)) ||
    a >= 224
  );
}

function privateAddress(address: string): boolean {
  const normalized = address.toLowerCase().split('%')[0]!;
  if (isIP(normalized) === 4) return privateIpv4(normalized);
  if (isIP(normalized) !== 6) return true;
  if (normalized.startsWith('::ffff:')) return privateIpv4(normalized.slice(7));
  return (
    normalized === '::' ||
    normalized === '::1' ||
    normalized.startsWith('fc') ||
    normalized.startsWith('fd') ||
    /^fe[89ab]/u.test(normalized)
  );
}

async function publicActionUrl(
  value: string,
  resolveHost: (hostname: string) => Promise<string[]>,
): Promise<URL> {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error('HTTP Action URL is invalid');
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.port) {
    throw new Error('HTTP Action must use a credential-free HTTPS URL on the default port');
  }
  const hostname = url.hostname.toLowerCase();
  if (
    hostname === 'localhost' ||
    hostname.endsWith('.localhost') ||
    hostname.endsWith('.local') ||
    hostname.endsWith('.internal')
  ) {
    throw new Error('HTTP Action host is not public');
  }
  const addresses = isIP(hostname) ? [hostname] : await resolveHost(hostname);
  if (!addresses.length || addresses.some(privateAddress)) {
    throw new Error('HTTP Action resolved to a non-public address');
  }
  return url;
}

async function readBoundedText(response: Response, maxBytes: number): Promise<string> {
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new Error(`HTTP Action response exceeds the ${maxBytes} byte limit`);
  }
  if (!response.body) return '';
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      throw new Error(`HTTP Action response exceeds the ${maxBytes} byte limit`);
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

function queryUrl(url: URL, args: unknown): URL {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return url;
  for (const [key, value] of Object.entries(args as Record<string, unknown>)) {
    if (value === undefined) continue;
    url.searchParams.set(key, typeof value === 'string' ? value : JSON.stringify(value));
  }
  return url;
}

async function executeHttpAction(
  input: V3WorkflowActionExecutionInput,
  options: V3WorkflowActionExecutorOptions,
): Promise<unknown> {
  const node = input.node;
  if (node.actionType !== 'http') throw new Error('HTTP Action configuration is invalid');
  const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  const method = node.method ?? 'GET';
  const resolveHost =
    options.resolveHost ??
    (async (hostname: string) =>
      (await lookup(hostname, { all: true, verbatim: true })).map(({ address }) => address));
  let url = await publicActionUrl(input.target, resolveHost);
  if (method === 'GET') url = queryUrl(url, input.args);
  const timeout = AbortSignal.timeout(options.timeoutMs ?? 30_000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  for (let redirect = 0; redirect <= MAX_REDIRECTS; redirect += 1) {
    const hasBody = method !== 'GET' && input.args !== undefined && input.args !== null;
    const response = await fetcher(url, {
      method,
      redirect: 'manual',
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
      headers: {
        accept: 'application/json,text/plain;q=0.9,*/*;q=0.8',
        ...(hasBody ? { 'content-type': 'application/json' } : {}),
        'user-agent': 'QoderWake-WakerFlow-Action/3',
      },
      ...(hasBody ? { body: JSON.stringify(input.args) } : {}),
      signal,
    });
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get('location');
      if (!location || redirect === MAX_REDIRECTS) throw new Error('HTTP Action redirect is invalid');
      url = await publicActionUrl(new URL(location, url).href, resolveHost);
      continue;
    }
    const bodyText = await readBoundedText(response, options.maxResponseBytes ?? MAX_HTTP_RESPONSE_BYTES);
    if (!response.ok) throw new Error(`HTTP Action returned ${response.status}: ${bodyText.slice(0, 1_000)}`);
    const mediaType = response.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase();
    let body: unknown = bodyText;
    if (mediaType === 'application/json' && bodyText) {
      try {
        body = JSON.parse(bodyText);
      } catch {
        throw new Error('HTTP Action returned invalid JSON');
      }
    }
    return { status: response.status, mediaType: mediaType ?? '', body };
  }
  throw new Error('HTTP Action redirect limit exceeded');
}

function shellArgument(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return `'${(text ?? '').replaceAll("'", "'\\''")}'`;
}

function scriptCommand(command: string, args: unknown): string {
  if (args === undefined || args === null) return command;
  const values = Array.isArray(args) ? args : [args];
  return [command, ...values.map(shellArgument)].join(' ');
}

async function executeScriptAction(
  input: V3WorkflowActionExecutionInput,
  options: V3WorkflowActionExecutorOptions,
): Promise<unknown> {
  const node = input.node;
  if (node.actionType !== 'script') throw new Error('Script Action configuration is invalid');
  if (!options.sandbox) throw new Error(`WakerFlow Script Action requires a sandbox: ${node.actionId}`);
  options.signal?.throwIfAborted();
  const sandboxId = await options.sandbox.create(input.executionKey, options.workspaceId);
  try {
    const result = await options.sandbox.exec(
      sandboxId,
      {
        toolCallId: input.executionKey,
        command: scriptCommand(input.target, input.args),
        timeoutMs: options.timeoutMs ?? 60_000,
      },
      options.signal,
    );
    if (result.exitCode !== 0 || result.timedOut) {
      const detail = [result.stderr, result.stdout].filter(Boolean).join('\n').trim();
      throw new Error(
        result.timedOut
          ? `Script Action timed out${detail ? `: ${detail.slice(0, 1_000)}` : ''}`
          : `Script Action exited with code ${result.exitCode}${detail ? `: ${detail.slice(0, 1_000)}` : ''}`,
      );
    }
    return {
      exitCode: result.exitCode,
      stdout: result.stdout,
      stderr: result.stderr,
      truncated: result.truncated,
    };
  } finally {
    await options.sandbox.destroy(sandboxId);
  }
}

async function executeBuiltinAction(
  input: V3WorkflowActionExecutionInput,
  options: V3WorkflowActionExecutorOptions,
): Promise<unknown> {
  const node = input.node;
  if (node.actionType !== 'builtin') throw new Error('Builtin Action configuration is invalid');
  if (!options.sandbox) throw new Error(`WakerFlow Builtin Action requires a sandbox: ${node.actionId}`);
  options.signal?.throwIfAborted();
  const sandboxId = await options.sandbox.create(input.executionKey, options.workspaceId);
  try {
    // Pi v0.87.1 has no Workflow JavaScript Action primitive. Reuse the existing
    // network-isolated, resource-bounded Action sandbox outside protected Pi.
    const program = [
      'const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;',
      "for (const level of ['log', 'info', 'debug']) console[level] = (...values) => process.stderr.write(values.map(String).join(' ') + '\\n');",
      `const handler = new AsyncFunction('input', ${JSON.stringify(node.handlerSource)});`,
      `const input = ${JSON.stringify(input.args ?? null)};`,
      'const data = await handler(input);',
      'process.stdout.write(JSON.stringify({ data: data === undefined ? null : data }));',
    ].join('\n');
    const result = await options.sandbox.exec(
      sandboxId,
      {
        toolCallId: input.executionKey,
        command: `node --input-type=module -e ${shellArgument(program)}`,
        timeoutMs: options.timeoutMs ?? 60_000,
      },
      options.signal,
    );
    if (result.exitCode !== 0 || result.timedOut || result.truncated) {
      const detail = [result.stderr, result.stdout].filter(Boolean).join('\n').trim();
      throw new Error(
        result.timedOut
          ? 'Builtin Action timed out'
          : result.truncated
            ? 'Builtin Action output exceeded the sandbox limit'
            : `Builtin Action exited with code ${result.exitCode}${detail ? `: ${detail.slice(0, 1_000)}` : ''}`,
      );
    }
    try {
      const parsed: unknown = JSON.parse(result.stdout);
      if (!parsed || typeof parsed !== 'object' || !Object.hasOwn(parsed, 'data'))
        throw new Error('missing data');
      return parsed;
    } catch {
      throw new Error('Builtin Action returned invalid JSON');
    }
  } finally {
    await options.sandbox.destroy(sandboxId);
  }
}

export function executeV3WorkflowAction(
  input: V3WorkflowActionExecutionInput,
  options: V3WorkflowActionExecutorOptions,
): Promise<unknown> {
  return input.node.actionType === 'http'
    ? executeHttpAction(input, options)
    : input.node.actionType === 'script'
      ? executeScriptAction(input, options)
      : executeBuiltinAction(input, options);
}
