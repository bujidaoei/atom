/**
 * Credential-free MCP import boundary used by Waker creation.
 *
 * This parser intentionally accepts the small subset of the official MCP
 * configuration format that can be persisted without a workspace secret
 * vault. It validates the complete input before any repository writes happen.
 */

export type CredentialFreeMcpTransport = 'stdio' | 'sse' | 'streamable_http';

export type CredentialFreeMcpConnectorDraft = {
  name: string;
  transport: CredentialFreeMcpTransport;
  command?: string;
  arguments?: string[];
  url?: string;
  timeoutSeconds: number;
  headersHelper?: string;
};

type UnknownRecord = Record<string, unknown>;

const MAX_NAME_LENGTH = 160;
const MAX_ARGUMENT_LENGTH = 2_000;
const MAX_ARGUMENTS = 100;
const MAX_URL_LENGTH = 2_000;
const DEFAULT_TIMEOUT_SECONDS = 60;

function record(value: unknown, label: string): UnknownRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as UnknownRecord;
}

function optionalEmptyRecord(value: unknown, label: string): void {
  if (value === undefined) return;
  const object = record(value, label);
  if (Object.keys(object).length > 0) {
    throw new Error(`${label} must be empty for credential-free MCP import`);
  }
}

function parseTransport(value: unknown, hasCommand: boolean): CredentialFreeMcpTransport {
  if (value !== undefined && typeof value !== 'string') throw new Error('MCP transport must be a string');
  const transport = typeof value === 'string' ? value : undefined;
  if (value !== undefined && !transport) throw new Error('MCP transport must not be empty');
  if (transport && !['stdio', 'sse', 'streamable-http', 'streamable_http'].includes(transport)) {
    throw new Error(`Unsupported MCP transport: ${transport}`);
  }
  if (transport === 'stdio' || (!transport && hasCommand)) return 'stdio';
  if (transport === 'sse') return 'sse';
  return 'streamable_http';
}

function parseUrl(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error('MCP URL must be a non-empty string');
  const url = value.trim();
  if (url.length > MAX_URL_LENGTH) throw new Error('MCP URL is too long');
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error('MCP URL is invalid');
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) {
    throw new Error('MCP URL must use HTTP or HTTPS');
  }
  if (parsed.username || parsed.password) throw new Error('MCP URL userinfo is not allowed');
  for (const key of parsed.searchParams.keys()) {
    if (
      /(?:^|_)(?:token|key|secret|password|passwd|authorization|auth|credential|api[-_]?key|access[-_]?token|client[-_]?secret)(?:$|_)/iu.test(
        key,
      )
    ) {
      throw new Error('MCP URL credential query parameters are not allowed');
    }
  }
  return url;
}

function parseArguments(value: unknown): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > MAX_ARGUMENTS) throw new Error('MCP args must be an array');
  return value.map((argument) => {
    if (typeof argument !== 'string' || argument.length > MAX_ARGUMENT_LENGTH) {
      throw new Error('MCP args must contain only bounded strings');
    }
    return argument;
  });
}

function parseTimeout(value: unknown): number {
  if (value === undefined) return DEFAULT_TIMEOUT_SECONDS;
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 600) {
    throw new Error('MCP timeout must be an integer from 1 to 600 seconds');
  }
  return value;
}

function parseServer(serverName: string, value: unknown): CredentialFreeMcpConnectorDraft {
  if (!serverName.trim() || serverName.length > MAX_NAME_LENGTH || serverName !== serverName.trim()) {
    throw new Error('MCP server name is invalid');
  }
  const server = record(value, `MCP server ${serverName}`);
  const allowed = new Set([
    'authType',
    'args',
    'arguments',
    'command',
    'env',
    'headers',
    'headersHelper',
    'timeout',
    'timeoutSeconds',
    'transport',
    'type',
    'url',
  ]);
  for (const key of Object.keys(server))
    if (!allowed.has(key)) throw new Error(`Unsupported MCP server field: ${key}`);
  if (server.authType !== undefined)
    throw new Error('MCP authType is unsupported for credential-free import');
  optionalEmptyRecord(server.env, 'MCP env');
  optionalEmptyRecord(server.headers, 'MCP headers');
  if (server.headersHelper !== undefined && typeof server.headersHelper !== 'string') {
    throw new Error('MCP headersHelper must be a string');
  }
  const headersHelper = typeof server.headersHelper === 'string' ? server.headersHelper : undefined;
  const hasCommand = server.command !== undefined;
  const hasUrl = server.url !== undefined;
  if (hasCommand === hasUrl)
    throw new Error(`MCP server ${serverName} must provide exactly one command or url`);
  if (hasCommand && (typeof server.command !== 'string' || !server.command.trim())) {
    throw new Error(`MCP server ${serverName} command is invalid`);
  }
  const transport = parseTransport(server.transport ?? server.type, hasCommand);
  if (server.transport !== undefined && server.type !== undefined) {
    const explicitTransport = parseTransport(server.transport, hasCommand);
    const legacyTransport = parseTransport(server.type, hasCommand);
    if (explicitTransport !== legacyTransport) throw new Error('MCP transport fields conflict');
  }
  if (transport === 'stdio' && !hasCommand) throw new Error('stdio MCP transport requires command');
  if (transport !== 'stdio' && !hasUrl) throw new Error('HTTP MCP transport requires url');
  if (
    transport !== 'stdio' &&
    (server.command !== undefined || server.args !== undefined || server.arguments !== undefined)
  ) {
    throw new Error('HTTP MCP transport does not accept command or args');
  }
  if (
    server.timeout !== undefined &&
    server.timeoutSeconds !== undefined &&
    server.timeout !== server.timeoutSeconds
  ) {
    throw new Error('MCP timeout fields conflict');
  }
  if (server.args !== undefined && server.arguments !== undefined && server.args !== server.arguments) {
    throw new Error('MCP argument fields conflict');
  }
  const timeoutSeconds = parseTimeout(server.timeout ?? server.timeoutSeconds);
  if (transport === 'stdio') {
    return {
      name: serverName,
      transport,
      command: (server.command as string).trim(),
      arguments: parseArguments(server.args ?? server.arguments),
      timeoutSeconds,
      ...(headersHelper ? { headersHelper } : {}),
    };
  }
  return {
    name: serverName,
    transport,
    url: parseUrl(server.url),
    timeoutSeconds,
    ...(headersHelper ? { headersHelper } : {}),
  };
}

/** Parse one or more credential-free MCP JSON documents before repository writes. */
export function parseCredentialFreeMcpConfigs(value: unknown): CredentialFreeMcpConnectorDraft[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new Error('mcpConfigs must be an array');
  const drafts: CredentialFreeMcpConnectorDraft[] = [];
  const names = new Set<string>();
  for (const raw of value) {
    if (typeof raw !== 'string' || !raw.trim()) throw new Error('MCP config must be a non-empty JSON string');
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error('MCP config must contain valid JSON');
    }
    const root = record(parsed, 'MCP config root');
    for (const key of Object.keys(root))
      if (key !== 'mcpServers') throw new Error(`Unsupported MCP config field: ${key}`);
    const servers = record(root.mcpServers, 'mcpServers');
    const entries = Object.entries(servers);
    if (!entries.length) throw new Error('mcpServers must contain at least one server');
    for (const [name, server] of entries) {
      if (names.has(name)) throw new Error(`Duplicate MCP server name: ${name}`);
      names.add(name);
      drafts.push(parseServer(name, server));
    }
  }
  return drafts;
}
