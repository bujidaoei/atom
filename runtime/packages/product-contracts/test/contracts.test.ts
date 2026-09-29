import { describe, expect, it } from 'vitest';
import { Value } from 'typebox/value';
import {
  CreateRunRequestSchema,
  ModelUsageSchema,
  ResolveApprovalRequestSchema,
  RunEventSchema,
  RunSchema,
} from '../src/index.ts';

describe('product contracts', () => {
  it('rejects an empty prompt and an unknown execution location', () => {
    expect(Value.Check(CreateRunRequestSchema, { prompt: '' })).toBe(false);
    expect(Value.Check(RunSchema, { executionLocation: 'automatic' })).toBe(false);
  });

  it('accepts an ordered product event without leaking raw objects', () => {
    expect(
      Value.Check(RunEventSchema, {
        id: crypto.randomUUID(),
        runId: crypto.randomUUID(),
        sequence: 1,
        type: 'run.created',
        occurredAt: new Date().toISOString(),
        payload: { executionLocation: 'cloud' },
      }),
    ).toBe(true);

    for (const type of [
      'run.queued',
      'run.preparing',
      'run.recovered',
      'model.requested',
      'model.retry_scheduled',
      'usage.updated',
      'tool.requested',
      'tool.failed',
    ]) {
      expect(
        Value.Check(RunEventSchema, {
          id: crypto.randomUUID(),
          runId: crypto.randomUUID(),
          sequence: 1,
          type,
          occurredAt: new Date().toISOString(),
          payload: {},
        }),
      ).toBe(true);
    }
  });

  it('accepts only explicit approval decisions', () => {
    expect(Value.Check(ResolveApprovalRequestSchema, { decision: 'approved' })).toBe(true);
    expect(Value.Check(ResolveApprovalRequestSchema, { decision: 'maybe' })).toBe(false);
  });

  it('defines a stable model usage summary', () => {
    expect(
      Value.Check(ModelUsageSchema, {
        inputTokens: 12,
        outputTokens: 8,
        cacheReadTokens: 2,
        cacheWriteTokens: 0,
        totalTokens: 22,
        totalCost: 0.002,
      }),
    ).toBe(true);
  });
});
