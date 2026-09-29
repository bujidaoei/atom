export interface V4AiGatewayServerConfiguration {
  baseUrl: string;
  masterKey: string;
  /** Optional administrator-only fallback; never used for Feishu user principals. */
  defaultVirtualKey?: string;
  model: string;
  requestTimeoutMs: number;
}

export interface V4StorageServerConfiguration {
  backend: 'cos';
  endpoint: string;
  accessKeyId: string;
  secretAccessKey: string;
  bucket: string;
  region: string;
  prefix: string;
  publicUrlBase: string | undefined;
}

export interface V4ServerConfiguration {
  aiGateway: V4AiGatewayServerConfiguration;
  uploadDir: string;
  storage: V4StorageServerConfiguration;
  feishu: {
    tokenEndpointVersion: 'v3' | 'v2';
    appId: string;
    appSecret: string;
    /** Dedicated at-rest key for OAuth verifier/code/refresh-token records. */
    authEncryptionKey: string;
    webRedirectUri?: string;
    desktopRedirectUri?: string;
    scopes: string[];
    requestTimeoutMs: number;
  };
}

export interface RedactedV4ServerConfiguration {
  aiGateway: {
    baseUrl: string;
    model: string;
    requestTimeoutMs: number;
    credentialConfigured: true;
  };
  uploadDir: string;
  storage: {
    backend: 'cos';
    endpoint: string;
    bucket: string;
    region: string;
    prefix: string;
    publicUrlBase: string | undefined;
    credentialsConfigured: true;
  };
  feishu: { configured: true };
}

export type EnvironmentValues = Readonly<Record<string, string | undefined>>;

export const ENTERPRISE_AI_GATEWAY_PROVIDER = 'enterprise-gateway' as const;

const DEFAULT_LITELLM_REQUEST_TIMEOUT_MS = 620_000;
const MIN_LITELLM_REQUEST_TIMEOUT_MS = 1_000;
const MAX_LITELLM_REQUEST_TIMEOUT_MS = 650_000;
const DEFAULT_FEISHU_REQUEST_TIMEOUT_MS = 15_000;
const MAX_FEISHU_REQUEST_TIMEOUT_MS = 60_000;
const MIN_FEISHU_AUTH_ENCRYPTION_KEY_LENGTH = 32;
const MAX_FEISHU_AUTH_ENCRYPTION_KEY_LENGTH = 4_096;

function required(environment: EnvironmentValues, name: string): string {
  const value = environment[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function optional(environment: EnvironmentValues, name: string): string | undefined {
  const value = environment[name]?.trim();
  return value || undefined;
}

function hasForbiddenControl(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f)) return true;
  }
  return false;
}

