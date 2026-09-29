import { createDecipheriv, createHash, timingSafeEqual } from 'node:crypto';

import type { V3ImChannelDiagnostic } from '../../product-contracts/src/v3.ts';

const FEISHU_ORIGIN = 'https://open.feishu.cn';
const MAX_CALLBACK_BYTES = 512 * 1024;
const MAX_CLOCK_SKEW_MS = 5 * 60_000;

export interface V3FeishuCredentials {
  appId: string;
  appSecret: string;
}

export interface V3FeishuCallbackSecurity {
  appId: string;
  verificationToken?: string;
  encryptKey?: string;
}

export interface V3FeishuCallbackHeaders {
  timestamp?: string;
  nonce?: string;
  signature?: string;
}

export interface V3FeishuMessageEvent {
  deliveryId: string;
  eventId: string;
  chatId: string;
  conversationType: 'group' | 'direct';
  messageType: string;
  text: string | null;
  occurredAt: string;
  senderOpenId?: string;
  senderUserId?: string;
}

export interface V3FeishuReceiveTarget {
  receiveIdType: 'chat_id' | 'open_id' | 'user_id';
  receiveId: string;
}

export interface V3DecodedFeishuCallback {
  body: Record<string, unknown>;
  challenge: string | null;
  message: V3FeishuMessageEvent | null;
}

