import type { RunEventType } from '../../product-contracts/src/index.ts';
import type { ModelUsage } from '../../product-contracts/src/index.ts';
import type { PiAgentSessionEvent } from './pi-runtime-types.ts';
import { runFailureDetail } from './run-failure.ts';

export interface NormalizedPiEvent {
  type: RunEventType;
  payload: Record<string, unknown>;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? { ...value } : { value };
}

function messageText(message: unknown): string {
  if (typeof message !== 'object' || message === null || !('content' in message)) return '';
  const content = message.content;
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content
    .filter(
      (part): part is { type: 'text'; text: string } =>
        typeof part === 'object' &&
        part !== null &&
        'type' in part &&
        part.type === 'text' &&
        'text' in part &&
        typeof part.text === 'string',
    )
    .map((part) => part.text)
    .join('');
}

export function extractModelUsage(message: unknown): ModelUsage | undefined {
  if (typeof message !== 'object' || message === null || !('usage' in message)) return undefined;
  const usage = message.usage;
  if (typeof usage !== 'object' || usage === null) return undefined;
  const values = usage as Record<string, unknown>;
  const cost =
    typeof values.cost === 'object' && values.cost !== null ? (values.cost as Record<string, unknown>) : {};
  const numbers = [
    values.input,
    values.output,
    values.cacheRead,
    values.cacheWrite,
    values.totalTokens,
    cost.total,
  ];
  if (numbers.some((value) => typeof value !== 'number' || !Number.isFinite(value) || value < 0)) {
    return undefined;
  }
  return {
    inputTokens: values.input as number,
    outputTokens: values.output as number,
    cacheReadTokens: values.cacheRead as number,
    cacheWriteTokens: values.cacheWrite as number,
    totalTokens: values.totalTokens as number,
    totalCost: cost.total as number,
  };
}

export function accumulateModelUsage(
  current: ModelUsage | null,
  next: ModelUsage | null | undefined,
): ModelUsage | null {
  if (!next) return current;
  if (!current) return { ...next };
  return {
    inputTokens: current.inputTokens + next.inputTokens,
    outputTokens: current.outputTokens + next.outputTokens,
    cacheReadTokens: current.cacheReadTokens + next.cacheReadTokens,
    cacheWriteTokens: current.cacheWriteTokens + next.cacheWriteTokens,
    totalTokens: current.totalTokens + next.totalTokens,
    totalCost: current.totalCost + next.totalCost,
  };
}

export function normalizePiEvents(event: PiAgentSessionEvent): NormalizedPiEvent[] {
  switch (event.type) {
    case 'agent_start':
      return [{ type: 'run.started', payload: {} }];
    case 'message_update':
      if (event.assistantMessageEvent.type === 'thinking_delta') {
        return [
          {
            type: 'thinking.delta',
            payload: { delta: event.assistantMessageEvent.delta },
          },
        ];
      }
      if (event.assistantMessageEvent.type !== 'text_delta') return [];
      return [
        {
          type: 'message.delta',
          payload: { delta: event.assistantMessageEvent.delta },
        },
      ];
    case 'message_end': {
      if (!('role' in event.message) || event.message.role !== 'assistant') return [];
      const usage = extractModelUsage(event.message);
      if (
        event.message.stopReason === 'error' ||
        event.message.stopReason === 'aborted' ||
        event.message.stopReason === 'length'
      ) {
        return usage ? [{ type: 'usage.updated', payload: { usage } }] : [];
      }
      const text = messageText(event.message);
      return [
        ...(usage ? [{ type: 'usage.updated' as const, payload: { usage } }] : []),
        ...(text
          ? [{ type: 'message.completed' as const, payload: { text, ...(usage ? { usage } : {}) } }]
          : []),
      ];
    }
    case 'tool_execution_start':
      return ['tool.requested', 'tool.started'].map((type) => ({
        type: type as 'tool.requested' | 'tool.started',
        payload: {
          toolCallId: event.toolCallId,
          toolName: event.toolName,
          args: asRecord(event.args),
        },
      }));
    case 'tool_execution_update':
      return [
        {
          type: 'tool.updated',
          payload: {
            toolCallId: event.toolCallId,
            toolName: event.toolName,
            partialResult: asRecord(event.partialResult),
          },
        },
      ];
    case 'tool_execution_end':
      return [
        {
          type: event.isError ? 'tool.failed' : 'tool.completed',
          payload: {
            toolCallId: event.toolCallId,
            toolName: event.toolName,
            result: asRecord(event.result),
            isError: event.isError,
          },
        },
      ];
    case 'auto_retry_start':
      return [
        {
          type: 'model.retry_scheduled',
          payload: {
            attempt: event.attempt,
            maxAttempts: event.maxAttempts,
            delayMs: event.delayMs,
            errorMessage: runFailureDetail(event.errorMessage),
          },
        },
      ];
    case 'auto_retry_end':
      return [
        {
          type: 'model.retry_completed',
          payload: {
            success: event.success,
            attempt: event.attempt,
            ...(event.finalError ? { finalError: runFailureDetail(event.finalError) } : {}),
          },
        },
      ];
    default:
      return [];
  }
}

export function normalizePiEvent(event: PiAgentSessionEvent): NormalizedPiEvent | undefined {
  return normalizePiEvents(event).at(-1);
}

export function extractAssistantText(message: unknown): string {
  return messageText(message);
}
