import { Type, type Static } from 'typebox';

export * from './v3.ts';
export * from './v3-ports.ts';
export * from './v3-canonical-json.ts';
export * from './v3-permission-catalog.ts';
export * from './server-configuration.ts';
export * from './provider-correlation.ts';
export * from './v3-attachment-compensation.ts';
export * from './feishu-auth.ts';
export * from './ai-gateway-virtual-key.ts';
export * from './download-center.ts';
export * from './v5-claim-polling.ts';
export * from './waker-creation-mcp.ts';

export const ExecutionLocationSchema = Type.Union([Type.Literal('local'), Type.Literal('cloud')]);
export type ExecutionLocation = Static<typeof ExecutionLocationSchema>;

export const RunStatusSchema = Type.Union([
  Type.Literal('queued'),
  Type.Literal('preparing'),
  Type.Literal('running'),
  Type.Literal('awaiting_approval'),
  Type.Literal('completed'),
  Type.Literal('failed'),
  Type.Literal('cancelled'),
]);
export type RunStatus = Static<typeof RunStatusSchema>;

export const RunEventTypeSchema = Type.Union([
  Type.Literal('run.created'),
  Type.Literal('run.queued'),
  Type.Literal('run.preparing'),
  Type.Literal('run.started'),
  Type.Literal('run.recovered'),
  Type.Literal('run.interrupted'),
  Type.Literal('run.inbox_delivery'),
  Type.Literal('run.session'),
  Type.Literal('model.requested'),
  Type.Literal('model.retry_scheduled'),
  Type.Literal('model.retry_completed'),
  Type.Literal('thinking.delta'),
  Type.Literal('message.delta'),
  Type.Literal('message.completed'),
  Type.Literal('usage.updated'),
  Type.Literal('tool.requested'),
  Type.Literal('tool.started'),
  Type.Literal('tool.updated'),
  Type.Literal('tool.completed'),
  Type.Literal('tool.failed'),
  Type.Literal('approval.requested'),
  Type.Literal('approval.resolved'),
  Type.Literal('input.requested'),
  Type.Literal('input.resolved'),
  Type.Literal('artifact.created'),
  Type.Literal('checkpoint.created'),
  Type.Literal('policy.evaluated'),
  Type.Literal('run.completed'),
  Type.Literal('run.failed'),
  Type.Literal('run.cancelled'),
]);
export type RunEventType = Static<typeof RunEventTypeSchema>;

export const ModelUsageSchema = Type.Object(
  {
    inputTokens: Type.Integer({ minimum: 0 }),
    outputTokens: Type.Integer({ minimum: 0 }),
    cacheReadTokens: Type.Integer({ minimum: 0 }),
    cacheWriteTokens: Type.Integer({ minimum: 0 }),
    totalTokens: Type.Integer({ minimum: 0 }),
    totalCost: Type.Number({ minimum: 0 }),
  },
  { additionalProperties: false },
);
export type ModelUsage = Static<typeof ModelUsageSchema>;

export const RunSchema = Type.Object(
  {
    id: Type.String({ format: 'uuid' }),
    conversationId: Type.Optional(Type.String({ format: 'uuid' })),
    taskId: Type.Optional(Type.String({ format: 'uuid' })),
    executionLocation: ExecutionLocationSchema,
    status: RunStatusSchema,
    prompt: Type.String({ minLength: 1, maxLength: 100_000 }),
    model: Type.String({ minLength: 1 }),
    usage: Type.Union([ModelUsageSchema, Type.Null()]),
    resultText: Type.Union([Type.String(), Type.Null()]),
    error: Type.Union([Type.String(), Type.Null()]),
    queuedAt: Type.String({ format: 'date-time' }),
    startedAt: Type.Union([Type.String({ format: 'date-time' }), Type.Null()]),
    finishedAt: Type.Union([Type.String({ format: 'date-time' }), Type.Null()]),
  },
  { additionalProperties: false },
);
export type Run = Static<typeof RunSchema>;

export const RunEventSchema = Type.Object(
  {
    id: Type.String({ format: 'uuid' }),
    runId: Type.String({ format: 'uuid' }),
    sequence: Type.Integer({ minimum: 1 }),
    type: RunEventTypeSchema,
    occurredAt: Type.String({ format: 'date-time' }),
    payload: Type.Record(Type.String(), Type.Unknown()),
  },
  { additionalProperties: false },
);
export type RunEvent = Static<typeof RunEventSchema>;

