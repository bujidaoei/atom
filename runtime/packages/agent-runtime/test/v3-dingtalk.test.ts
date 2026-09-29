import { describe, expect, it, vi } from 'vitest';

import { diagnoseV3DingTalkChannel } from '../src/v3-dingtalk.ts';

describe('V3 DingTalk protocol boundary', () => {
  it('uses the official Stream open-connection shape without returning credentials or tickets', async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toBe('https://api.dingtalk.com/v1.0/gateway/connections/open');
      expect(JSON.parse(String(init?.body))).toEqual({
        clientId: 'ding-client-id',
        clientSecret: 'raw-secret',
        subscriptions: [],
        ua: 'workdude-v3',
        localIp: '',
      });
      return new Response(JSON.stringify({ endpoint: 'wss://api.dingtalk.com/connect', ticket: 'ticket' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }) as typeof fetch;

    const result = await diagnoseV3DingTalkChannel(
      { appKey: 'ding-client-id', appSecret: 'raw-secret' },
      fetchImpl,
    );
    expect(result).toMatchObject({
      status: 'ready',
      message: 'DingTalk credentials and Stream connection validated successfully.',
    });
    expect(JSON.stringify(result)).not.toMatch(/raw-secret|ticket/u);
  });

  it('categorizes invalid credentials and network failures without exposing provider bodies', async () => {
    const invalid = await diagnoseV3DingTalkChannel(
      { appKey: 'ding-invalid', appSecret: 'private-value' },
      vi.fn(
        async () => new Response('provider says private-value is invalid', { status: 401 }),
      ) as typeof fetch,
    );
    expect(invalid).toMatchObject({ status: 'degraded' });
    expect(JSON.stringify(invalid)).not.toContain('private-value');

    const offline = await diagnoseV3DingTalkChannel(
      { appKey: 'ding-offline', appSecret: 'private-value' },
      vi.fn(async () => {
        throw new Error('network failed with private-value');
      }) as typeof fetch,
    );
    expect(offline).toMatchObject({ status: 'unavailable' });
    expect(JSON.stringify(offline)).not.toContain('private-value');
  });
});
