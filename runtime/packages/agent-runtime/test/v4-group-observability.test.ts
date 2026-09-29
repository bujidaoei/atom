import { describe, expect, it } from 'vitest';

import { summarizeV3GroupAttemptObservability } from '../src/v3-group-observability.ts';

describe('V4 group attempt observability', () => {
  it('sums only durable completed attempts across recovery and keeps the latest correlation ID', () => {
    expect(
      summarizeV3GroupAttemptObservability([
        {
          type: 'usage.updated',
          payload: { usage: { inputTokens: 99, outputTokens: 99, totalTokens: 198 } },
        },
        {
          type: 'leader.attempt.completed',
          payload: {
            usage: {
              inputTokens: 7,
              outputTokens: 5,
              cacheReadTokens: 2,
              cacheWriteTokens: 1,
              totalTokens: 12,
              totalCost: 0.25,
            },
            providerCorrelationId: 'leader-correlation',
          },
        },
        {
          type: 'role_run.attempt.completed',
          payload: {
            usage: { inputTokens: 11, outputTokens: 3, totalTokens: 14, totalCost: 0.5 },
            providerCorrelationId: 'credential=historical-group-secret',
          },
        },
      ]),
    ).toEqual({
      usage: {
        inputTokens: 18,
        outputTokens: 8,
        cacheReadTokens: 2,
        cacheWriteTokens: 1,
        totalTokens: 26,
        totalCost: 0.75,
      },
      providerCorrelationId: 'credential=[REDACTED]',
    });
  });

  it('returns null observability when no completed attempt reported it', () => {
    expect(summarizeV3GroupAttemptObservability([])).toEqual({
      usage: null,
      providerCorrelationId: null,
    });
  });
});
