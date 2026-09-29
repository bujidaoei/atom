import { randomUUID } from 'node:crypto';

const FEISHU_REGISTRATION_URL = 'https://accounts.feishu.cn/oauth/v1/app/registration';
const DEFAULT_POLL_AFTER_MS = 5_000;
const DEFAULT_EXPIRES_IN_SECONDS = 600;
const REQUEST_TIMEOUT_MS = 15_000;

type RegistrationPayload = Record<string, unknown>;

interface RegistrationSession {
  ownerKey: string;
  deviceCode: string;
  verificationUrl: string;
  pollAfterMs: number;
  expiresAt: number;
  credentials?: { appId: string; appSecret: string };
}

export interface V3FeishuQrSession {
  sessionId: string;
  verificationUrl: string;
  pollAfterMs: number;
  expiresAt: string;
}

export type V3FeishuQrPollResult =
  | { status: 'pending' | 'denied' | 'expired'; pollAfterMs: number }
  | { status: 'authorized'; pollAfterMs: number; credentials: { appId: string; appSecret: string } };

function string(value: unknown, name: string, maximum = 4_000): string {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum) {
    throw new Error(`Invalid Feishu QR ${name}`);
  }
  return value.trim();
}

function seconds(value: unknown, fallback: number): number {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) && parsed >= 1 && parsed <= 3_600 ? Math.ceil(parsed) : fallback;
}

function verificationUrl(value: unknown): string {
  const raw = string(value, 'verification URL', 8_000);
  const parsed = new URL(raw);
  if (
    parsed.protocol !== 'https:' ||
    (parsed.hostname !== 'accounts.feishu.cn' && parsed.hostname !== 'open.feishu.cn')
  ) {
    throw new Error('Invalid Feishu QR verification URL origin');
  }
  return parsed.toString();
}

async function registrationRequest(
  input: Record<string, string>,
  operation: 'init' | 'begin' | 'poll',
  fetchImpl: typeof fetch,
): Promise<RegistrationPayload> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetchImpl(FEISHU_REGISTRATION_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(input).toString(),
      signal: controller.signal,
    });
    const text = await response.text();
    let payload: unknown;
    try {
      payload = JSON.parse(text);
    } catch (error) {
      throw new Error(`Feishu QR ${operation} returned invalid JSON`, { cause: error });
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error(`Feishu QR ${operation} returned an invalid response`);
    }
    if (!response.ok && operation !== 'poll') {
      throw new Error(`Feishu QR ${operation} failed with HTTP ${response.status}`);
    }
    return payload as RegistrationPayload;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`Feishu QR ${operation} timed out`, { cause: error });
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export class V3FeishuQrRegistrationBroker {
  private readonly sessions = new Map<string, RegistrationSession>();

  constructor(
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly now: () => number = Date.now,
  ) {}

  async start(ownerKey: string): Promise<V3FeishuQrSession> {
    this.removeExpired();
    await registrationRequest({ action: 'init' }, 'init', this.fetchImpl);
    const result = await registrationRequest(
      {
        action: 'begin',
        archetype: 'PersonalAgent',
        auth_method: 'client_secret',
        request_user_info: 'open_id',
      },
      'begin',
      this.fetchImpl,
    );
    const pollAfterMs = seconds(result.interval, DEFAULT_POLL_AFTER_MS / 1_000) * 1_000;
    const expiresAt =
      this.now() + seconds(result.expire_in ?? result.expires_in, DEFAULT_EXPIRES_IN_SECONDS) * 1_000;
    const sessionId = randomUUID();
    const session: RegistrationSession = {
      ownerKey: string(ownerKey, 'owner', 500),
      deviceCode: string(result.device_code, 'device code'),
      verificationUrl: verificationUrl(result.verification_uri_complete),
      pollAfterMs,
      expiresAt,
    };
    this.sessions.set(sessionId, session);
    return {
      sessionId,
      verificationUrl: session.verificationUrl,
      pollAfterMs,
      expiresAt: new Date(expiresAt).toISOString(),
    };
  }

  async poll(ownerKey: string, sessionId: string): Promise<V3FeishuQrPollResult> {
    this.removeExpired();
    const session = this.sessions.get(sessionId);
    if (!session || session.ownerKey !== ownerKey) throw new Error('Feishu QR session not found or expired');
    if (session.credentials) {
      return { status: 'authorized', pollAfterMs: session.pollAfterMs, credentials: session.credentials };
    }
    const result = await registrationRequest(
      { action: 'poll', device_code: session.deviceCode },
      'poll',
      this.fetchImpl,
    );
    if (result.client_id && result.client_secret) {
      session.credentials = {
        appId: string(result.client_id, 'application id'),
        appSecret: string(result.client_secret, 'application secret', 65_536),
      };
      return { status: 'authorized', pollAfterMs: session.pollAfterMs, credentials: session.credentials };
    }
    if (result.error === 'slow_down') session.pollAfterMs = Math.min(session.pollAfterMs + 5_000, 60_000);
    if (result.error === 'expired_token') {
      this.sessions.delete(sessionId);
      return { status: 'expired', pollAfterMs: session.pollAfterMs };
    }
    if (result.error === 'access_denied') {
      this.sessions.delete(sessionId);
      return { status: 'denied', pollAfterMs: session.pollAfterMs };
    }
    if (result.error && result.error !== 'authorization_pending' && result.error !== 'slow_down') {
      throw new Error(`Feishu QR poll failed: ${string(result.error, 'poll error', 300)}`);
    }
    return { status: 'pending', pollAfterMs: session.pollAfterMs };
  }

  complete(ownerKey: string, sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (session?.ownerKey === ownerKey) this.sessions.delete(sessionId);
  }

  private removeExpired(): void {
    const now = this.now();
    for (const [sessionId, session] of this.sessions) {
      if (session.expiresAt <= now) this.sessions.delete(sessionId);
    }
  }
}
