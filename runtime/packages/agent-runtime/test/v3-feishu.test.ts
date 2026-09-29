import { createCipheriv, createHash } from 'node:crypto';

import { describe, expect, it, vi } from 'vitest';

import {
  decodeV3FeishuCallback,
  diagnoseV3FeishuChannel,
  parseV3FeishuReceiveTarget,
  sendV3FeishuTextMessage,
  v3FeishuCallbackSignature,
} from '../src/v3-feishu.ts';

function encryptCallback(body: object, encryptKey: string, iv = Buffer.alloc(16, 7)): string {
  const key = createHash('sha256').update(encryptKey, 'utf8').digest();
  const cipher = createCipheriv('aes-256-cbc', key, iv);
  return Buffer.concat([iv, cipher.update(JSON.stringify(body), 'utf8'), cipher.final()]).toString('base64');
}

describe('V3 Feishu protocol boundary', () => {
  it('verifies a plaintext challenge with the configured Verification Token', () => {
    const decoded = decodeV3FeishuCallback(
      Buffer.from(JSON.stringify({ challenge: 'challenge-code', token: 'verification-token' })),
      {},
      { appId: 'cli_example', verificationToken: 'verification-token' },
    );
    expect(decoded).toMatchObject({ challenge: 'challenge-code', message: null });
    expect(() =>
      decodeV3FeishuCallback(
        Buffer.from(JSON.stringify({ challenge: 'challenge-code', token: 'wrong-token' })),
        {},
        { appId: 'cli_example', verificationToken: 'verification-token' },
      ),
    ).toThrow('Invalid Feishu verification token');
  });

  it('verifies the raw body signature, decrypts the envelope, and uses message_id for delivery identity', () => {
    const encryptKey = 'documented-encrypt-key';
    const timestamp = '1786752000';
    const event = {
      schema: '2.0',
      header: {
        event_id: 'event-1',
        event_type: 'im.message.receive_v1',
        create_time: '1786752000000',
        token: 'verification-token',
        app_id: 'cli_example',
      },
      event: {
        sender: {
          sender_id: { open_id: 'ou_sender_1', user_id: 'user_sender_1' },
        },
        message: {
          message_id: 'om_message_1',
          chat_id: 'oc_chat_1',
          chat_type: 'group',
          message_type: 'text',
          content: JSON.stringify({ text: '请核对真实数据' }),
          create_time: '1786752000000',
        },
      },
    };
    const raw = Buffer.from(JSON.stringify({ encrypt: encryptCallback(event, encryptKey) }));
    const signature = v3FeishuCallbackSignature(timestamp, 'nonce-1', encryptKey, raw);
    const decoded = decodeV3FeishuCallback(
      raw,
      { timestamp, nonce: 'nonce-1', signature },
      { appId: 'cli_example', verificationToken: 'verification-token', encryptKey },
      1_786_752_000_000,
    );
    expect(decoded.message).toEqual({
      deliveryId: 'om_message_1',
      eventId: 'event-1',
      chatId: 'oc_chat_1',
      conversationType: 'group',
      messageType: 'text',
      text: '请核对真实数据',
      occurredAt: '2026-08-15T00:00:00.000Z',
      senderOpenId: 'ou_sender_1',
      senderUserId: 'user_sender_1',
    });
    expect(() =>
      decodeV3FeishuCallback(
        raw,
        { timestamp, nonce: 'nonce-1', signature: '0'.repeat(64) },
        { appId: 'cli_example', encryptKey },
        1_786_752_000_000,
      ),
    ).toThrow('Invalid Feishu callback signature');
  });

  it('performs a real-shaped tenant token request without returning the token', async () => {
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({ app_id: 'cli_example', app_secret: 'raw-secret' });
      return new Response(
        JSON.stringify({ code: 0, msg: 'ok', tenant_access_token: 'tenant-token', expire: 7200 }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }) as typeof fetch;
    const result = await diagnoseV3FeishuChannel(
      { appId: 'cli_example', appSecret: 'raw-secret' },
      fetchImpl,
    );
    expect(result).toMatchObject({ status: 'ready', message: 'Feishu credentials validated successfully.' });
    expect(JSON.stringify(result)).not.toContain('tenant-token');
  });

  it('sends text to the documented chat_id endpoint without exposing the tenant token', async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (String(url).includes('/auth/v3/tenant_access_token/internal/')) {
        return new Response(JSON.stringify({ code: 0, tenant_access_token: 'tenant-token', expire: 7200 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      expect(String(url)).toBe('https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id');
      expect(init?.headers).toMatchObject({ authorization: 'Bearer tenant-token' });
      expect(JSON.parse(String(init?.body))).toEqual({
        receive_id: 'oc_chat_1',
        msg_type: 'text',
        content: JSON.stringify({ text: 'DeepSeek 回复' }),
        uuid: 'durable-run-reply-id',
      });
      return new Response(JSON.stringify({ code: 0, data: { message_id: 'om_reply_1' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }) as typeof fetch;

    await expect(
      sendV3FeishuTextMessage(
        { appId: 'cli_example', appSecret: 'raw-secret' },
        { receiveIdType: 'chat_id', receiveId: 'oc_chat_1' },
        'DeepSeek 回复',
        fetchImpl,
        undefined,
        'durable-run-reply-id',
      ),
    ).resolves.toBe('om_reply_1');
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('sends direct messages by open_id and parses encrypted receive targets without exposing them', async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (String(url).includes('/auth/v3/tenant_access_token/internal/')) {
        return new Response(JSON.stringify({ code: 0, tenant_access_token: 'tenant-token', expire: 7200 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      expect(String(url)).toBe('https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id');
      expect(JSON.parse(String(init?.body))).toMatchObject({ receive_id: 'ou_direct_1' });
      return new Response(JSON.stringify({ code: 0, data: { message_id: 'om_reply_2' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }) as typeof fetch;

    const target = parseV3FeishuReceiveTarget(
      JSON.stringify({ receiveIdType: 'open_id', receiveId: 'ou_direct_1' }),
    );
    expect(target).toEqual({ receiveIdType: 'open_id', receiveId: 'ou_direct_1' });
    await expect(
      sendV3FeishuTextMessage(
        { appId: 'cli_example', appSecret: 'raw-secret' },
        target,
        'Direct reply',
        fetchImpl,
      ),
    ).resolves.toBe('om_reply_2');
    expect(() => parseV3FeishuReceiveTarget('oc_unstructured_chat')).toThrow(
      /Stored Feishu receive target is invalid|JSON/iu,
    );
  });
});
