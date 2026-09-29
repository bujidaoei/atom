import { describe, expect, it } from 'vitest';

import {
  redactCredentialText,
  redactFailureEventPayload,
  redactProviderCorrelation,
} from '../src/provider-correlation.ts';

describe('provider correlation redaction', () => {
  it('redacts credential-shaped headers and bounds the retained diagnostic', () => {
    const redacted = redactProviderCorrelation(
      `Authorization: Basic dXNlcjpwYXNz ` +
        `Cookie: session=cookie-secret; Set-Cookie: refresh=set-cookie-secret; ` +
        `token=token-secret api_key=key-secret password=password-secret secret=plain-secret ` +
        'x'.repeat(500),
    );

    expect(redacted).not.toMatch(
      /dXNlcjpwYXNz|cookie-secret|set-cookie-secret|token-secret|key-secret|password-secret|plain-secret/iu,
    );
    expect(redacted).toContain('Authorization: Basic [REDACTED]');
    expect(redacted).toContain('Cookie: [REDACTED]');
    expect(redacted!.length).toBeLessThanOrEqual(200);
    expect(redactProviderCorrelation('Authorization=opaque-secret')).toBe('Authorization=[REDACTED]');
  });

  it('redacts named signatures, credentials, GitHub tokens, JWTs, and line breaks', () => {
    const githubTokens = ['ghp_', 'gho_', 'ghu_', 'ghs_', 'ghr_'].map(
      (prefix) => `${prefix}${'a'.repeat(30)}`,
    );
    const fineGrainedToken = `github_pat_${'b'.repeat(24)}_${'c'.repeat(24)}`;
    const jwt = ['eyJhbGciOiJIUzI1NiJ9', 'eyJzdWIiOiIxMjM0NTY3ODkwIn0', 'signaturepart123'].join('.');
    const redacted = redactProviderCorrelation(
      `opaque-prefix\r\nsignature=signature-secret credential=credential-secret\n` +
        `${githubTokens.join(' ')} ${fineGrainedToken} ${jwt} ${'x'.repeat(500)}`,
    );

    expect(redacted).not.toMatch(/signature-secret|credential-secret|gh[pousr]_|github_pat_|eyJ/iu);
    expect(redacted).not.toMatch(/[\r\n]/u);
    expect(redacted).toContain('signature=[REDACTED]');
    expect(redacted).toContain('credential=[REDACTED]');
    expect(redacted!.length).toBeLessThanOrEqual(200);
  });

  it.each([
    ...['ghp_', 'gho_', 'ghu_', 'ghs_', 'ghr_'].map((prefix) => `${prefix}${'a'.repeat(30)}`),
    `github_pat_${'b'.repeat(24)}_${'c'.repeat(24)}`,
    ['eyJhbGciOiJIUzI1NiJ9', 'eyJzdWIiOiIxMjM0NTY3ODkwIn0', 'signaturepart123'].join('.'),
  ])('redacts a standalone high-confidence token shape', (value) => {
    expect(redactProviderCorrelation(value)).toBe('[REDACTED]');
  });

  it('redacts scanner-recognized cloud access keys and bare key fields', () => {
    const cloudAccessKeys = ['AKIA', 'ASIA', 'AKID'].map((prefix) => `${prefix}${'A'.repeat(16)}`);
    const redacted = redactCredentialText(
      `key=bare-secret private_key=private-secret ${cloudAccessKeys.join(' ')}`,
      4_000,
    );

    expect(redacted).not.toMatch(/bare-secret|private-secret|AKIA|ASIA|AKID/u);
    expect(redacted).toContain('key=[REDACTED]');
    expect(redacted).toContain('private_key=[REDACTED]');
    expect(redacted.match(/\[REDACTED\]/gu)).toHaveLength(5);
    expect(
      redactCredentialText(
        `{"api_key":"opaque json secret"} {'token':'opaque single secret'} ` +
          `{"Authorization":"Bearer opaque-json-secret"} ` +
          `{"accessKeyId":"opaque access id","secretAccessKey":"opaque access secret",` +
          `"clientSecret":"opaque client secret"} key="quoted secret value" ` +
          `client_secret='single quoted secret'`,
        4_000,
      ),
    ).toBe(
      `{"api_key":"[REDACTED]"} {'token':'[REDACTED]'} ` +
        `{"Authorization":"[REDACTED]"} ` +
        `{"accessKeyId":"[REDACTED]","secretAccessKey":"[REDACTED]",` +
        `"clientSecret":"[REDACTED]"} key=[REDACTED] client_secret=[REDACTED]`,
    );
  });

  it('normalizes C0, DEL and C1 controls without changing ordinary detail', () => {
    const controls = String.fromCharCode(0, 1, 9, 11, 12, 27, 31, 127, 128, 159);
    const redacted = redactCredentialText(`opaque${controls}key=control-secret${controls}tail`, 4_000);

    expect(
      [...redacted].some((character) => {
        const codePoint = character.codePointAt(0)!;
        return codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f);
      }),
    ).toBe(false);
    expect(redacted).not.toContain('control-secret');
    expect(redacted).toContain('key=[REDACTED]');
    const ordinary = '  Actionable detail: retry worker  42.  ';
    expect(redactCredentialText(ordinary, 4_000)).toBe(ordinary);
  });

  it('redacts only named metadata in failure events, including nested failures', () => {
    const payload = {
      detail: 'key=top-secret',
      error: { code: 'key=nested-code-secret', message: 'private_key=nested-secret' },
      failures: [{ detail: 'token=array-secret' }, 'key=array-string-secret'],
      summary: 'Model summary stays exact: token=answer-content',
    };
    expect(redactFailureEventPayload('role_run.verification_failed', payload)).toEqual({
      detail: 'key=[REDACTED]',
      error: { code: 'key=[REDACTED]', message: 'private_key=[REDACTED]' },
      failures: [{ detail: 'token=[REDACTED]' }, 'key=[REDACTED]'],
      summary: payload.summary,
    });
    const modelPayload = { delta: 'Model content stays exact: token=answer-content' };
    expect(redactFailureEventPayload('message.delta', modelPayload)).toBe(modelPayload);
    expect(
      redactFailureEventPayload('mission.remediation_planning', {
        failures: [{ detail: 'key=remediation-secret' }],
        summary: payload.summary,
      }),
    ).toEqual({
      failures: [{ detail: 'key=[REDACTED]' }],
      summary: payload.summary,
    });
    expect(
      redactFailureEventPayload('model.retry_scheduled', {
        errorMessage: 'key=retry-secret',
        finalError: 'private_key=final-secret',
      }),
    ).toEqual({ errorMessage: 'key=[REDACTED]', finalError: 'private_key=[REDACTED]' });

    let deep: Record<string, unknown> = { message: 'key=deep-secret' };
    for (let index = 0; index < 100; index += 1) deep = { error: deep };
    expect(() => redactFailureEventPayload('run.failed', deep)).not.toThrow();
    expect(JSON.stringify(redactFailureEventPayload('run.failed', deep))).not.toContain('deep-secret');
  });

  it('preserves an ordinary opaque correlation identifier', () => {
    expect(redactProviderCorrelation('gateway-request_123-opaque')).toBe('gateway-request_123-opaque');
    expect(redactCredentialText('Docs: https://docs.example.test/mcp.', 4_000)).toBe(
      'Docs: https://docs.example.test/mcp.',
    );
    expect(redactCredentialText('URL: https://user:pass@example.test/mcp', 4_000)).toBe(
      'URL: https://user:[REDACTED]@example.test/mcp',
    );
  });
});
