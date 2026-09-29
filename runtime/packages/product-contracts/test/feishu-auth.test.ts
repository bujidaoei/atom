import { describe, expect, it } from 'vitest';
import { Value } from 'typebox/value';

import {
  V3AuthSessionSchema,
  V3FeishuDesktopCompleteInputSchema,
  V3FeishuDesktopCompleteResponseSchema,
  V3FeishuDesktopStartInputSchema,
  V3FeishuDesktopStartResponseSchema,
} from '../src/feishu-auth.ts';

const principal = {
  userId: '11111111-1111-4111-8111-111111111111',
  workspaceId: '22222222-2222-4222-8222-222222222222',
  displayName: 'Feishu user',
  role: 'member' as const,
  permissions: [],
};

describe('Feishu auth product contracts', () => {
  it('keeps session projections redacted and validates the Desktop PKCE transaction shape', () => {
    expect(Value.Check(V3AuthSessionSchema, { authenticated: false })).toBe(true);
    expect(Value.Check(V3AuthSessionSchema, { authenticated: true, principal })).toBe(true);
    expect(Value.Check(V3AuthSessionSchema, { authenticated: true, principal, token: 'secret' })).toBe(false);

    const start = {
      transactionId: 'transaction-123456',
      codeChallenge: 'c'.repeat(43),
      nonce: 'nonce-1234567890',
    };
    expect(Value.Check(V3FeishuDesktopStartInputSchema, start)).toBe(true);
    expect(Value.Check(V3FeishuDesktopStartInputSchema, { ...start, codeChallenge: 'short' })).toBe(false);
    expect(Value.Check(V3FeishuDesktopStartInputSchema, { ...start, extra: true })).toBe(false);

    const startResponse = {
      transactionId: start.transactionId,
      clientId: 'cli_test',
      state: 'state-test-1234567890',
      authorizationUrl: 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?state=test',
      redirectUri: 'http://127.0.0.1:19840/callback',
      expiresAt: '2030-01-01T00:00:00.000Z',
    };
    expect(Value.Check(V3FeishuDesktopStartResponseSchema, startResponse)).toBe(true);
    expect(
      Value.Check(V3FeishuDesktopCompleteInputSchema, {
        transactionId: start.transactionId,
        codeVerifier: 'v'.repeat(43),
        nonce: start.nonce,
      }),
    ).toBe(true);
    expect(
      Value.Check(V3FeishuDesktopCompleteResponseSchema, {
        authenticated: true,
        principal,
        sessionToken: 's'.repeat(32),
      }),
    ).toBe(true);
    expect(Value.Check(V3FeishuDesktopCompleteResponseSchema, { status: 'pending', pollAfterMs: 750 })).toBe(
      true,
    );
    expect(Value.Check(V3FeishuDesktopCompleteResponseSchema, { status: 'denied' })).toBe(true);
    expect(Value.Check(V3FeishuDesktopCompleteResponseSchema, { status: 'expired', pollAfterMs: 750 })).toBe(
      true,
    );
    expect(
      Value.Check(V3FeishuDesktopCompleteResponseSchema, {
        status: 'authorized',
        principal,
        sessionToken: 's'.repeat(32),
      }),
    ).toBe(false);
  });
});
