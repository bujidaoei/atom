import { describe, expect, it } from 'vitest';

import { loadV4ServerConfiguration, redactV4ServerConfiguration } from '../src/server-configuration.ts';

const completeEnvironment = {
  NODE_ENV: 'test',
  LITELLM_BASE_URL: 'https://gateway.example.com',
  LITELLM_MASTER_KEY: 'sk-test-gateway-not-real',
  LITELLM_MODEL: 'gateway-model-a',
  UPLOAD_DIR: '/app/uploads',
  STORAGE_BACKEND: 'cos',
  STORAGE_S3_ENDPOINT: 'https://cos.example.com',
  STORAGE_S3_ACCESS_KEY: 'test-access-key',
  STORAGE_S3_SECRET_KEY: 'test-secret-key',
  STORAGE_S3_BUCKET: 'test-bucket',
  STORAGE_S3_REGION: 'test-region',
  STORAGE_S3_PREFIX: 'test-prefix',
  STORAGE_PUBLIC_URL_BASE: '',
  APP_SECRET_ENCRYPTION_KEY: 'test-vault-encryption-key-that-is-long-enough-32',
  app_id: 'cli_test',
  app_secret: 'test-app-secret',
  FEISHU_AUTH_ENCRYPTION_KEY: 'test-feishu-auth-key-that-is-long-enough-32',
};