function absoluteHttpUrl(value: string, name: string, allowLoopbackHttp: boolean): URL {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute URL`);
  }
  if (url.username || url.password) throw new Error(`${name} must not contain credentials`);
  const loopback = ['127.0.0.1', '::1', 'localhost'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(allowLoopbackHttp && loopback && url.protocol === 'http:')) {
    throw new Error(`${name} must use HTTPS${allowLoopbackHttp ? ' or loopback HTTP' : ''}`);
  }
  url.hash = '';
  url.search = '';
  return url;
}

export function normalizeLiteLlmBaseUrl(value: string): string {
  const url = absoluteHttpUrl(value.trim(), 'LITELLM_BASE_URL', true);
  const path = url.pathname.replace(/\/+$/u, '');
  url.pathname = path.endsWith('/v1') ? path : `${path}/v1`;
  return url.toString().replace(/\/$/u, '');
}

function serverLiteLlmBaseUrl(environment: EnvironmentValues): string {
  const configuredBaseUrl =
    optional(environment, 'TOKEN_V3_AI_GATEWAY_BASE_URL') ?? required(environment, 'LITELLM_BASE_URL');
  const baseUrl = normalizeLiteLlmBaseUrl(configuredBaseUrl);
  const processMode = optional(environment, 'NODE_ENV');
  if (new URL(baseUrl).protocol === 'http:' && processMode !== 'development' && processMode !== 'test') {
    throw new Error('LITELLM_BASE_URL must use HTTPS outside explicit development or test mode');
  }
  return baseUrl;
}

function normalizedEndpoint(value: string, name: string): string {
  return absoluteHttpUrl(value, name, true).toString().replace(/\/$/u, '');
}

function requestTimeout(environment: EnvironmentValues): number {
  const source = optional(environment, 'LITELLM_REQUEST_TIMEOUT_MS');
  if (!source) return DEFAULT_LITELLM_REQUEST_TIMEOUT_MS;
  const value = Number(source);
  if (
    !Number.isInteger(value) ||
    value < MIN_LITELLM_REQUEST_TIMEOUT_MS ||
    value > MAX_LITELLM_REQUEST_TIMEOUT_MS
  ) {
    throw new Error(
      `LITELLM_REQUEST_TIMEOUT_MS must be an integer from ${MIN_LITELLM_REQUEST_TIMEOUT_MS} to ${MAX_LITELLM_REQUEST_TIMEOUT_MS}`,
    );
  }
  return value;
}

function feishuRequestTimeout(environment: EnvironmentValues): number {
  const source = optional(environment, 'FEISHU_REQUEST_TIMEOUT_MS');
  if (!source) return DEFAULT_FEISHU_REQUEST_TIMEOUT_MS;
  const value = Number(source);
  if (!Number.isInteger(value) || value < 1_000 || value > MAX_FEISHU_REQUEST_TIMEOUT_MS) {
    throw new Error(
      `FEISHU_REQUEST_TIMEOUT_MS must be an integer from 1000 to ${MAX_FEISHU_REQUEST_TIMEOUT_MS}`,
    );
  }
  return value;
}

function feishuTokenEndpointVersion(environment: EnvironmentValues): 'v3' | 'v2' {
  const configured = optional(environment, 'FEISHU_TOKEN_ENDPOINT_VERSION');
  if (!configured || configured === 'v3') return 'v3';
  if (configured === 'v2') return 'v2';
  throw new Error('FEISHU_TOKEN_ENDPOINT_VERSION must be v2 or v3');
}

function feishuScopes(environment: EnvironmentValues): string[] {
  const configured = optional(environment, 'FEISHU_OAUTH_SCOPES');
  const values = (configured ? configured.split(/\s+/u) : ['offline_access']).filter(Boolean);
  if (!values.includes('offline_access')) values.push('offline_access');
  if (
    values.length > 200 ||
    new Set(values).size !== values.length ||
    values.some((value) => !/^[A-Za-z0-9:._-]{1,200}$/u.test(value))
  ) {
    throw new Error('FEISHU_OAUTH_SCOPES must contain up to 200 unique scope names');
  }
  return values;
}

function feishuAuthEncryptionKey(environment: EnvironmentValues, requiredForMode: boolean): string {
  const value = optional(environment, 'FEISHU_AUTH_ENCRYPTION_KEY');
  if (!value) {
    if (requiredForMode) throw new Error('FEISHU_AUTH_ENCRYPTION_KEY is required');
    return '';
  }
  if (
    value.length < MIN_FEISHU_AUTH_ENCRYPTION_KEY_LENGTH ||
    value.length > MAX_FEISHU_AUTH_ENCRYPTION_KEY_LENGTH ||
    /\s/u.test(value) ||
    hasForbiddenControl(value)
  ) {
    throw new Error(
      `FEISHU_AUTH_ENCRYPTION_KEY must be ${MIN_FEISHU_AUTH_ENCRYPTION_KEY_LENGTH} to ${MAX_FEISHU_AUTH_ENCRYPTION_KEY_LENGTH} non-whitespace characters`,
    );
  }
  const vaultKey = optional(environment, 'APP_SECRET_ENCRYPTION_KEY');
  if (vaultKey && value === vaultKey) {
    throw new Error('FEISHU_AUTH_ENCRYPTION_KEY must differ from APP_SECRET_ENCRYPTION_KEY');
  }
  return value;
}

function validateFeishuRedirectUri(
  value: string,
  name: 'FEISHU_WEB_REDIRECT_URI' | 'FEISHU_DESKTOP_REDIRECT_URI',
  allowLoopbackHttp: boolean,
): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute URL`);
  }
  const expectedPath =
    name === 'FEISHU_WEB_REDIRECT_URI'
      ? '/api/v3/auth/feishu/callback'
      : '/api/v3/auth/feishu/desktop/callback';
  const loopback = ['127.0.0.1', '::1', 'localhost'].includes(url.hostname);
  const temporaryIpPreview = url.hostname === '129.204.151.235';
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== expectedPath ||
    (url.protocol !== 'https:' &&
      !(allowLoopbackHttp && loopback && url.protocol === 'http:') &&
      !(temporaryIpPreview && url.protocol === 'http:'))
  ) {
    throw new Error(`${name} must be HTTPS with the exact callback path`);
  }
  return url.toString();
}

