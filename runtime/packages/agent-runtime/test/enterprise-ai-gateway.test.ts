import { createServer, type RequestListener } from 'node:http';
import type { AddressInfo } from 'node:net';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { startEnterpriseGatewayLoopback } from '../../../tests/fixtures/v4/enterprise-ai-gateway.ts';
import {
  assertEnterpriseAiGatewayModelAuthorized,
  createEnterpriseAiGatewayAuthorizationState,
  createEnterpriseAiGatewayClient,
  createEnterpriseAiGatewayReadinessProbe,
  normalizeEnterpriseAiGatewayBaseUrl,
  resolveEnterpriseChatModel,
  validateEnterpriseAiGatewayModel,
  validateEnterpriseAiGatewayStartup,
  type EnterpriseAiGatewayConfiguration,
} from '../src/enterprise-ai-gateway.ts';
import { classifyRunFailure } from '../src/run-failure.ts';

const gateways: Array<{ close(): Promise<void> }> = [];

async function listenLoopback(handler: RequestListener): Promise<string> {
  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  gateways.push({
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.closeAllConnections();
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  });
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

afterEach(async () => {
  await Promise.all(gateways.splice(0).map((gateway) => gateway.close()));
  vi.restoreAllMocks();
});

describe('enterprise AI gateway boundary', () => {
  it('recovers from one real startup probe deadline without accepting an unchecked catalog', async () => {
    let probes = 0;
    const origin = await listenLoopback((request, response) => {
      if (request.url === '/health/liveliness') {
        if (++probes > 1) response.end();
      } else if (!request.headers.authorization) response.writeHead(401).end();
      else response.end(JSON.stringify({ data: [{ id: 'model' }] }));
    });
    const authority = createEnterpriseAiGatewayAuthorizationState({
      baseUrl: `${origin}/v1`,
      masterKey: 'synthetic-key',
      model: 'model',
      requestTimeoutMs: 100,
    });
    expect((await validateEnterpriseAiGatewayStartup(authority)).availableModels).toEqual(['model']);
    expect(probes).toBe(2);
  });

  it('does not retry or accept an insecure unauthenticated catalog', async () => {
    let probes = 0;
    const origin = await listenLoopback((request, response) => {
      if (request.url === '/health/liveliness') probes++;
      response.end();
    });
    const authority = createEnterpriseAiGatewayAuthorizationState({
      baseUrl: `${origin}/v1`,
      masterKey: 'synthetic-key',
      model: 'model',
      requestTimeoutMs: 500,
    });
    await expect(validateEnterpriseAiGatewayStartup(authority)).rejects.toThrow(
      'must reject unauthenticated',
    );
    expect(probes).toBe(1);
  });

  it('revalidates the complete gateway after a transient startup outage', async () => {
    let probes = 0;
    let catalogs = 0;
    const origin = await listenLoopback((request, response) => {
      if (request.url === '/health/liveliness') {
        response.writeHead(++probes === 1 ? 503 : 200).end();
      } else if (!request.headers.authorization) {
        response.writeHead(401).end();
      } else {
        catalogs++;
        response.end(JSON.stringify({ data: [{ id: 'model' }] }));
      }
    });
    const authority = createEnterpriseAiGatewayAuthorizationState({
      baseUrl: `${origin}/v1`,
      masterKey: 'synthetic-key',
      model: 'model',
      requestTimeoutMs: 500,
    });
    const retry = vi.fn();
    expect((await validateEnterpriseAiGatewayStartup(authority, retry)).status).toBe('ready');
    expect(probes).toBe(2);
    expect(catalogs).toBe(1);
    expect(retry).toHaveBeenCalledTimes(1);
    expect(retry.mock.calls.flat().join(' ')).not.toContain('synthetic-key');
  });

  it.each([401, 403, 429, 503])('bounds startup attempts for catalog status %s', async (status) => {
    let catalogs = 0;
    const origin = await listenLoopback((request, response) => {
      if (request.url === '/health/liveliness') response.end();
      else if (!request.headers.authorization) response.writeHead(401).end();
      else {
        catalogs++;
        response.writeHead(status).end();
      }
    });
    const authority = createEnterpriseAiGatewayAuthorizationState({
      baseUrl: `${origin}/v1`,
      masterKey: 'synthetic-key',
      model: 'model',
      requestTimeoutMs: 500,
    });
    await expect(validateEnterpriseAiGatewayStartup(authority)).rejects.toThrow(String(status));
    expect(catalogs).toBe(status === 503 ? 3 : 1);
  });

  it('bounds a real catalog body stalled after successful headers', async () => {
    const origin = await listenLoopback((request, response) => {
      if (request.url === '/health/liveliness') {
        response.end('alive');
        return;
      }
      if (!request.headers.authorization) {
        response.writeHead(401).end();
        return;
      }
      response.writeHead(200, { 'content-type': 'application/json' });
      response.write('{"data":');
    });
    const failure = await validateEnterpriseAiGatewayModel(
      {
        baseUrl: `${origin}/v1`,
        masterKey: 'local-test-token',
        model: 'model-a',
        requestTimeoutMs: 5_000,
      },
      fetch,
      { timeoutMs: 100 },
    ).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toBe('AI gateway model discovery response stream failed');
    expect(classifyRunFailure(failure)).toBe('provider_timeout');
  });

  it.each([
    [new DOMException('The operation was aborted', 'TimeoutError'), 'provider_timeout'],
    [new DOMException('The operation was aborted', 'AbortError'), 'cancelled'],
    [new TypeError('terminated'), 'provider_stream'],
  ])('retains discovery origin when catalog body fails: %s', async (cause, category) => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'test-key',
      model: 'gateway-model-a',
      requestTimeoutMs: 5_000,
    };
    const fetcher: typeof fetch = async (input, init) => {
      if (String(input).endsWith('/health/liveliness')) return new Response('alive');
      if (!new Headers(init?.headers).has('authorization')) return new Response(null, { status: 401 });
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.error(cause);
          },
        }),
      );
    };
    const error = await validateEnterpriseAiGatewayModel(configuration, fetcher).catch(
      (failure: unknown) => failure,
    );
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe('AI gateway model discovery response stream failed');
    expect((error as Error).cause).toBe(cause);
    expect(classifyRunFailure(error)).toBe(category);
  });
  it.each(
    [302, 307, 308].flatMap((statusCode) =>
      ['completion', 'liveness', 'anonymous-models', 'authenticated-models'].map((stage) => ({
        statusCode,
        stage,
      })),
    ),
  )('refuses HTTP $statusCode at $stage before reaching another origin', async ({ statusCode, stage }) => {
    let redirectedRequests = 0;
    let redirectsIssued = 0;
    const destination = await listenLoopback((request, response) => {
      redirectedRequests += 1;
      request.resume();
      response.writeHead(stage === 'anonymous-models' ? 401 : 200, { 'content-type': 'application/json' });
      response.end(
        JSON.stringify({
          data: [{ id: 'gateway-model-a' }],
          choices: [{ message: { content: 'redirected' } }],
        }),
      );
    });
    const origin = await listenLoopback((request, response) => {
      request.resume();
      const requestedStage =
        request.url === '/v1/chat/completions'
          ? 'completion'
          : request.url === '/health/liveliness'
            ? 'liveness'
            : request.headers.authorization
              ? 'authenticated-models'
              : 'anonymous-models';
      if (requestedStage === stage) {
        redirectsIssued += 1;
        response.writeHead(statusCode, { location: `${destination}/outside-gateway` });
        response.end();
        return;
      }
      response.writeHead(requestedStage === 'anonymous-models' ? 401 : 200, {
        'content-type': 'application/json',
      });
      response.end(JSON.stringify({ data: [{ id: 'gateway-model-a' }] }));
    });
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: `${origin}/v1`,
      masterKey: 'synthetic-redirect-test-key',
      model: 'gateway-model-a',
      requestTimeoutMs: 3_000,
    };
    const operation =
      stage === 'completion'
        ? createEnterpriseAiGatewayClient(configuration).complete({
            messages: [{ role: 'user', content: 'synthetic knowledge document' }],
          })
        : validateEnterpriseAiGatewayModel(configuration);
    await expect(operation).rejects.toThrow();
    expect(redirectsIssued).toBe(1);
    expect(redirectedRequests).toBe(0);
  });

  it('uses only exact authorized gateway model ids and rejects retired Qoder strategies', () => {
    const authorizedModels = ['gateway-model-a', 'qwen3.8-max'];
    expect(resolveEnterpriseChatModel(undefined, 'gateway-model-a', authorizedModels)).toBe(
      'gateway-model-a',
    );
    expect(() => resolveEnterpriseChatModel('auto', 'gateway-model-a', authorizedModels)).toThrow(
      /unavailable/iu,
    );
    expect(() => resolveEnterpriseChatModel('lite', 'gateway-model-a', authorizedModels)).toThrow(
      /unavailable/iu,
    );
    expect(resolveEnterpriseChatModel('qwen3.8-max', 'gateway-model-a', authorizedModels)).toBe(
      'qwen3.8-max',
    );
    expect(() => resolveEnterpriseChatModel('unlisted-model', 'gateway-model-a', authorizedModels)).toThrow(
      /unavailable/iu,
    );
    expect(() => assertEnterpriseAiGatewayModelAuthorized('unlisted-model', authorizedModels)).toThrow(
      /unavailable/iu,
    );
    expect(() => resolveEnterpriseChatModel(undefined, 'gateway-model-a', [])).toThrow(/unavailable/iu);
    try {
      assertEnterpriseAiGatewayModelAuthorized('unlisted-model', authorizedModels);
    } catch (cause) {
      expect(classifyRunFailure(cause)).toBe('model_unavailable');
    }
  });

  it.each([
    ['https://gateway.example.com', 'https://gateway.example.com/v1'],
    ['https://gateway.example.com/', 'https://gateway.example.com/v1'],
    ['https://gateway.example.com/v1', 'https://gateway.example.com/v1'],
    ['https://gateway.example.com/root/', 'https://gateway.example.com/root/v1'],
    ['http://127.0.0.1:4000', 'http://127.0.0.1:4000/v1'],
  ])('normalizes %s once', (input, expected) => {
    expect(normalizeEnterpriseAiGatewayBaseUrl(input)).toBe(expected);
  });

  it.each([
    'not-a-url',
    'ftp://gateway.example.com',
    'http://gateway.example.com',
    'https://user:password@gateway.example.com',
  ])('rejects unsafe base URL %s', (input) => {
    expect(() => normalizeEnterpriseAiGatewayBaseUrl(input)).toThrow(/LITELLM_BASE_URL/u);
  });

  it('authenticates model discovery and returns only redacted readiness', async () => {
    const gateway = await startEnterpriseGatewayLoopback({ models: ['gateway-model-a'] });
    gateways.push(gateway);
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: normalizeEnterpriseAiGatewayBaseUrl(gateway.baseUrl),
      masterKey: gateway.apiKey,
      model: 'gateway-model-a',
      requestTimeoutMs: 5_000,
    };

    const readiness = await validateEnterpriseAiGatewayModel(configuration);

    expect(readiness).toMatchObject({
      status: 'ready',
      model: 'gateway-model-a',
      availableModelCount: 1,
      availableModels: ['gateway-model-a'],
    });
    expect(JSON.stringify(readiness)).not.toContain(gateway.apiKey);
    expect(gateway.requests).toEqual([
      expect.objectContaining({
        method: 'GET',
        url: '/health/liveliness',
        authorization: undefined,
      }),
      expect.objectContaining({
        method: 'GET',
        url: '/v1/models',
        authorization: undefined,
      }),
      expect.objectContaining({
        method: 'GET',
        url: '/v1/models',
        authorization: `Bearer ${gateway.apiKey}`,
      }),
    ]);
  });

  it('fails when the explicit configured model is absent', async () => {
    const gateway = await startEnterpriseGatewayLoopback({ models: ['different-model'] });
    gateways.push(gateway);

    await expect(
      validateEnterpriseAiGatewayModel({
        baseUrl: normalizeEnterpriseAiGatewayBaseUrl(gateway.baseUrl),
        masterKey: gateway.apiKey,
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      }),
    ).rejects.toThrow(/gateway-model-a.*not available/iu);
  });

  it('redacts authentication failures', async () => {
    const gateway = await startEnterpriseGatewayLoopback();
    gateways.push(gateway);
    const rejectedKey = 'sk-rejected-test-key-not-real';

    await expect(
      validateEnterpriseAiGatewayModel({
        baseUrl: normalizeEnterpriseAiGatewayBaseUrl(gateway.baseUrl),
        masterKey: rejectedKey,
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      }),
    ).rejects.not.toThrow(rejectedKey);
  });

  it('rejects a non-LiteLLM service before authenticated model discovery', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://provider.example.com/v1',
      masterKey: 'sk-provider-test-key-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 5_000,
    };
    const requests: string[] = [];
    const authenticatedRequests: string[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      requests.push(String(input));
      if (new Headers(init?.headers).has('authorization')) authenticatedRequests.push(String(input));
      return new Response('not found', { status: 404 });
    };

    await expect(validateEnterpriseAiGatewayModel(configuration, fetcher)).rejects.toThrow(/liveness/iu);
    expect(requests.sort()).toEqual([
      'https://provider.example.com/health/liveliness',
      'https://provider.example.com/v1/models',
    ]);
    expect(authenticatedRequests).toEqual([]);
  });

  it('bounds the authenticated model catalog by bytes actually received', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 5_000,
    };
    const oversizedCatalog = JSON.stringify({
      data: [{ id: 'gateway-model-a', padding: 'x'.repeat(2 * 1024 * 1024) }],
    });
    const fetcher: typeof fetch = async (input, init) => {
      const url = String(input);
      if (url.endsWith('/health/liveliness')) return new Response('alive', { status: 200 });
      if (!new Headers(init?.headers).has('authorization')) {
        return new Response('unauthorized', { status: 401 });
      }
      return new Response(oversizedCatalog, {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };

    await expect(validateEnterpriseAiGatewayModel(configuration, fetcher)).rejects.toThrow(/2 MiB/iu);
  });

  it('bounds structured completion success bodies by bytes actually received and cancels overflow', async () => {
    let cancelled = false;
    const oversizedFetch: typeof fetch = async () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            const chunk = new Uint8Array(1024 * 1024);
            for (let index = 0; index < 5; index += 1) controller.enqueue(chunk);
          },
          cancel() {
            cancelled = true;
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: 'https://gateway.example.com/v1',
        masterKey: 'sk-gateway-test-key-not-real',
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      oversizedFetch,
    );

    await expect(client.complete({ messages: [] })).rejects.toThrow(/4 MiB/iu);
    expect(cancelled).toBe(true);
  });

  it('cancels non-success structured response bodies before returning the categorized failure', async () => {
    let cancelled = false;
    const rejectedFetch: typeof fetch = async () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode('credential-shaped provider failure'));
          },
          cancel() {
            cancelled = true;
          },
        }),
        { status: 503, headers: { 'x-request-id': 'gateway-rejected-request' } },
      );
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: 'https://gateway.example.com/v1',
        masterKey: 'sk-gateway-test-key-not-real',
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      rejectedFetch,
    );

    await expect(client.complete({ messages: [] })).rejects.toThrow(/HTTP 503/iu);
    expect(cancelled).toBe(true);
  });

  it.each([
    {
      name: 'trusted response header',
      responseId: 'opaque-body-id',
      correlation: 'Bearer sk-structured-secret-123456789 token=structured-token-123456789',
      expected: 'Bearer [REDACTED] token=[REDACTED]',
    },
    {
      name: 'response body fallback',
      responseId: 'token=structured-body-token-123456789',
      correlation: null,
      expected: 'token=[REDACTED]',
    },
    {
      name: 'ordinary opaque correlation',
      responseId: 'opaque-body-id',
      correlation: 'gateway-request-123',
      expected: 'gateway-request-123',
    },
  ])('sanitizes successful structured completion correlation from $name only', async (scenario) => {
    const modelContent =
      'Model answer stays exact: Bearer sk-answer-content-123456789 token=answer-token-123456789';
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: 'https://gateway.example.com/v1',
        masterKey: 'sk-gateway-test-key-not-real',
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      async () =>
        new Response(
          JSON.stringify({
            id: scenario.responseId,
            choices: [{ message: { content: modelContent } }],
            usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
          }),
          {
            headers: {
              'content-type': 'application/json',
              ...(scenario.correlation ? { 'x-request-id': scenario.correlation } : {}),
            },
          },
        ),
    );

    await expect(client.complete({ messages: [] })).resolves.toMatchObject({
      content: modelContent,
      providerCorrelationId: scenario.expected,
    });
  });

  it('preserves the failed probe diagnostic when an already-returned response body aborts', async () => {
    const baseUrl = await listenLoopback((request, response) => {
      if (request.url === '/health/liveliness') {
        response.writeHead(200);
        response.write('alive'); // Headers arrive, but the body remains open until the probe deadline.
      }
      // The unauthenticated catalog deliberately never returns headers.
    });
    await expect(
      validateEnterpriseAiGatewayModel(
        {
          baseUrl: `${baseUrl}/v1`,
          masterKey: 'synthetic-key',
          model: 'model',
          requestTimeoutMs: 5000,
        },
        fetch,
        { timeoutMs: 50 },
      ),
    ).rejects.toThrow('AI gateway unauthenticated model discovery could not reach');
  });

  it('caps one complete control-plane probe and deduplicates concurrent readiness callers', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 620_000,
    };
    const requests: string[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      requests.push(String(input));
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, 5);
        init?.signal?.addEventListener(
          'abort',
          () => {
            clearTimeout(timer);
            reject(init.signal?.reason);
          },
          { once: true },
        );
      });
      if (String(input).endsWith('/health/liveliness')) return new Response('alive');
      if (!new Headers(init?.headers).has('authorization')) return new Response('forbidden', { status: 403 });
      return Response.json({ data: [{ id: 'gateway-model-a' }] });
    };
    const probe = createEnterpriseAiGatewayReadinessProbe(configuration, fetcher);

    const [first, second] = await Promise.all([probe(), probe()]);

    expect(first).toEqual(second);
    expect(requests).toHaveLength(3);

    const blockingFetch: typeof fetch = async (_input, init) =>
      await new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
      });
    await expect(
      validateEnterpriseAiGatewayModel(configuration, blockingFetch, { timeoutMs: 20 }),
    ).rejects.toThrow(/liveness/iu);
  });

  it('starts both credential-free identity probes concurrently before authenticated discovery', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 5_000,
    };
    const started: string[] = [];
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetcher: typeof fetch = async (input, init) => {
      const authenticated = new Headers(init?.headers).has('authorization');
      const key = String(input).endsWith('/health/liveliness')
        ? 'liveness'
        : authenticated
          ? 'authenticated-catalog'
          : 'unauthenticated-catalog';
      started.push(key);
      await gate;
      if (key === 'liveness') return new Response('alive');
      if (key === 'unauthenticated-catalog') return new Response('forbidden', { status: 403 });
      return Response.json({ data: [{ id: 'gateway-model-a' }] });
    };

    const validation = validateEnterpriseAiGatewayModel(configuration, fetcher);
    await new Promise((resolve) => setTimeout(resolve, 20));
    const concurrentlyStarted = [...started].sort();
    release();
    await validation;

    expect(concurrentlyStarted).toEqual(['liveness', 'unauthenticated-catalog']);
    expect(started.sort()).toEqual(['authenticated-catalog', 'liveness', 'unauthenticated-catalog']);
  });

  it('serves soft-stale snapshots while refreshing, revokes them on known failure, and recovers', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 5_000,
    };
    let now = 1_000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    let models = ['gateway-model-a'];
    let mode: 'ready' | 'blocked' | 'failed' = 'ready';
    let releaseBlocked!: () => void;
    let markBlocked!: () => void;
    const blocked = new Promise<void>((resolve) => {
      releaseBlocked = resolve;
    });
    const blockedStarted = new Promise<void>((resolve) => {
      markBlocked = resolve;
    });
    const requests: string[] = [];
    let authenticatedRequests = 0;
    const fetcher: typeof fetch = async (input, init) => {
      const authenticated = new Headers(init?.headers).has('authorization');
      const key = String(input).endsWith('/health/liveliness')
        ? 'liveness'
        : authenticated
          ? 'authenticated-catalog'
          : 'unauthenticated-catalog';
      requests.push(key);
      if (key === 'liveness') {
        if (mode === 'failed') throw new Error('gateway unavailable');
        return new Response('alive');
      }
      if (key === 'unauthenticated-catalog') return new Response('forbidden', { status: 403 });
      authenticatedRequests += 1;
      if (mode === 'blocked') {
        markBlocked();
        await blocked;
      }
      return Response.json({ data: models.map((id) => ({ id })) });
    };
    const authorization = createEnterpriseAiGatewayAuthorizationState(configuration, fetcher);

    const first = await authorization.refreshSnapshot();
    expect(first.models).toEqual(['gateway-model-a']);
    expect((await authorization.refreshSnapshot()).checkedAt).toBe(first.checkedAt);
    expect(requests).toHaveLength(3);

    now += 30_001;
    models = ['gateway-model-a', 'gateway-model-b'];
    mode = 'blocked';
    const softA = authorization.refreshSnapshot();
    const softB = authorization.refreshSnapshot();
    const softResult = await Promise.race([
      Promise.all([softA, softB]).then((operations) => ({ kind: 'resolved' as const, operations })),
      new Promise<{ kind: 'blocked' }>((resolve) => setTimeout(() => resolve({ kind: 'blocked' }), 25)),
    ]);
    await blockedStarted;
    mode = 'ready';
    releaseBlocked();
    await Promise.allSettled([softA, softB]);
    expect(softResult.kind).toBe('resolved');
    if (softResult.kind !== 'resolved') throw new Error('Soft-stale snapshot blocked unexpectedly');
    expect(softResult.operations.map(({ checkedAt }) => checkedAt)).toEqual([
      first.checkedAt,
      first.checkedAt,
    ]);
    await vi.waitFor(() => expect(authenticatedRequests).toBe(2));
    let refreshed = first;
    await vi.waitFor(async () => {
      refreshed = await authorization.refreshSnapshot();
      expect(refreshed.models).toEqual(['gateway-model-a', 'gateway-model-b']);
    });
    const refreshedAt = now;

    now += 30_001;
    mode = 'failed';
    expect((await authorization.refreshSnapshot()).checkedAt).toBe(refreshed.checkedAt);
    await vi.waitFor(() => expect(requests.filter((key) => key === 'liveness')).toHaveLength(3));
    await vi.waitFor(async () => {
      await expect(authorization.refreshSnapshot()).rejects.toThrow(/liveness/iu);
    });
    const requestsAfterFailedRefresh = requests.length;
    await expect(authorization.refreshSnapshot()).rejects.toThrow(/liveness/iu);
    expect(requests).toHaveLength(requestsAfterFailedRefresh);

    now = refreshedAt + 120_001;
    await expect(authorization.refreshSnapshot()).rejects.toThrow(/liveness/iu);
    expect(refreshed.resolveModel('gateway-model-b')).toBe('gateway-model-b');

    now += 30_001;
    mode = 'ready';
    models = ['gateway-model-a'];
    expect((await authorization.refreshSnapshot()).models).toEqual(['gateway-model-a']);
  });

  it('revokes a real loopback gateway catalog after an outage or credential rejection', async () => {
    let mode: 'ready' | 'offline' | 'rejected' = 'ready';
    let livenessProbes = 0;
    const origin = await listenLoopback((request, response) => {
      if (request.url === '/health/liveliness') {
        livenessProbes += 1;
        response.writeHead(mode === 'offline' ? 503 : 200).end();
      } else if (!request.headers.authorization || mode === 'rejected') {
        response.writeHead(401).end();
      } else {
        response.setHeader('content-type', 'application/json');
        response.end(JSON.stringify({ data: [{ id: 'gateway-model-a' }] }));
      }
    });
    let now = 1_000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    const authorization = createEnterpriseAiGatewayAuthorizationState({
      baseUrl: `${origin}/v1`,
      masterKey: 'synthetic-key',
      model: 'gateway-model-a',
      requestTimeoutMs: 1_000,
    });

    expect((await authorization.refreshSnapshot()).models).toEqual(['gateway-model-a']);
    now += 30_001;
    mode = 'offline';
    expect((await authorization.refreshSnapshot()).models).toEqual(['gateway-model-a']);
    await vi.waitFor(async () => {
      await expect(authorization.refreshSnapshot()).rejects.toThrow(/liveness/iu);
    });
    const probesAfterOutage = livenessProbes;
    await expect(authorization.refreshSnapshot()).rejects.toThrow(/liveness/iu);
    expect(livenessProbes).toBe(probesAfterOutage);

    now += 30_001;
    mode = 'ready';
    expect((await authorization.refreshSnapshot()).models).toEqual(['gateway-model-a']);

    mode = 'rejected';
    await expect(authorization.validate()).rejects.toThrow(/authentication failed \(401\)/iu);
    await expect(authorization.refreshSnapshot()).rejects.toThrow(/authentication failed \(401\)/iu);
  });

  it('coalesces concurrent live validations and preserves the last accepted operation after failure', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 5_000,
    };
    let models = ['gateway-model-a', 'retired-model'];
    let blockCatalogRefresh = false;
    let releaseCatalogRefresh!: () => void;
    let markCatalogRefreshRequested!: () => void;
    let authenticatedCatalogRequests = 0;
    const catalogRefreshRequested = new Promise<void>((resolve) => {
      markCatalogRefreshRequested = resolve;
    });
    const catalogRefreshGate = new Promise<void>((resolve) => {
      releaseCatalogRefresh = resolve;
    });
    const fetcher: typeof fetch = async (input, init) => {
      if (String(input).endsWith('/health/liveliness')) return new Response('alive');
      if (!new Headers(init?.headers).has('authorization')) return new Response('forbidden', { status: 403 });
      authenticatedCatalogRequests += 1;
      if (blockCatalogRefresh) {
        markCatalogRefreshRequested();
        await catalogRefreshGate;
      }
      return Response.json({ data: models.map((id) => ({ id })) });
    };
    const authorization = createEnterpriseAiGatewayAuthorizationState(configuration, fetcher);

    const operationA = await authorization.refreshSnapshot();
    expect(operationA.models).toEqual(['gateway-model-a', 'retired-model']);

    models = ['gateway-model-a'];
    blockCatalogRefresh = true;
    const refresh = authorization.validate();
    const concurrentRefresh = authorization.validate();
    try {
      await catalogRefreshRequested;
      expect(operationA.models).toEqual(['gateway-model-a', 'retired-model']);
      expect(operationA.resolveModel('retired-model')).toBe('retired-model');
    } finally {
      releaseCatalogRefresh();
    }
    await Promise.all([refresh, concurrentRefresh]);
    const operationB = await authorization.refreshSnapshot();
    expect(operationB.models).toEqual(['gateway-model-a']);
    expect(() => operationB.assertAuthorized('retired-model')).toThrow(/unavailable/iu);
    expect(authenticatedCatalogRequests).toBe(2);

    blockCatalogRefresh = false;
    models = ['replacement-model'];
    const rejectedRefresh = authorization.validate();
    const concurrentRejectedRefresh = authorization.validate();
    const rejectedResults = await Promise.allSettled([rejectedRefresh, concurrentRejectedRefresh]);
    expect(rejectedResults).toEqual([
      expect.objectContaining({ status: 'rejected' }),
      expect.objectContaining({ status: 'rejected' }),
    ]);
    for (const result of rejectedResults) {
      if (result.status === 'fulfilled') throw new Error('Catalog refresh unexpectedly succeeded');
      expect(result.reason).toEqual(
        expect.objectContaining({ message: expect.stringMatching(/not available/iu) }),
      );
    }
    expect(authenticatedCatalogRequests).toBe(3);
    expect(operationB.models).toEqual(['gateway-model-a']);
    await expect(authorization.refreshSnapshot()).rejects.toThrow(/not available/iu);
    expect(authenticatedCatalogRequests).toBe(3);
  });

  it('returns one immutable operation snapshot that survives a concurrent later catalog refresh', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-default',
      requestTimeoutMs: 5_000,
    };
    let models = ['gateway-model-default', 'gateway-model-a'];
    let blockSecondCatalog = false;
    let markSecondCatalogRequested!: () => void;
    let releaseSecondCatalog!: () => void;
    const secondCatalogRequested = new Promise<void>((resolve) => {
      markSecondCatalogRequested = resolve;
    });
    const secondCatalogGate = new Promise<void>((resolve) => {
      releaseSecondCatalog = resolve;
    });
    const fetcher: typeof fetch = async (input, init) => {
      if (String(input).endsWith('/health/liveliness')) return new Response('alive');
      if (!new Headers(init?.headers).has('authorization')) return new Response('forbidden', { status: 403 });
      if (blockSecondCatalog) {
        markSecondCatalogRequested();
        await secondCatalogGate;
      }
      return Response.json({ data: models.map((id) => ({ id })) });
    };
    const authorization = createEnterpriseAiGatewayAuthorizationState(configuration, fetcher);

    const operationA = await authorization.refreshSnapshot();
    expect(operationA).toMatchObject({
      defaultModel: 'gateway-model-default',
      models: ['gateway-model-default', 'gateway-model-a'],
      checkedAt: expect.any(String),
    });
    expect(Object.isFrozen(operationA)).toBe(true);
    expect(Object.isFrozen(operationA.models)).toBe(true);
    expect(operationA).not.toHaveProperty('authorizedModels');
    expect(() => (operationA.models as string[]).push('injected-model')).toThrow(TypeError);
    expect(operationA.resolveModel()).toBe('gateway-model-default');
    expect(operationA.resolveModel('gateway-model-a')).toBe('gateway-model-a');
    expect(() => operationA.resolveModel('gateway-model-b')).toThrow(/unavailable/iu);

    models = ['gateway-model-default', 'gateway-model-b'];
    blockSecondCatalog = true;
    const refreshB = authorization.validate();
    try {
      await secondCatalogRequested;
      expect(operationA.resolveModel('gateway-model-a')).toBe('gateway-model-a');
    } finally {
      releaseSecondCatalog();
    }
    await refreshB;
    const operationB = await authorization.refreshSnapshot();

    expect(operationA.resolveModel('gateway-model-a')).toBe('gateway-model-a');
    expect(() => operationA.resolveModel('gateway-model-b')).toThrow(/unavailable/iu);
    expect(operationB.resolveModel('gateway-model-b')).toBe('gateway-model-b');
    expect(() => operationB.resolveModel('gateway-model-a')).toThrow(/unavailable/iu);
  });

  it('keeps issued snapshots immutable but revokes new ones after a forced validation failure', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-default',
      requestTimeoutMs: 5_000,
    };
    let mode: 'ready' | 'missing-default' | 'rejected' = 'ready';
    const fetcher: typeof fetch = async (input, init) => {
      if (String(input).endsWith('/health/liveliness')) {
        if (mode === 'rejected') throw new Error('gateway unavailable');
        return new Response('alive');
      }
      if (!new Headers(init?.headers).has('authorization')) return new Response('forbidden', { status: 403 });
      return Response.json({
        data: (mode === 'missing-default'
          ? ['gateway-model-replacement']
          : ['gateway-model-default', 'gateway-model-a']
        ).map((id) => ({ id })),
      });
    };
    const authorization = createEnterpriseAiGatewayAuthorizationState(configuration, fetcher);
    const accepted = await authorization.refreshSnapshot();

    mode = 'missing-default';
    await expect(authorization.validate()).rejects.toThrow(/not available/iu);
    expect(accepted.resolveModel('gateway-model-a')).toBe('gateway-model-a');
    await expect(authorization.refreshSnapshot()).rejects.toThrow(/not available/iu);

    mode = 'rejected';
    await expect(authorization.validate()).rejects.toThrow(/liveness/iu);
    await expect(authorization.refreshSnapshot()).rejects.toThrow(/liveness/iu);

    mode = 'ready';
    await authorization.validate();
    expect((await authorization.refreshSnapshot()).models).toEqual([
      'gateway-model-default',
      'gateway-model-a',
    ]);
  });

  it('hard-caps control-plane requests at ten seconds independently of generation timeouts', async () => {
    const configuration: EnterpriseAiGatewayConfiguration = {
      baseUrl: 'https://gateway.example.com/v1',
      masterKey: 'sk-gateway-test-key-not-real',
      model: 'gateway-model-a',
      requestTimeoutMs: 620_000,
    };
    const timeout = new AbortController().signal;
    const timeoutSpy = vi.spyOn(AbortSignal, 'timeout').mockReturnValue(timeout);
    const signals: AbortSignal[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      signals.push(init?.signal as AbortSignal);
      if (String(input).endsWith('/health/liveliness')) return new Response('alive');
      if (!new Headers(init?.headers).has('authorization')) return new Response('forbidden', { status: 403 });
      return Response.json({ data: [{ id: 'gateway-model-a' }] });
    };
    try {
      await validateEnterpriseAiGatewayModel(configuration, fetcher, { timeoutMs: 60_000 });
      expect(timeoutSpy).toHaveBeenCalledWith(10_000);
    } finally {
      timeoutSpy.mockRestore();
    }

    expect(new Set(signals).size).toBe(1);
  });
});