describe('V4 server configuration', () => {
  it('loads one validated LiteLLM, upload, storage, and Feishu configuration', () => {
    const configuration = loadV4ServerConfiguration(completeEnvironment);

    expect(configuration.aiGateway).toEqual({
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-test-gateway-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 620_000,
    });
    expect(configuration.uploadDir).toBe('/app/uploads');
    expect(configuration.storage).toEqual({
      backend: 'cos',
      endpoint: 'https://cos.example.com',
      accessKeyId: 'test-access-key',
      secretAccessKey: 'test-secret-key',
      bucket: 'test-bucket',
      region: 'test-region',
      prefix: 'test-prefix',
      publicUrlBase: undefined,
    });
    expect(configuration.feishu).toEqual({
      tokenEndpointVersion: 'v3',
      appId: 'cli_test',
      appSecret: 'test-app-secret',
      authEncryptionKey: 'test-feishu-auth-key-that-is-long-enough-32',
      scopes: ['offline_access'],
      requestTimeoutMs: 15_000,
    });
  });

  it('allows the Cloud Worker to omit Feishu App credentials it never consumes', () => {
    const environment = {
      ...completeEnvironment,
      app_id: undefined,
      app_secret: undefined,
      FEISHU_AUTH_ENCRYPTION_KEY: undefined,
    };
    const configuration = loadV4ServerConfiguration(environment, { requireFeishu: false });
    expect(configuration.aiGateway.model).toBe('gateway-model-a');
    expect(configuration.feishu).toMatchObject({ appId: '', appSecret: '' });
    expect(configuration.feishu.authEncryptionKey).toBe('');
  });

  it('prefers the V3 AI Gateway aliases when both gateway naming schemes exist', () => {
    const configuration = loadV4ServerConfiguration({
      ...completeEnvironment,
      TOKEN_V3_AI_GATEWAY_BASE_URL: 'https://ai-gateway.skg.com/',
      TOKEN_V3_AI_GATEWAY_ADMIN_KEY: 'v3-admin-key',
    });
    expect(configuration.aiGateway.baseUrl).toBe('https://ai-gateway.skg.com/v1');
    expect(configuration.aiGateway.masterKey).toBe('v3-admin-key');
  });

  it('loads an optional administrator-only default virtual key without replacing the master key', () => {
    const configuration = loadV4ServerConfiguration({
      ...completeEnvironment,
      TOKEN_V3_AI_GATEWAY_DEFAULT_VIRTUAL_KEY: 'sk-admin-default-virtual-test',
    });
    expect(configuration.aiGateway.masterKey).toBe('sk-test-gateway-not-real');
    expect(configuration.aiGateway.defaultVirtualKey).toBe('sk-admin-default-virtual-test');
    expect(JSON.stringify(redactV4ServerConfiguration(configuration))).not.toContain(
      'sk-admin-default-virtual-test',
    );
  });

  it('requires a dedicated Feishu auth encryption key and rejects vault-key reuse', () => {
    expect(() =>
      loadV4ServerConfiguration({ ...completeEnvironment, FEISHU_AUTH_ENCRYPTION_KEY: undefined }),
    ).toThrow(/FEISHU_AUTH_ENCRYPTION_KEY is required/iu);
    expect(() =>
      loadV4ServerConfiguration({
        ...completeEnvironment,
        FEISHU_AUTH_ENCRYPTION_KEY: completeEnvironment.APP_SECRET_ENCRYPTION_KEY,
      }),
    ).toThrow(/must differ from APP_SECRET_ENCRYPTION_KEY/iu);
  });

  it('fails closed on a non-HTTPS production public origin in API-key mode', () => {
    expect(() =>
      loadV4ServerConfiguration(
        {
          ...completeEnvironment,
          NODE_ENV: 'production',
          PUBLIC_BASE_URL: 'http://129.204.151.235',
        },
        { requireFeishu: false },
      ),
    ).toThrow(/PUBLIC_BASE_URL must be an HTTPS origin/iu);
  });

  it('fails closed on incomplete or non-HTTPS production Feishu callback configuration', () => {
    const production = {
      ...completeEnvironment,
      NODE_ENV: 'production',
      PUBLIC_BASE_URL: 'https://workdude.example',
      FEISHU_WEB_REDIRECT_URI: undefined,
      FEISHU_DESKTOP_REDIRECT_URI: undefined,
    };
    expect(() => loadV4ServerConfiguration(production)).toThrow(/redirect_uri/iu);
    expect(() =>
      loadV4ServerConfiguration({
        ...production,
        FEISHU_WEB_REDIRECT_URI: 'http://workdude.example/api/v3/auth/feishu/callback',
        FEISHU_DESKTOP_REDIRECT_URI: 'https://workdude.example/api/v3/auth/feishu/desktop/callback',
      }),
    ).toThrow(/HTTPS/iu);
  });

  it('allows the approved IP callback only for non-production preview configuration', () => {
    const configuration = loadV4ServerConfiguration({
      ...completeEnvironment,
      NODE_ENV: 'development',
      PUBLIC_BASE_URL: 'http://129.204.151.235',
      FEISHU_WEB_REDIRECT_URI: 'http://129.204.151.235/api/v3/auth/feishu/callback',
      FEISHU_DESKTOP_REDIRECT_URI: 'http://129.204.151.235/api/v3/auth/feishu/desktop/callback',
    });
    expect(configuration.feishu.webRedirectUri).toBe('http://129.204.151.235/api/v3/auth/feishu/callback');
    expect(() =>
      loadV4ServerConfiguration({
        ...completeEnvironment,
        NODE_ENV: 'development',
        LITELLM_BASE_URL: 'http://129.204.151.235',
        PUBLIC_BASE_URL: 'http://129.204.151.235',
        FEISHU_WEB_REDIRECT_URI: 'http://129.204.151.235/api/v3/auth/feishu/callback',
        FEISHU_DESKTOP_REDIRECT_URI: 'http://129.204.151.235/api/v3/auth/feishu/desktop/callback',
      }),
    ).toThrow(/LITELLM_BASE_URL must use HTTPS/iu);
  });
  it('accepts exact HTTPS production callback paths', () => {
    const configuration = loadV4ServerConfiguration({
      ...completeEnvironment,
      NODE_ENV: 'production',
      PUBLIC_BASE_URL: 'https://workdude.example',
      FEISHU_WEB_REDIRECT_URI: 'https://workdude.example/api/v3/auth/feishu/callback',
      FEISHU_DESKTOP_REDIRECT_URI: 'https://workdude.example/api/v3/auth/feishu/desktop/callback',
    });
    expect(configuration.feishu.webRedirectUri).toBe('https://workdude.example/api/v3/auth/feishu/callback');
  });

  it('normalizes unique Feishu scopes and always requests offline access for rotation', () => {
    expect(
      loadV4ServerConfiguration({
        ...completeEnvironment,
        FEISHU_OAUTH_SCOPES: 'auth:user.id:read offline_access',
      }).feishu.scopes,
    ).toEqual(['auth:user.id:read', 'offline_access']);
  });

  it('accepts only the explicit Feishu token endpoint compatibility versions', () => {
    expect(
      loadV4ServerConfiguration({ ...completeEnvironment, FEISHU_TOKEN_ENDPOINT_VERSION: 'v2' }).feishu
        .tokenEndpointVersion,
    ).toBe('v2');
    expect(() =>
      loadV4ServerConfiguration({ ...completeEnvironment, FEISHU_TOKEN_ENDPOINT_VERSION: 'v1' }),
    ).toThrow(/FEISHU_TOKEN_ENDPOINT_VERSION/iu);
  });

  it('rejects duplicate or malformed Feishu scopes', () => {
    expect(() =>
      loadV4ServerConfiguration({
        ...completeEnvironment,
        FEISHU_OAUTH_SCOPES: 'offline_access offline_access',
      }),
    ).toThrow(/scopes/iu);
    expect(() =>
      loadV4ServerConfiguration({ ...completeEnvironment, FEISHU_OAUTH_SCOPES: 'contact/scope' }),
    ).toThrow(/scopes/iu);
  });

  it.each([1_000, 620_000, 650_000])('accepts bounded timeout %i', (requestTimeoutMs) => {
    expect(
      loadV4ServerConfiguration({
        ...completeEnvironment,
        LITELLM_REQUEST_TIMEOUT_MS: String(requestTimeoutMs),
      }).aiGateway.requestTimeoutMs,
    ).toBe(requestTimeoutMs);
  });

  it.each(['999', '650001', 'not-a-number'])('rejects invalid timeout %s', (value) => {
    expect(() =>
      loadV4ServerConfiguration({
        ...completeEnvironment,
        LITELLM_REQUEST_TIMEOUT_MS: value,
      }),
    ).toThrow(/LITELLM_REQUEST_TIMEOUT_MS/u);
  });

  it.each(['production', 'staging', undefined])(
    'rejects loopback gateway HTTP outside explicit development/test mode (%s)',
    (nodeEnvironment) => {
      expect(() =>
        loadV4ServerConfiguration({
          ...completeEnvironment,
          NODE_ENV: nodeEnvironment,
          LITELLM_BASE_URL: 'http://127.0.0.1:4000',
          ...(nodeEnvironment === 'production'
            ? {
                PUBLIC_BASE_URL: 'https://workdude.example',
                FEISHU_WEB_REDIRECT_URI: 'https://workdude.example/api/v3/auth/feishu/callback',
                FEISHU_DESKTOP_REDIRECT_URI: 'https://workdude.example/api/v3/auth/feishu/desktop/callback',
              }
            : {}),
        }),
      ).toThrow(/LITELLM_BASE_URL must use HTTPS outside explicit development or test mode/u);
    },
  );

  it.each(['development', 'test'])(
    'accepts loopback gateway HTTP only in explicit %s mode',
    (nodeEnvironment) => {
      expect(
        loadV4ServerConfiguration({
          ...completeEnvironment,
          NODE_ENV: nodeEnvironment,
          LITELLM_BASE_URL: 'http://127.0.0.1:4000',
        }).aiGateway.baseUrl,
      ).toBe('http://127.0.0.1:4000/v1');
    },
  );

  it.each([
    'LITELLM_BASE_URL',
    'LITELLM_MASTER_KEY',
    'LITELLM_MODEL',
    'UPLOAD_DIR',
    'STORAGE_BACKEND',
    'STORAGE_S3_ENDPOINT',
    'STORAGE_S3_ACCESS_KEY',
    'STORAGE_S3_SECRET_KEY',
    'STORAGE_S3_BUCKET',
    'STORAGE_S3_REGION',
    'STORAGE_S3_PREFIX',
    'app_id',
    'app_secret',
  ])('fails closed when %s is absent', (name) => {
    expect(() => loadV4ServerConfiguration({ ...completeEnvironment, [name]: undefined })).toThrow(
      new RegExp(name, 'u'),
    );
  });

  it('does not accept legacy direct-provider settings as gateway configuration', () => {
    expect(() =>
      loadV4ServerConfiguration({
        ...completeEnvironment,
        LITELLM_BASE_URL: undefined,
        DEEPSEEK_BASE_URL: 'https://api.deepseek.com',
        DEEPSEEK_API_KEY: 'legacy-key',
      }),
    ).toThrow(/LITELLM_BASE_URL/u);
  });

  it('redacts every reusable credential and retains only operational identity', () => {
    const redacted = redactV4ServerConfiguration(loadV4ServerConfiguration(completeEnvironment));
    const serialized = JSON.stringify(redacted);

    expect(redacted).toMatchObject({
      aiGateway: { baseUrl: 'https://gateway.example.com/v1', model: 'gateway-model-a' },
      storage: { endpoint: 'https://cos.example.com', bucket: 'test-bucket' },
      feishu: { configured: true },
    });
    expect(serialized).not.toContain('sk-test-gateway-not-real');
    expect(serialized).not.toContain('test-access-key');
    expect(serialized).not.toContain('test-secret-key');
    expect(serialized).not.toContain('test-app-secret');
  });
});
