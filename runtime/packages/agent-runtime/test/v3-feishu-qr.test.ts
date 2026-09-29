import { describe, expect, it, vi } from 'vitest';

import { V3FeishuQrRegistrationBroker } from '../src/v3-feishu-qr.ts';

describe('V3 Feishu QR registration broker', () => {
  it('uses the observed init/begin/poll protocol and keeps credentials server-side', async () => {
    const requests: URLSearchParams[] = [];
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = new URLSearchParams(String(init?.body));
      requests.push(body);
      if (body.get('action') === 'init') return new Response(JSON.stringify({ ok: true }));
      if (body.get('action') === 'begin') {
        return new Response(
          JSON.stringify({
            verification_uri_complete: 'https://accounts.feishu.cn/device?code=verification-code',
            device_code: 'device-code',
            interval: 2,
            expire_in: 600,
          }),
        );
      }
      return new Response(
        JSON.stringify(
          requests.filter((request) => request.get('action') === 'poll').length === 1
            ? { error: 'authorization_pending' }
            : { client_id: 'cli_qr_app', client_secret: 'qr-app-secret' },
        ),
      );
    }) as typeof fetch;
    const broker = new V3FeishuQrRegistrationBroker(fetchImpl, () => Date.parse('2026-08-16T00:00:00Z'));

    const session = await broker.start('workspace:user');
    expect(session).toMatchObject({ pollAfterMs: 2_000, expiresAt: '2026-08-16T00:10:00.000Z' });
    expect(JSON.stringify(session)).not.toContain('device-code');
    await expect(broker.poll('workspace:user', session.sessionId)).resolves.toEqual({
      status: 'pending',
      pollAfterMs: 2_000,
    });
    const authorized = await broker.poll('workspace:user', session.sessionId);
    expect(authorized).toEqual({
      status: 'authorized',
      pollAfterMs: 2_000,
      credentials: { appId: 'cli_qr_app', appSecret: 'qr-app-secret' },
    });
    expect(requests.map((request) => request.get('action'))).toEqual(['init', 'begin', 'poll', 'poll']);
    expect(Object.fromEntries(requests[1]!)).toEqual({
      action: 'begin',
      archetype: 'PersonalAgent',
      auth_method: 'client_secret',
      request_user_info: 'open_id',
    });
    broker.complete('workspace:user', session.sessionId);
    await expect(broker.poll('workspace:user', session.sessionId)).rejects.toThrow(
      'Feishu QR session not found or expired',
    );
  });

  it('handles slow down, denial, expiry, ownership, and verification URL origin', async () => {
    const results = [{ error: 'slow_down' }, { error: 'access_denied' }, { error: 'expired_token' }];
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = new URLSearchParams(String(init?.body));
      if (body.get('action') === 'init') return new Response('{}');
      if (body.get('action') === 'begin') {
        return new Response(
          JSON.stringify({
            verification_uri_complete: 'https://accounts.feishu.cn/device',
            device_code: `device-${Math.random()}`,
            interval: 1,
          }),
        );
      }
      return new Response(JSON.stringify(results.shift()));
    }) as typeof fetch;
    const broker = new V3FeishuQrRegistrationBroker(fetchImpl);
    const slow = await broker.start('owner');
    await expect(broker.poll('other', slow.sessionId)).rejects.toThrow('not found or expired');
    await expect(broker.poll('owner', slow.sessionId)).resolves.toEqual({
      status: 'pending',
      pollAfterMs: 6_000,
    });
    const denied = await broker.start('owner');
    await expect(broker.poll('owner', denied.sessionId)).resolves.toMatchObject({ status: 'denied' });
    const expired = await broker.start('owner');
    await expect(broker.poll('owner', expired.sessionId)).resolves.toMatchObject({ status: 'expired' });

    const badOrigin = new V3FeishuQrRegistrationBroker(
      vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
        const action = new URLSearchParams(String(init?.body)).get('action');
        return new Response(
          action === 'begin'
            ? JSON.stringify({
                verification_uri_complete: 'https://example.com/phishing',
                device_code: 'device-code',
              })
            : '{}',
        );
      }) as typeof fetch,
    );
    await expect(badOrigin.start('owner')).rejects.toThrow('verification URL origin');
  });
});