function validateProductionPublicBaseUrl(environment: EnvironmentValues): void {
  if (optional(environment, 'NODE_ENV') !== 'production') return;
  const publicBaseUrl = optional(environment, 'PUBLIC_BASE_URL');
  if (!publicBaseUrl) throw new Error('PUBLIC_BASE_URL is required in production');
  let publicOrigin: URL;
  try {
    publicOrigin = new URL(publicBaseUrl);
  } catch {
    throw new Error('PUBLIC_BASE_URL must be an HTTPS origin without a path or query');
  }
  if (
    publicOrigin.protocol !== 'https:' ||
    publicOrigin.username ||
    publicOrigin.password ||
    publicOrigin.pathname !== '/' ||
    publicOrigin.search ||
    publicOrigin.hash
  ) {
    throw new Error('PUBLIC_BASE_URL must be an HTTPS origin without a path or query');
  }
}

function validateProductionFeishuCallbacks(
  environment: EnvironmentValues,
  webRedirectUri: string | undefined,
  desktopRedirectUri: string | undefined,
): void {
  if (optional(environment, 'NODE_ENV') !== 'production') return;
  // Production requires the values to be explicitly registered in the
  // provider console; deriving them from PUBLIC_BASE_URL is convenient only
  // for development/test and can hide a registration typo in production.
  if (
    !optional(environment, 'FEISHU_WEB_REDIRECT_URI') ||
    !optional(environment, 'FEISHU_DESKTOP_REDIRECT_URI') ||
    !webRedirectUri ||
    !desktopRedirectUri
  ) {
    throw new Error(
      'FEISHU_WEB_REDIRECT_URI and FEISHU_DESKTOP_REDIRECT_URI are required in production Feishu mode',
    );
  }
  validateFeishuRedirectUri(webRedirectUri, 'FEISHU_WEB_REDIRECT_URI', false);
  validateFeishuRedirectUri(desktopRedirectUri, 'FEISHU_DESKTOP_REDIRECT_URI', false);
}