function object(value: unknown, name: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Invalid Feishu ${name}`);
  }
  return value as Record<string, unknown>;
}

function nonEmpty(value: unknown, name: string, maximum = 10_000): string {
  if (typeof value !== 'string' || !value || value.length > maximum) {
    throw new Error(`Invalid Feishu ${name}`);
  }
  return value;
}

function equal(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left, 'utf8');
  const rightBytes = Buffer.from(right, 'utf8');
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function json(raw: Buffer): Record<string, unknown> {
  if (raw.byteLength < 2 || raw.byteLength > MAX_CALLBACK_BYTES) {
    throw new Error('Invalid Feishu callback size');
  }
  try {
    return object(JSON.parse(raw.toString('utf8')), 'callback body');
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Invalid Feishu')) throw error;
    throw new Error('Invalid Feishu callback JSON', { cause: error });
  }
}

/** Implements Feishu's documented SHA-256(timestamp + nonce + encrypt_key + raw body) check. */
export function v3FeishuCallbackSignature(
  timestamp: string,
  nonce: string,
  encryptKey: string,
  rawBody: Uint8Array,
): string {
  return createHash('sha256')
    .update(timestamp, 'utf8')
    .update(nonce, 'utf8')
    .update(encryptKey, 'utf8')
    .update(rawBody)
    .digest('hex');
}

/** Implements Feishu's documented AES-256-CBC encrypted callback envelope. */
export function decryptV3FeishuCallback(encrypted: string, encryptKey: string): Buffer {
  const sealed = Buffer.from(encrypted, 'base64');
  if (sealed.byteLength < 32 || sealed.byteLength % 16 !== 0) {
    throw new Error('Invalid Feishu encrypted callback');
  }
  try {
    const key = createHash('sha256').update(encryptKey, 'utf8').digest();
    const decipher = createDecipheriv('aes-256-cbc', key, sealed.subarray(0, 16));
    return Buffer.concat([decipher.update(sealed.subarray(16)), decipher.final()]);
  } catch {
    throw new Error('Invalid Feishu encrypted callback');
  }
}

function parseMessage(body: Record<string, unknown>, appId: string): V3FeishuMessageEvent | null {
  const header = object(body.header, 'event header');
  if (nonEmpty(header.app_id, 'app id', 300) !== appId) throw new Error('Feishu callback app id mismatch');
  if (header.event_type !== 'im.message.receive_v1') return null;
  const event = object(body.event, 'event');
  const message = object(event.message, 'message');
  const chatId = nonEmpty(message.chat_id, 'chat id', 500);
  const messageType = nonEmpty(message.message_type, 'message type', 100);
  const deliveryId = nonEmpty(message.message_id, 'message id', 300);
  const eventId = nonEmpty(header.event_id, 'event id', 300);
  const createTime = nonEmpty(message.create_time ?? header.create_time, 'create time', 30);
  const occurred = Number(createTime);
  if (!Number.isSafeInteger(occurred) || occurred <= 0) throw new Error('Invalid Feishu create time');
  let senderOpenId: string | undefined;
  let senderUserId: string | undefined;
  if (event.sender && typeof event.sender === 'object' && !Array.isArray(event.sender)) {
    const sender = object(event.sender, 'sender');
    if (sender.sender_id && typeof sender.sender_id === 'object' && !Array.isArray(sender.sender_id)) {
      const senderId = object(sender.sender_id, 'sender id');
      if (senderId.open_id !== undefined) {
        senderOpenId = nonEmpty(senderId.open_id, 'sender open id', 500);
      }
      if (senderId.user_id !== undefined) {
        senderUserId = nonEmpty(senderId.user_id, 'sender user id', 500);
      }
    }
  }
  let text: string | null = null;
  if (messageType === 'text') {
    const content = object(
      JSON.parse(nonEmpty(message.content, 'message content', 200_000)),
      'message content',
    );
    text = nonEmpty(content.text, 'text message', 150_000).trim();
    if (!text) throw new Error('Invalid Feishu text message');
  }
  return {
    deliveryId,
    eventId,
    chatId,
    conversationType: message.chat_type === 'p2p' ? 'direct' : 'group',
    messageType,
    text,
    occurredAt: new Date(occurred).toISOString(),
    ...(senderOpenId ? { senderOpenId } : {}),
    ...(senderUserId ? { senderUserId } : {}),
  };
}

/** The official SDK flattens header/event fields after authenticating its WebSocket.
 * Never expose this decoder as an unauthenticated HTTP endpoint.
 */
export function decodeV3FeishuSocketMessage(
  event: Record<string, unknown>,
  appId: string,
): V3FeishuMessageEvent | null {
  const sender = object(event.sender, 'sender');
  if (sender.sender_type !== 'user') return null;
  return parseMessage({ header: event, event }, appId);
}

export function decodeV3FeishuCallback(
  rawBody: Uint8Array,
  headers: V3FeishuCallbackHeaders,
  security: V3FeishuCallbackSecurity,
  now = Date.now(),
): V3DecodedFeishuCallback {
  if (!security.verificationToken && !security.encryptKey) {
    throw new Error('Feishu callback security is not configured');
  }
  const raw = Buffer.from(rawBody);
  let body = json(raw);
  if (security.encryptKey) {
    const timestamp = nonEmpty(headers.timestamp, 'request timestamp', 30);
    const nonce = nonEmpty(headers.nonce, 'request nonce', 300);
    const signature = nonEmpty(headers.signature, 'request signature', 128);
    const timestampMs = Number(timestamp) * 1_000;
    if (!Number.isSafeInteger(timestampMs) || Math.abs(now - timestampMs) > MAX_CLOCK_SKEW_MS) {
      throw new Error('Expired Feishu callback timestamp');
    }
    const expected = v3FeishuCallbackSignature(timestamp, nonce, security.encryptKey, raw);
    if (!equal(expected, signature)) throw new Error('Invalid Feishu callback signature');
    if ('encrypt' in body) {
      body = json(decryptV3FeishuCallback(nonEmpty(body.encrypt, 'encrypted payload'), security.encryptKey));
    }
  }
  if (security.verificationToken) {
    const header =
      body.header && typeof body.header === 'object' ? object(body.header, 'event header') : null;
    const supplied = typeof body.token === 'string' ? body.token : header?.token;
    if (typeof supplied !== 'string' || !equal(supplied, security.verificationToken)) {
      throw new Error('Invalid Feishu verification token');
    }
  }
  const challenge = typeof body.challenge === 'string' ? nonEmpty(body.challenge, 'challenge', 2_000) : null;
  return { body, challenge, message: challenge ? null : parseMessage(body, security.appId) };
}

interface FeishuTokenResponse {
  code?: number;
  msg?: string;
  tenant_access_token?: string;
  expire?: number;
}

interface FeishuSendMessageResponse {
  code?: number;
  msg?: string;
  data?: { message_id?: string };
}

export async function requestV3FeishuTenantAccessToken(
  credentials: V3FeishuCredentials,
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetchImpl(`${FEISHU_ORIGIN}/open-apis/auth/v3/tenant_access_token/internal/`, {
    method: 'POST',
    headers: { 'content-type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ app_id: credentials.appId, app_secret: credentials.appSecret }),
    ...(signal ? { signal } : {}),
  });
  const payload = (await response.json()) as FeishuTokenResponse;
  if (!response.ok || payload.code !== 0 || !payload.tenant_access_token) {
    throw new Error(
      `Feishu credential validation failed${payload.code === undefined ? '' : ` (${payload.code})`}`,
    );
  }
  return payload.tenant_access_token;
}

export async function sendV3FeishuTextMessage(
  credentials: V3FeishuCredentials,
  target: V3FeishuReceiveTarget,
  text: string,
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
  messageUuid?: string,
): Promise<string | null> {
  if (!['chat_id', 'open_id', 'user_id'].includes(target.receiveIdType)) {
    throw new Error('Invalid Feishu receive id type');
  }
  const receiveId = nonEmpty(target.receiveId, 'receive id', 500);
  const content = nonEmpty(text.trim(), 'outbound text', 150_000);
  const token = await requestV3FeishuTenantAccessToken(credentials, fetchImpl, signal);
  const response = await fetchImpl(
    `${FEISHU_ORIGIN}/open-apis/im/v1/messages?receive_id_type=${target.receiveIdType}`,
    {
      method: 'POST',
      headers: {
        authorization: `Bearer ${token}`,
        'content-type': 'application/json; charset=utf-8',
      },
      body: JSON.stringify({
        receive_id: receiveId,
        msg_type: 'text',
        content: JSON.stringify({ text: content }),
        ...(messageUuid ? { uuid: nonEmpty(messageUuid, 'message UUID', 50) } : {}),
      }),
      ...(signal ? { signal } : {}),
    },
  );
  const payload = (await response.json()) as FeishuSendMessageResponse;
  if (!response.ok || payload.code !== 0) {
    throw new Error(
      `Feishu message delivery failed${payload.code === undefined ? '' : ` (${payload.code})`}`,
    );
  }
  return payload.data?.message_id ?? null;
}

export function parseV3FeishuReceiveTarget(value: string): V3FeishuReceiveTarget {
  const parsed = JSON.parse(value) as unknown;
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const target = parsed as Record<string, unknown>;
    if (
      ['chat_id', 'open_id', 'user_id'].includes(String(target.receiveIdType)) &&
      typeof target.receiveId === 'string'
    ) {
      return {
        receiveIdType: target.receiveIdType as V3FeishuReceiveTarget['receiveIdType'],
        receiveId: nonEmpty(target.receiveId, 'receive id', 500),
      };
    }
  }
  throw new Error('Stored Feishu receive target is invalid');
}

export async function diagnoseV3FeishuChannel(
  credentials: V3FeishuCredentials,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 10_000,
): Promise<V3ImChannelDiagnostic> {
  const checkedAt = new Date().toISOString();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await requestV3FeishuTenantAccessToken(credentials, fetchImpl, controller.signal);
    return { status: 'ready', message: 'Feishu credentials validated successfully.', checkedAt };
  } catch (error) {
    const message =
      error instanceof Error && error.name === 'AbortError'
        ? 'Feishu credential validation timed out.'
        : error instanceof Error
          ? error.message
          : 'Feishu credential validation failed.';
    return { status: 'degraded', message, checkedAt };
  } finally {
    clearTimeout(timeout);
  }
}
