import {
  redactKnowledgeFailureDetail,
  redactRunFailureDetail,
} from '../../product-contracts/src/provider-correlation.ts';

export type RunFailureCategory =
  | 'configuration_missing'
  | 'gateway_authentication'
  | 'gateway_authorization'
  | 'model_unavailable'
  | 'provider_rate_limit'
  | 'provider_budget'
  | 'provider_context_limit'
  | 'provider_rejected'
  | 'provider_timeout'
  | 'provider_stream'
  | 'provider_unavailable'
  | 'provider_malformed'
  | 'runtime_start'
  | 'sandbox_unavailable'
  | 'sandbox_policy'
  | 'tool_failed'
  | 'storage_failed'
  | 'cancelled'
  | 'internal';

function failureMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

function failureHasName(cause: unknown, expectedName: string): boolean {
  let current = cause;
  for (let depth = 0; depth < 8 && current instanceof Error; depth += 1) {
    if (current.name === expectedName) return true;
    current = current.cause;
  }
  return false;
}

export function classifyRunFailure(cause: unknown): RunFailureCategory {
  const message = failureMessage(cause);
  if (message === 'Run status observation failed') return 'internal';
  if (failureHasName(cause, 'ObjectStorageReadError')) return 'storage_failed';
  // HttpSandboxClient identifies its HTTP origin. Preserve it before applying
  // generic provider status heuristics (including 401, 429 and 504).
  if (/^Sandbox Broker returned [45]\d\d$/u.test(message)) return 'sandbox_unavailable';
  if (failureHasName(cause, 'TimeoutError')) return 'provider_timeout';
  if (failureHasName(cause, 'AbortError')) return 'cancelled';
  if (
    /model security|model policy/iu.test(message) &&
    /does not allow|not allowed|disallow|denied|blocked/iu.test(message)
  ) {
    return 'model_unavailable';
  }
  if (/content policy/iu.test(message)) return 'provider_rejected';
  if (/\b504\b|timeout|timed out|deadline exceeded/iu.test(message)) return 'provider_timeout';
  if (/abort|cancel/iu.test(message)) return 'cancelled';
  if (
    /missing|not configured|is required|请先.*配置/iu.test(message) &&
    /api.?key|litellm|gateway|configuration|master.?key/iu.test(message)
  ) {
    return 'configuration_missing';
  }
  if (
    /sandbox|broker/iu.test(message) &&
    /unavailable|not configured|disabled|cannot connect|returned\s+5\d\d|failed to create|seccomp/iu.test(
      message,
    )
  ) {
    return 'sandbox_unavailable';
  }
  if (/policy|approval|not permitted|rejected command/iu.test(message)) return 'sandbox_policy';
  if (/tool/iu.test(message) && /failed|error|exit/iu.test(message)) return 'tool_failed';
  if (/storage|object store|\bcos\b|\bs3\b/iu.test(message)) return 'storage_failed';
  if (/401|authentication failed|invalid api.?key|invalid key/iu.test(message)) {
    return 'gateway_authentication';
  }
  if (/403|authorization failed|forbidden|not authorized/iu.test(message)) {
    return 'gateway_authorization';
  }
  if (/model/iu.test(message) && /not found|not available|unavailable|unsupported/iu.test(message)) {
    return 'model_unavailable';
  }
  if (/budget|quota|insufficient credits?|spend limit/iu.test(message)) return 'provider_budget';
  if (/429|rate.?limit|too many requests/iu.test(message)) return 'provider_rate_limit';
  if (/context/iu.test(message) && /length|limit|too large|exceed|maximum/iu.test(message)) {
    return 'provider_context_limit';
  }
  if (/malformed|invalid json|invalid structured|schema validation|empty response/iu.test(message)) {
    return 'provider_malformed';
  }
  if (/\b5\d\d\b|service unavailable|bad gateway|gateway unavailable|upstream unavailable/iu.test(message)) {
    return 'provider_unavailable';
  }
  if (/400|404|409|413|422|provider rejected|invalid request/iu.test(message)) {
    return 'provider_rejected';
  }
  if (/fetch|network|socket|stream|econn|epipe|connection/iu.test(message)) return 'provider_stream';
  if (/runtime|session|configured model not found|startup|start failed/iu.test(message))
    return 'runtime_start';
  return 'internal';
}

export function runFailureDetail(cause: unknown): string {
  return redactRunFailureDetail(failureMessage(cause));
}

export function knowledgeFailureDetail(cause: unknown): string {
  return redactKnowledgeFailureDetail(failureMessage(cause), 2_000);
}