export function loadV4ServerConfiguration(
  environment: EnvironmentValues,
  options: { requireFeishu?: boolean } = {},
): V4ServerConfiguration {
  const requireFeishu = options.requireFeishu ?? true;
  const backend = required(environment, 'STORAGE_BACKEND');
  if (backend !== 'cos') throw new Error('STORAGE_BACKEND must be cos');
  const publicUrl = optional(environment, 'STORAGE_PUBLIC_URL_BASE');

  const publicBaseUrl = optional(environment, 'PUBLIC_BASE_URL')?.replace(/\/+$/u, '');
  validateProductionPublicBaseUrl(environment);
  const feishuWebRedirectUri =
    optional(environment, 'FEISHU_WEB_REDIRECT_URI') ??
    (publicBaseUrl ? `${publicBaseUrl}/api/v3/auth/feishu/callback` : undefined);
  const feishuDesktopRedirectUri =
    optional(environment, 'FEISHU_DESKTOP_REDIRECT_URI') ??
    (publicBaseUrl ? `${publicBaseUrl}/api/v3/auth/feishu/desktop/callback` : undefined);
  const lowerAppId = optional(environment, 'app_id');
  const upperAppId = optional(environment, 'FEISHU_APP_ID');
  const lowerAppSecret = optional(environment, 'app_secret');
  const upperAppSecret = optional(environment, 'FEISHU_APP_SECRET');
  if (
    (lowerAppId && upperAppId && lowerAppId !== upperAppId) ||
    (lowerAppSecret && upperAppSecret && lowerAppSecret !== upperAppSecret)
  ) {
    throw new Error('Feishu App ID/Secret aliases must match when both are configured');
  }
  if (requireFeishu) {
    const allowLoopbackHttp = ['development', 'test'].includes(optional(environment, 'NODE_ENV') ?? '');
    if (feishuWebRedirectUri) {
      validateFeishuRedirectUri(feishuWebRedirectUri, 'FEISHU_WEB_REDIRECT_URI', allowLoopbackHttp);
    }
    if (feishuDesktopRedirectUri) {
      validateFeishuRedirectUri(feishuDesktopRedirectUri, 'FEISHU_DESKTOP_REDIRECT_URI', allowLoopbackHttp);
    }
    validateProductionFeishuCallbacks(environment, feishuWebRedirectUri, feishuDesktopRedirectUri);
  }
  const defaultVirtualKey = optional(environment, 'TOKEN_V3_AI_GATEWAY_DEFAULT_VIRTUAL_KEY');
  return {
    aiGateway: {
      baseUrl: serverLiteLlmBaseUrl(environment),
      masterKey:
        optional(environment, 'TOKEN_V3_AI_GATEWAY_ADMIN_KEY') ?? required(environment, 'LITELLM_MASTER_KEY'),
      ...(defaultVirtualKey ? { defaultVirtualKey } : {}),
      model: required(environment, 'LITELLM_MODEL'),
      requestTimeoutMs: requestTimeout(environment),
    },
    uploadDir: required(environment, 'UPLOAD_DIR'),
    storage: {
      backend,
      endpoint: normalizedEndpoint(required(environment, 'STORAGE_S3_ENDPOINT'), 'STORAGE_S3_ENDPOINT'),
      accessKeyId: required(environment, 'STORAGE_S3_ACCESS_KEY'),
      secretAccessKey: required(environment, 'STORAGE_S3_SECRET_KEY'),
      bucket: required(environment, 'STORAGE_S3_BUCKET'),
      region: required(environment, 'STORAGE_S3_REGION'),
      prefix: required(environment, 'STORAGE_S3_PREFIX'),
      publicUrlBase: publicUrl ? normalizedEndpoint(publicUrl, 'STORAGE_PUBLIC_URL_BASE') : undefined,
    },
    feishu: {
      tokenEndpointVersion: feishuTokenEndpointVersion(environment),
      appId: upperAppId ?? lowerAppId ?? (requireFeishu ? required(environment, 'app_id') : ''),
      appSecret:
        upperAppSecret ?? lowerAppSecret ?? (requireFeishu ? required(environment, 'app_secret') : ''),
      authEncryptionKey: feishuAuthEncryptionKey(environment, requireFeishu),
      ...(feishuWebRedirectUri ? { webRedirectUri: feishuWebRedirectUri } : {}),
      ...(feishuDesktopRedirectUri ? { desktopRedirectUri: feishuDesktopRedirectUri } : {}),
      scopes: feishuScopes(environment),
      requestTimeoutMs: feishuRequestTimeout(environment),
    },
  };
}

export function redactV4ServerConfiguration(
  configuration: V4ServerConfiguration,
): RedactedV4ServerConfiguration {
  return {
    aiGateway: {
      baseUrl: configuration.aiGateway.baseUrl,
      model: configuration.aiGateway.model,
      requestTimeoutMs: configuration.aiGateway.requestTimeoutMs,
      credentialConfigured: true,
    },
    uploadDir: configuration.uploadDir,
    storage: {
      backend: configuration.storage.backend,
      endpoint: configuration.storage.endpoint,
      bucket: configuration.storage.bucket,
      region: configuration.storage.region,
      prefix: configuration.storage.prefix,
      publicUrlBase: configuration.storage.publicUrlBase,
      credentialsConfigured: true,
    },
    feishu: { configured: true },
  };
}
