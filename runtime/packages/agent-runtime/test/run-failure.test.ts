import { describe, expect, it } from 'vitest';

import { classifyRunFailure, knowledgeFailureDetail, runFailureDetail } from '../src/run-failure.ts';

describe('V4 gateway failure contract', () => {
  it.each(['TimeoutError', 'AbortError', 'Error'])('retains storage origin over %s causes', (name) => {
    const cause = new Error('Request aborted');
    cause.name = name;
    const error = new Error('Object storage read failed', { cause });
    error.name = 'ObjectStorageReadError';
    expect(classifyRunFailure(error)).toBe('storage_failed');
  });
  it('does not mislabel a Run status database timeout as a model timeout', () => {
    expect(
      classifyRunFailure(
        new Error('Run status observation failed', {
          cause: new DOMException('Database deadline', 'TimeoutError'),
        }),
      ),
    ).toBe('internal');
  });
  it.each([
    ['LITELLM_MASTER_KEY is required', 'configuration_missing'],
    ['AI gateway configuration is missing', 'configuration_missing'],
    ['401 Unauthorized', 'gateway_authentication'],
    ['403 Forbidden', 'gateway_authorization'],
    ['configured model route-a is not available', 'model_unavailable'],
    ['AI gateway model is unavailable: route-b', 'model_unavailable'],
    ['429 Too Many Requests', 'provider_rate_limit'],
    ['budget has been exceeded', 'provider_budget'],
    ['quota exhausted', 'provider_budget'],
    ['maximum context length exceeded', 'provider_context_limit'],
    ['request timed out after 620000ms', 'provider_timeout'],
    ['AI gateway proxy failed with HTTP 504', 'provider_timeout'],
    ['gateway returned malformed JSON', 'provider_malformed'],
    ['503 Service Unavailable', 'provider_unavailable'],
    ['413 status code (no body)', 'provider_rejected'],
    ['Sandbox Broker returned 500', 'sandbox_unavailable'],
    ['Sandbox Broker returned 401', 'sandbox_unavailable'],
    ['Sandbox Broker returned 403', 'sandbox_unavailable'],
    ['Sandbox Broker returned 429', 'sandbox_unavailable'],
    ['Sandbox Broker returned 504', 'sandbox_unavailable'],
    ['TLS socket disconnected during stream', 'provider_stream'],
    ['user cancelled the request', 'cancelled'],
  ])('classifies %s as %s', (message, expected) => {
    expect(classifyRunFailure(new Error(message))).toBe(expected);
  });

  it('prioritizes provider timeout, content policy, and model-security categories over generic policy text', () => {
    expect(classifyRunFailure(new DOMException('The operation was aborted', 'TimeoutError'))).toBe(
      'provider_timeout',
    );
    expect(
      classifyRunFailure(
        new Error('AI gateway request failed', {
          cause: new DOMException('The operation was aborted', 'TimeoutError'),
        }),
      ),
    ).toBe('provider_timeout');
    expect(classifyRunFailure(new Error('Provider content policy rejected this prompt'))).toBe(
      'provider_rejected',
    );
    expect(classifyRunFailure(new Error('Model security policy does not allow model untrusted-route'))).toBe(
      'model_unavailable',
    );
  });

  it('redacts gateway, storage, Feishu, and authorization credentials', () => {
    const detail = runFailureDetail(
      new Error(
        'Bearer reusable-token LITELLM_MASTER_KEY=master-value STORAGE_S3_SECRET_KEY=storage-value app_secret=feishu-value sk-1234567890abcdef AKID1234567890ABCDE',
      ),
    );

    expect(detail).toBe(
      'Bearer [REDACTED] LITELLM_MASTER_KEY=[REDACTED] STORAGE_S3_SECRET_KEY=[REDACTED] app_secret=[REDACTED] [REDACTED] [REDACTED]',
    );
  });

  it('bounds untrusted provider detail', () => {
    expect(runFailureDetail(new Error('x'.repeat(10_000)))).toHaveLength(4_000);
  });

  it('normalizes and redacts every shared credential shape in failure detail', () => {
    const jwt = ['eyJhbGciOiJIUzI1NiJ9', 'eyJzdWIiOiJmYWlsdXJlIn0', 'signaturepart123'].join('.');
    const detail = runFailureDetail(
      new Error(
        `runtime failed\r\nsignature=signature-secret credential=credential-secret ` +
          `token=token-secret github_pat_${'a'.repeat(24)}_${'b'.repeat(24)} ${jwt}`,
      ),
    );

    expect(detail).not.toMatch(/signature-secret|credential-secret|token-secret|github_pat_|eyJ|[\r\n]/iu);
    expect(detail).toContain('signature=[REDACTED]');
    expect(detail).toContain('credential=[REDACTED]');
    expect(detail.length).toBeLessThanOrEqual(4_000);
  });

  it('uses the shared cloud-key, bare-key and control rules for failure detail', () => {
    const accessKey = `${['AK', 'IA'].join('')}${'A'.repeat(16)}`;
    const controls = String.fromCharCode(0, 9, 27, 127, 159);
    const detail = runFailureDetail(
      new Error(`key=bare-secret${controls}private_key=private-secret ${accessKey}`),
    );

    expect(detail).not.toMatch(/bare-secret|private-secret|AKIA/u);
    expect(
      [...detail].every((character) => {
        const codePoint = character.codePointAt(0)!;
        return codePoint > 0x1f && (codePoint < 0x7f || codePoint > 0x9f);
      }),
    ).toBe(true);
    expect(detail).toBe('key=[REDACTED] private_key=[REDACTED] [REDACTED]');
  });

  it('removes Knowledge source URLs after shared credential redaction', () => {
    expect(
      knowledgeFailureDetail(
        new Error('Fetch https://user:pass@example.test/source?token=url-secret failed key=detail-secret'),
      ),
    ).toBe('Fetch [redacted-url] failed key=[REDACTED]');
  });
});
