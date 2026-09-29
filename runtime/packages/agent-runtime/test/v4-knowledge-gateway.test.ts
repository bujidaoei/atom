import { afterEach, describe, expect, it, vi } from 'vitest';

import { startEnterpriseGatewayLoopback } from '../../../tests/fixtures/v4/enterprise-ai-gateway.ts';
import { createEnterpriseAiGatewayClient } from '../src/enterprise-ai-gateway.ts';
import { generateKnowledgeCards, knowledgeCardGatewayCompletion } from '../src/v3-knowledge-cards.ts';

const gateways: Array<{ close(): Promise<void> }> = [];

afterEach(async () => {
  await Promise.all(gateways.splice(0).map((gateway) => gateway.close()));
});

describe('V4 Knowledge enterprise gateway', () => {
  it('uses the shared client and reports validated cards, usage, and correlation', async () => {
    const gateway = await startEnterpriseGatewayLoopback({
      contentChunks: [
        JSON.stringify({
          cards: [
            {
              title: 'Gateway card',
              keywords: ['gateway'],
              contentMarkdown: '## Gateway\n\nGrounded content.',
            },
          ],
        }),
      ],
      correlationId: 'knowledge-correlation',
      responseCostHeader: 0.125,
      usage: {
        prompt_tokens: 7,
        completion_tokens: 5,
        total_tokens: 12,
        prompt_tokens_details: { cached_tokens: 0, cache_write_tokens: 0 },
        cache_read_input_tokens: 4,
        cache_creation_input_tokens: 3,
        response_cost: 0,
      },
    });
    gateways.push(gateway);
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: `${gateway.baseUrl}/v1`,
        masterKey: gateway.apiKey,
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      fetch,
    );

    await expect(
      generateKnowledgeCards('Gateway source', 'Grounded content.', {
        gateway: client,
      }),
    ).resolves.toEqual({
      cards: [
        {
          title: 'Gateway card',
          keywords: ['gateway'],
          contentMarkdown: '## Gateway\n\nGrounded content.',
        },
      ],
      usage: {
        inputTokens: 7,
        outputTokens: 5,
        cacheReadTokens: 4,
        cacheWriteTokens: 3,
        totalTokens: 12,
        totalCost: 0.125,
      },
      providerCorrelationId: 'knowledge-correlation',
    });
    expect(gateway.requests.at(-1)).toMatchObject({
      url: '/v1/chat/completions',
      authorization: `Bearer ${gateway.apiKey}`,
    });
  });

  it('propagates cancellation through the shared client', async () => {
    const gateway = await startEnterpriseGatewayLoopback({ delayMs: 250 });
    gateways.push(gateway);
    const controller = new AbortController();
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: `${gateway.baseUrl}/v1`,
        masterKey: gateway.apiKey,
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      fetch,
    );
    setTimeout(() => controller.abort(), 25);

    await expect(
      generateKnowledgeCards('Source', 'Content', { gateway: client, signal: controller.signal }),
    ).rejects.toThrow(/abort|cancel/iu);
  });

  it('rejects malformed structured content without a fallback card', async () => {
    const gateway = await startEnterpriseGatewayLoopback({
      contentChunks: ['{bad'],
      correlationId: 'knowledge-malformed-correlation',
      usage: {
        prompt_tokens: 9,
        completion_tokens: 2,
        total_tokens: 11,
        cache_read_input_tokens: 5,
        cache_creation_input_tokens: 1,
        response_cost: 0.25,
      },
    });
    gateways.push(gateway);
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: `${gateway.baseUrl}/v1`,
        masterKey: gateway.apiKey,
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      fetch,
    );

    const failure = await generateKnowledgeCards('Source', 'Content', { gateway: client }).catch(
      (cause: unknown) => cause,
    );
    expect(failure).toBeInstanceOf(Error);
    expect(String(failure)).toMatch(/malformed/iu);
    expect(knowledgeCardGatewayCompletion(failure)).toEqual({
      usage: {
        inputTokens: 9,
        outputTokens: 2,
        cacheReadTokens: 5,
        cacheWriteTokens: 1,
        totalTokens: 11,
        totalCost: 0.25,
      },
      providerCorrelationId: 'knowledge-malformed-correlation',
    });
  });

  it('retains bounded correlation when a gateway response body is malformed', async () => {
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: 'http://127.0.0.1:1/v1',
        masterKey: 'loopback-test-key',
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      vi.fn(
        async () =>
          new Response('{bad', {
            status: 200,
            headers: {
              'content-type': 'application/json',
              'x-request-id':
                'Bearer sk-malformed-body-secret-123456789 token=malformed-body-token-123456789',
            },
          }),
      ) as unknown as typeof fetch,
    );

    const failure = await generateKnowledgeCards('Source', 'Content', { gateway: client }).catch(
      (cause: unknown) => cause,
    );
    expect(String(failure)).toMatch(/malformed JSON/iu);
    expect(knowledgeCardGatewayCompletion(failure)).toEqual({
      usage: null,
      providerCorrelationId: 'Bearer [REDACTED] token=[REDACTED]',
    });
  });

  it('retains usage and a response id when gateway content validation fails', async () => {
    const client = createEnterpriseAiGatewayClient(
      {
        baseUrl: 'http://127.0.0.1:1/v1',
        masterKey: 'loopback-test-key',
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              id: 'token=response-id-secret-123456789',
              choices: [{ message: { content: '' } }],
              usage: {
                prompt_tokens: 3,
                completion_tokens: 1,
                total_tokens: 4,
                prompt_tokens_details: { cached_tokens: 2, cache_write_tokens: 1 },
                response_cost: 0.75,
              },
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          ),
      ) as unknown as typeof fetch,
    );

    const failure = await generateKnowledgeCards('Source', 'Content', { gateway: client }).catch(
      (cause: unknown) => cause,
    );
    expect(String(failure)).toMatch(/empty content/iu);
    expect(knowledgeCardGatewayCompletion(failure)).toEqual({
      usage: {
        inputTokens: 3,
        outputTokens: 1,
        cacheReadTokens: 2,
        cacheWriteTokens: 1,
        totalTokens: 4,
        totalCost: 0.75,
      },
      providerCorrelationId: 'token=[REDACTED]',
    });
  });
});