export const ApprovalSchema = Type.Object(
  {
    id: Type.String({ format: 'uuid' }),
    runId: Type.String({ format: 'uuid' }),
    command: Type.String({ minLength: 1, maxLength: 16_000 }),
    target: Type.String({ minLength: 1 }),
    risk: Type.Union([Type.Literal('read'), Type.Literal('write'), Type.Literal('execute')]),
    status: Type.Union([
      Type.Literal('pending'),
      Type.Literal('approved'),
      Type.Literal('rejected'),
      Type.Literal('expired'),
    ]),
    requestedAt: Type.String({ format: 'date-time' }),
    expiresAt: Type.String({ format: 'date-time' }),
  },
  { additionalProperties: false },
);
export type Approval = Static<typeof ApprovalSchema>;

export const ArtifactSchema = Type.Object(
  {
    id: Type.String({ format: 'uuid' }),
    runId: Type.String({ format: 'uuid' }),
    name: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.String({ minLength: 1 }),
    sizeBytes: Type.Integer({ minimum: 0 }),
    sha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
    downloadUrl: Type.Optional(Type.String()),
  },
  { additionalProperties: false },
);
export type Artifact = Static<typeof ArtifactSchema>;

export const CreateRunRequestSchema = Type.Object(
  {
    prompt: Type.String({ minLength: 1, maxLength: 100_000 }),
    conversationId: Type.Optional(Type.String({ format: 'uuid' })),
  },
  { additionalProperties: false },
);
export type CreateRunRequest = Static<typeof CreateRunRequestSchema>;

export const ResolveApprovalRequestSchema = Type.Object(
  { decision: Type.Union([Type.Literal('approved'), Type.Literal('rejected')]) },
  { additionalProperties: false },
);
export type ResolveApprovalRequest = Static<typeof ResolveApprovalRequestSchema>;

export interface RunDetail extends Run {
  events: RunEvent[];
  approvals: Approval[];
  artifacts: Artifact[];
}

export interface ProductSession {
  user: { id: string; displayName: string };
  workspace: { id: string; name: string };
  executionReadiness?: { ready: boolean; message: string };
}

export interface AgentRunRequest {
  runId: string;
  prompt: string;
  images?: AgentRunImage[];
  readableAttachments?: AgentRunReadableAttachment[];
  workspacePath: string;
  sessionPath: string;
  /** Previous conversation turn's native Pi session; a new Run forks it once. */
  parentSessionPath?: string;
  recovery?: boolean;
  signal?: AbortSignal;
  model?: string;
}

export interface AgentRunImage {
  data: string;
  mimeType: string;
}

export interface AgentRunReadableAttachment {
  path: string;
  mediaType: string;
  sizeBytes: number;
  sha256: string;
}

export interface SandboxExecRequest {
  toolCallId: string;
  command: string;
  timeoutMs: number;
}

export interface SandboxExecResult {
  toolCallId: string;
  exitCode: number;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  truncated: boolean;
}

export interface SandboxWriteFileRequest {
  toolCallId: string;
  path: string;
  content: string;
}

export interface SandboxWriteFileResult {
  toolCallId: string;
  bytesWritten: number;
}

export interface SandboxClient {
  create(runId: string, workspaceId: string): Promise<string>;
  exec(sandboxId: string, request: SandboxExecRequest, signal?: AbortSignal): Promise<SandboxExecResult>;
  writeFile?(
    sandboxId: string,
    request: SandboxWriteFileRequest,
    signal?: AbortSignal,
  ): Promise<SandboxWriteFileResult>;
  destroy(sandboxId: string): Promise<void>;
}

export interface ApprovalAdapter {
  request(input: {
    runId: string;
    toolCallId: string;
    command: string;
    target: string;
    risk: 'read' | 'write' | 'execute';
    requestHash?: string;
    ruleIds?: string[];
    policyVersions?: Array<{ id: string; version: number }>;
  }): Promise<'approved' | 'rejected'>;
}

export interface ProductEventSink {
  emit(type: RunEventType, payload: Record<string, unknown>): Promise<void>;
}
