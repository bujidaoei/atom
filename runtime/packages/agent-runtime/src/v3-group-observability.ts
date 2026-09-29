import type { V3ModelUsage } from '../../product-contracts/src/v3.ts';
import { redactProviderCorrelation } from '../../product-contracts/src/provider-correlation.ts';

interface V3GroupAttemptEvent {
  type: string;
  payload: Record<string, unknown>;
}

const COMPLETED_ATTEMPT_EVENTS = new Set(['leader.attempt.completed', 'role_run.attempt.completed']);

function usageFrom(value: unknown): V3ModelUsage | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const usage = value as Record<string, unknown>;
  if (
    typeof usage.inputTokens !== 'number' ||
    typeof usage.outputTokens !== 'number' ||
    typeof usage.totalTokens !== 'number'
  ) {
    return undefined;
  }
  return {
    inputTokens: usage.inputTokens,
    outputTokens: usage.outputTokens,
    totalTokens: usage.totalTokens,
    ...(typeof usage.cacheReadTokens === 'number' ? { cacheReadTokens: usage.cacheReadTokens } : {}),
    ...(typeof usage.cacheWriteTokens === 'number' ? { cacheWriteTokens: usage.cacheWriteTokens } : {}),
    ...(typeof usage.totalCost === 'number' ? { totalCost: usage.totalCost } : {}),
  };
}

export function summarizeV3GroupAttemptObservability(events: readonly V3GroupAttemptEvent[]): {
  usage: V3ModelUsage | null;
  providerCorrelationId: string | null;
} {
  const total: V3ModelUsage = { inputTokens: 0, outputTokens: 0, totalTokens: 0 };
  let hasUsage = false;
  let hasCacheReadTokens = false;
  let hasCacheWriteTokens = false;
  let hasTotalCost = false;
  let providerCorrelationId: string | null = null;
  for (const event of events) {
    if (!COMPLETED_ATTEMPT_EVENTS.has(event.type)) continue;
    const usage = usageFrom(event.payload.usage);
    if (usage) {
      hasUsage = true;
      total.inputTokens += usage.inputTokens;
      total.outputTokens += usage.outputTokens;
      total.totalTokens += usage.totalTokens;
      if (usage.cacheReadTokens !== undefined) {
        hasCacheReadTokens = true;
        total.cacheReadTokens = (total.cacheReadTokens ?? 0) + usage.cacheReadTokens;
      }
      if (usage.cacheWriteTokens !== undefined) {
        hasCacheWriteTokens = true;
        total.cacheWriteTokens = (total.cacheWriteTokens ?? 0) + usage.cacheWriteTokens;
      }
      if (usage.totalCost !== undefined) {
        hasTotalCost = true;
        total.totalCost = (total.totalCost ?? 0) + usage.totalCost;
      }
    }
    if (typeof event.payload.providerCorrelationId === 'string') {
      providerCorrelationId = redactProviderCorrelation(event.payload.providerCorrelationId);
    }
  }
  if (!hasCacheReadTokens) delete total.cacheReadTokens;
  if (!hasCacheWriteTokens) delete total.cacheWriteTokens;
  if (!hasTotalCost) delete total.totalCost;
  return { usage: hasUsage ? total : null, providerCorrelationId };
}
