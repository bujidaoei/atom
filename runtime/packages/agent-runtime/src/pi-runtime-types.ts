import type { Static, TSchema } from 'typebox';

export interface PiToolResult<TDetails = unknown> {
  content: Array<{ type: string; text?: string; [key: string]: unknown }>;
  details?: TDetails;
  isError?: boolean;
  terminate?: boolean;
}

export interface ToolDefinition<TParams extends TSchema = TSchema, TDetails = unknown> {
  name: string;
  label: string;
  description: string;
  promptSnippet?: string;
  promptGuidelines?: string[];
  parameters: TParams;
  executionMode?: 'sequential' | 'parallel';
  execute(
    toolCallId: string,
    params: Static<TParams>,
    signal: AbortSignal | undefined,
    onUpdate?: (result: PiToolResult<TDetails>) => void,
    context?: unknown,
  ): Promise<PiToolResult<TDetails>>;
}

export interface PiSessionMessage {
  role: string;
  api?: string;
  provider?: string;
  model?: string;
  timestamp?: number;
  stopReason?: string;
  responseId?: string;
  errorMessage?: string;
  content?: unknown;
  usage?: unknown;
}

export type PiAgentSessionEvent =
  | { type: 'agent_start' }
  | {
      type: 'message_update';
      message?: PiSessionMessage;
      assistantMessageEvent:
        { type: 'thinking_delta' | 'text_delta'; delta: string } | { type: string; [key: string]: unknown };
    }
  | { type: 'message_end'; message: PiSessionMessage }
  | { type: 'tool_execution_start'; toolCallId: string; toolName: string; args: unknown }
  | {
      type: 'tool_execution_update';
      toolCallId: string;
      toolName: string;
      partialResult: unknown;
    }
  | {
      type: 'tool_execution_end';
      toolCallId: string;
      toolName: string;
      result: unknown;
      isError: boolean;
    }
  | {
      type: 'auto_retry_start';
      attempt: number;
      maxAttempts: number;
      delayMs: number;
      errorMessage: string;
    }
  | { type: 'auto_retry_end'; success: boolean; attempt: number; finalError?: string }
  | { type: 'agent_settled' };
