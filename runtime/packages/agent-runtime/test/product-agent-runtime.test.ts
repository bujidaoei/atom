import { describe, expect, it } from 'vitest';

import { normalizePiEvent, normalizePiEvents } from '../src/event-normalizer.ts';
import { classifyRunFailure, runFailureDetail } from '../src/run-failure.ts';

describe('Pi event normalization', () => {
  it('maps text deltas into stable product events', () => {
    const event = normalizePiEvent({
      type: 'message_update',
      message: {
        role: 'assistant',
        content: [],
        api: 'openai-completions',
        provider: 'deepseek',
        model: 'deepseek-chat',
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: 'stop',
        timestamp: 0,
      },
      assistantMessageEvent: {
        type: 'text_delta',
        contentIndex: 0,
        delta: 'hello',
        partial: {
          role: 'assistant',
          content: [],
          api: 'openai-completions',
          provider: 'deepseek',
          model: 'deepseek-chat',
          usage: {
            input: 0,
            output: 0,
            cacheRead: 0,
            cacheWrite: 0,
            totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
          },
          stopReason: 'stop',
          timestamp: 0,
        },
      },
    });

    expect(event).toEqual({ type: 'message.delta', payload: { delta: 'hello' } });
  });

  it('maps Pi thinking deltas into a separate durable stream without changing Pi', () => {
    const event = normalizePiEvent({
      type: 'message_update',
      message: {
        role: 'assistant',
        content: [],
        api: 'openai-completions',
        provider: 'deepseek',
        model: 'deepseek-chat',
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: 'stop',
        timestamp: 0,
      },
      assistantMessageEvent: {
        type: 'thinking_delta',
        contentIndex: 0,
        delta: '先核验约束',
        partial: {
          role: 'assistant',
          content: [],
          api: 'openai-completions',
          provider: 'deepseek',
          model: 'deepseek-chat',
          usage: {
            input: 0,
            output: 0,
            cacheRead: 0,
            cacheWrite: 0,
            totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
          },
          stopReason: 'stop',
          timestamp: 0,
        },
      },
    });

    expect(event).toEqual({ type: 'thinking.delta', payload: { delta: '先核验约束' } });
  });

  it('maps tool completion without exposing Pi objects', () => {
    const event = normalizePiEvent({
      type: 'tool_execution_end',
      toolCallId: 'call-1',
      toolName: 'sandbox_exec',
      result: { content: [{ type: 'text', text: 'ok' }] },
      isError: false,
    });

    expect(event?.type).toBe('tool.completed');
    expect(event?.payload.toolCallId).toBe('call-1');
  });

  it('projects tool request/start and failed completion as ordered authoritative events', () => {
    expect(
      normalizePiEvents({
        type: 'tool_execution_start',
        toolCallId: 'call-1',
        toolName: 'sandbox_exec',
        args: { command: 'pwd' },
      }),
    ).toEqual([
      {
        type: 'tool.requested',
        payload: { toolCallId: 'call-1', toolName: 'sandbox_exec', args: { command: 'pwd' } },
      },
      {
        type: 'tool.started',
        payload: { toolCallId: 'call-1', toolName: 'sandbox_exec', args: { command: 'pwd' } },
      },
    ]);

    expect(
      normalizePiEvents({
        type: 'tool_execution_end',
        toolCallId: 'call-1',
        toolName: 'sandbox_exec',
        result: { content: [{ type: 'text', text: 'exit 1' }] },
        isError: true,
      }),
    ).toEqual([
      expect.objectContaining({
        type: 'tool.failed',
        payload: expect.objectContaining({ toolCallId: 'call-1', isError: true }),
      }),
    ]);
  });

  it('projects PI auto-retry scheduling and completion without inventing progress', () => {
    expect(
      normalizePiEvents({
        type: 'auto_retry_start',
        attempt: 2,
        maxAttempts: 3,
        delayMs: 1_000,
        errorMessage: 'rate limited',
      }),
    ).toEqual([
      {
        type: 'model.retry_scheduled',
        payload: {
          attempt: 2,
          maxAttempts: 3,
          delayMs: 1_000,
          errorMessage: 'rate limited',
        },
      },
    ]);
    expect(normalizePiEvents({ type: 'auto_retry_end', success: true, attempt: 2 })).toEqual([
      { type: 'model.retry_completed', payload: { success: true, attempt: 2 } },
    ]);
  });

  it('projects final model usage without exposing a Pi message', () => {
    const event = normalizePiEvent({
      type: 'message_end',
      message: {
        role: 'assistant',
        content: [{ type: 'text', text: 'done' }],
        api: 'openai-completions',
        provider: 'deepseek',
        model: 'deepseek-chat',
        usage: {
          input: 12,
          output: 8,
          cacheRead: 2,
          cacheWrite: 0,
          totalTokens: 22,
          cost: { input: 0.001, output: 0.001, cacheRead: 0, cacheWrite: 0, total: 0.002 },
        },
        stopReason: 'stop',
        timestamp: 0,
      },
    });

    expect(event).toEqual({
      type: 'message.completed',
      payload: {
        text: 'done',
        usage: {
          inputTokens: 12,
          outputTokens: 8,
          cacheReadTokens: 2,
          cacheWriteTokens: 0,
          totalTokens: 22,
          totalCost: 0.002,
        },
      },
    });

    expect(
      normalizePiEvents({
        type: 'message_end',
        message: {
          role: 'assistant',
          content: [{ type: 'text', text: 'done' }],
          api: 'openai-completions',
          provider: 'deepseek',
          model: 'deepseek-chat',
          usage: {
            input: 12,
            output: 8,
            cacheRead: 2,
            cacheWrite: 0,
            totalTokens: 22,
            cost: { input: 0.001, output: 0.001, cacheRead: 0, cacheWrite: 0, total: 0.002 },
          },
          stopReason: 'stop',
          timestamp: 0,
        },
      }).map(({ type }) => type),
    ).toEqual(['usage.updated', 'message.completed']);
  });

  it('never projects a provider error assistant message as a completed response', () => {
    expect(
      normalizePiEvents({
        type: 'message_end',
        message: {
          role: 'assistant',
          content: [{ type: 'text', text: '401 invalid API key' }],
          api: 'openai-completions',
          provider: 'deepseek',
          model: 'deepseek-chat',
          usage: {
            input: 0,
            output: 0,
            cacheRead: 0,
            cacheWrite: 0,
            totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
          },
          stopReason: 'error',
          errorMessage: '401 invalid API key',
          timestamp: 0,
        },
      }).map(({ type }) => type),
    ).not.toContain('message.completed');
  });

  it('classifies failures using the public contract and redacts credential-shaped detail', () => {
    expect(classifyRunFailure(new Error('401 Unauthorized API key'))).toBe('gateway_authentication');
    expect(classifyRunFailure(new Error('request timed out after 30s'))).toBe('provider_timeout');
    expect(classifyRunFailure(new Error('Sandbox Broker is not configured'))).toBe('sandbox_unavailable');
    expect(classifyRunFailure(new Error('unexpected invariant'))).toBe('internal');
    expect(runFailureDetail(new Error('Bearer secret-token sk-real-secret'))).toBe(
      'Bearer [REDACTED] [REDACTED]',
    );
  });
});
