import type { V3ImChannelDiagnostic } from '../../product-contracts/src/v3.ts';

const DINGTALK_OPEN_CONNECTION_URL = 'https://api.dingtalk.com/v1.0/gateway/connections/open';
const DINGTALK_DIAGNOSTIC_TIMEOUT_MS = 10_000;

export interface V3DingTalkCredentials {
  appKey: string;
  appSecret: string;
}

function failedDiagnostic(status: 'degraded' | 'unavailable'): V3ImChannelDiagnostic {
  return {
    status,
    message:
      status === 'degraded'
        ? 'DingTalk connection failed. Check the Client ID, Client Secret, and provider access, then retry.'
        : 'DingTalk is temporarily unreachable. Check network access, then retry.',
    checkedAt: new Date().toISOString(),
  };
}

export async function diagnoseV3DingTalkChannel(
  credentials: V3DingTalkCredentials,
  fetchImpl: typeof fetch = fetch,
): Promise<V3ImChannelDiagnostic> {
  if (!credentials.appKey.trim() || !credentials.appSecret.trim()) return failedDiagnostic('degraded');
  try {
    const response = await fetchImpl(DINGTALK_OPEN_CONNECTION_URL, {
      method: 'POST',
      headers: { accept: 'application/json', 'content-type': 'application/json' },
      body: JSON.stringify({
        clientId: credentials.appKey,
        clientSecret: credentials.appSecret,
        subscriptions: [],
        ua: 'workdude-v3',
        localIp: '',
      }),
      signal: AbortSignal.timeout(DINGTALK_DIAGNOSTIC_TIMEOUT_MS),
    });
    if (!response.ok) return failedDiagnostic('degraded');
    const body = (await response.json()) as Record<string, unknown>;
    if (
      typeof body.endpoint !== 'string' ||
      !body.endpoint ||
      typeof body.ticket !== 'string' ||
      !body.ticket
    ) {
      return failedDiagnostic('degraded');
    }
    return {
      status: 'ready',
      message: 'DingTalk credentials and Stream connection validated successfully.',
      checkedAt: new Date().toISOString(),
    };
  } catch {
    return failedDiagnostic('unavailable');
  }
}
