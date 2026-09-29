import type { ModelUsage } from '../../product-contracts/src/index.ts';
import { accumulateModelUsage, extractModelUsage } from './event-normalizer.ts';

/** Read native Pi's persisted messages from a run-scoped (not group-shared) session. */
export function recoveredRunUsage(branch: readonly unknown[]): ModelUsage | null {
  let usage: ModelUsage | null = null;
  for (const entry of branch) {
    if (!entry || typeof entry !== 'object' || !('type' in entry) || entry.type !== 'message') continue;
    const message = 'message' in entry ? entry.message : undefined;
    if (!message || typeof message !== 'object' || !('role' in message)) continue;
    if (message.role === 'assistant') {
      usage = accumulateModelUsage(usage, extractModelUsage(message));
    } else if (
      message.role === 'toolResult' &&
      'toolName' in message &&
      message.toolName === 'plugin_agent' &&
      'details' in message &&
      message.details &&
      typeof message.details === 'object' &&
      'usage' in message.details
    ) {
      const child = message.details.usage;
      if (!child || typeof child !== 'object') continue;
      const values = child as Record<string, unknown>;
      // Reuse the same finite, nonnegative validation as live native usage.
      usage = accumulateModelUsage(
        usage,
        extractModelUsage({
          usage: {
            input: values.inputTokens,
            output: values.outputTokens,
            cacheRead: values.cacheReadTokens,
            cacheWrite: values.cacheWriteTokens,
            totalTokens: values.totalTokens,
            cost: { total: values.totalCost },
          },
        }),
      );
    }
  }
  return usage;
}
