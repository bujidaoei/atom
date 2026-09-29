import {
  normalizeLiteLlmBaseUrl,
  type V4AiGatewayServerConfiguration,
} from '../../product-contracts/src/server-configuration.ts';
import type { ModelUsage } from '../../product-contracts/src/index.ts';
import { redactProviderCorrelation } from '../../product-contracts/src/provider-correlation.ts';

export type EnterpriseAiGatewayAuthorizedModels = ReadonlySet<string> | readonly string[];

export type EnterpriseAiGatewayConfiguration = V4AiGatewayServerConfiguration & {
  authorizedModels?: EnterpriseAiGatewayAuthorizedModels;
  requestHeaders?: Record<string, string>;
};

export interface EnterpriseAiGatewayReadiness {
  status: 'ready';
  model: string;
  availableModelCount: number;
  availableModels: readonly string[];
  livenessStatus: number;
  unauthenticatedModelsStatus: number;
  checkedAt: string;
}

export interface EnterpriseAiGatewayOperationSnapshot {
  readonly defaultModel: string;
  readonly models: readonly string[];
  readonly checkedAt: string;
  assertAuthorized(model: string): void;
  resolveModel(requested?: string): string;
}

export interface EnterpriseAiGatewayCatalogAuthority {
  validate(): Promise<EnterpriseAiGatewayReadiness>;
  refreshSnapshot(): Promise<EnterpriseAiGatewayOperationSnapshot>;
}

export interface EnterpriseAiGatewayCompletion {
  content: string;
  usage: ModelUsage | null;
  providerCorrelationId: string | null;
}

export type EnterpriseAiGatewayCompletionMetadata = Pick<
  EnterpriseAiGatewayCompletion,
  'usage' | 'providerCorrelationId'
>;

class EnterpriseAiGatewayCompletionError extends Error {
  constructor(
    cause: unknown,
    readonly gatewayCompletion: EnterpriseAiGatewayCompletionMetadata,
  ) {
    super(cause instanceof Error ? cause.message : 'AI gateway structured completion failed', { cause });
    this.name = 'EnterpriseAiGatewayCompletionError';
  }
}

export function enterpriseAiGatewayCompletion(cause: unknown): EnterpriseAiGatewayCompletionMetadata | null {
  return cause instanceof EnterpriseAiGatewayCompletionError ? cause.gatewayCompletion : null;
}

export interface EnterpriseAiGatewayClient {
  complete(input: {
    messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }>;
    temperature?: number;
    responseFormat?: { type: 'json_object' };
    signal?: AbortSignal;
  }): Promise<EnterpriseAiGatewayCompletion>;
}

const MAX_MODEL_CATALOG_BYTES = 2 * 1024 * 1024;
const MAX_STRUCTURED_COMPLETION_BYTES = 4 * 1024 * 1024;
// T313: the real gateway's healthy TLS requests approach three seconds.
// Keep control-plane calls bounded independently of long model generations,
// without treating a normal connection setup as an authentication failure.
export const MAX_AI_GATEWAY_CONTROL_PLANE_TIMEOUT_MS = 10_000;
const AI_GATEWAY_AUTHORIZATION_SOFT_TTL_MS = 30_000;
const AI_GATEWAY_AUTHORIZATION_HARD_TTL_MS = 120_000;

export function normalizeEnterpriseAiGatewayBaseUrl(value: string): string {
  return normalizeLiteLlmBaseUrl(value);
}

export function enterpriseAiGatewayOrigin(baseUrl: string): string {
  const url = new URL(baseUrl);
  url.pathname = url.pathname.replace(/\/v1\/?$/u, '') || '/';
  return url.toString().replace(/\/$/u, '');
}

function includesModel(models: EnterpriseAiGatewayAuthorizedModels, model: string): boolean {
  return typeof (models as ReadonlySet<string>).has === 'function'
    ? (models as ReadonlySet<string>).has(model)
    : (models as readonly string[]).includes(model);
}

export function assertEnterpriseAiGatewayModelAuthorized(
  model: string,
  authorizedModels: EnterpriseAiGatewayAuthorizedModels,
): void {
  if (!model || !includesModel(authorizedModels, model)) {
    throw new Error(`AI gateway model is unavailable: ${model || '<empty>'}`);
  }
}

export function resolveEnterpriseChatModel(
  requested: string | undefined,
  configured: string,
  authorizedModels?: EnterpriseAiGatewayAuthorizedModels,
): string {
  const trimmed = requested?.trim() ?? '';
  const model = trimmed || configured;
  if (model.length > 200) throw new Error('AI gateway model is invalid');
  if (authorizedModels) assertEnterpriseAiGatewayModelAuthorized(model, authorizedModels);
  return model;
}

export class EnterpriseAiGatewayProbeError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = 'EnterpriseAiGatewayProbeError';
  }
}

async function discardProbeBody(response: Response): Promise<void> {
  // A deadline may already have errored the stream. Cleanup must not replace
  // the HTTP/probe result with that secondary error.
  await response.body?.cancel().catch(() => undefined);
}

function discoveryError(status: number): Error {
  if (status === 401) return new Error('AI gateway model discovery authentication failed (401)');
  if (status === 403) return new Error('AI gateway model discovery authorization failed (403)');
  if (status === 429) return new Error('AI gateway model discovery rate limit reached (429)');
  return new EnterpriseAiGatewayProbeError(
    `AI gateway model discovery failed with status ${status}`,
    status >= 500,
  );
}

/** Startup only: never retries an Agent turn or accepts an unvalidated catalog. */
export async function validateEnterpriseAiGatewayStartup(
  authority: Pick<EnterpriseAiGatewayCatalogAuthority, 'validate'>,
  onRetry?: (message: string) => void,
): Promise<EnterpriseAiGatewayReadiness> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await authority.validate();
    } catch (cause) {
      if (!(cause instanceof EnterpriseAiGatewayProbeError) || !cause.retryable || attempt >= 3) throw cause;
      onRetry?.(`AI gateway startup validation retry ${attempt + 1}/3: ${cause.message}`);
      await new Promise<void>((resolve) => setTimeout(resolve, 250 * attempt));
    }
  }
}

/** Keep recovery/queue services alive during a retryable transport outage.
 * Each operation must still call refreshSnapshot; no catalog or model authority is granted here. */
export async function initializeEnterpriseGatewayService(
  authority: EnterpriseAiGatewayCatalogAuthority,
  warn: (message: string) => void,
  describeFailure?: (cause: EnterpriseAiGatewayProbeError) => string,
): Promise<'ready' | 'degraded'> {
  try {
    await validateEnterpriseAiGatewayStartup(authority, warn);
    return 'ready';
  } catch (cause) {
    if (!(cause instanceof EnterpriseAiGatewayProbeError) || !cause.retryable) throw cause;
    warn(
      `AI gateway temporarily unavailable; model authorization remains unavailable.${describeFailure ? ` ${describeFailure(cause)}` : ''}`,
    );
    return 'degraded';
  }
}

async function boundedJson(
  response: Response,
  options: {
    maximumBytes: number;
    exceededMessage: string;
    emptyMessage: string;
    invalidMessage: string;
    streamFailureMessage: string;
  },
): Promise<unknown> {
  const announcedBytes = Number(response.headers.get('content-length') ?? 0);
  if (Number.isFinite(announcedBytes) && announcedBytes > options.maximumBytes) {
    await response.body?.cancel().catch(() => undefined);
    throw new Error(options.exceededMessage);
  }
  if (!response.body) throw new Error(options.emptyMessage);
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let receivedBytes = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read().catch((cause: unknown) => {
        throw new Error(options.streamFailureMessage, { cause });
      });
      if (done) break;
      receivedBytes += value.byteLength;
      if (receivedBytes > options.maximumBytes) {
        await reader.cancel().catch(() => undefined);
        throw new Error(options.exceededMessage);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(receivedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as unknown;
  } catch (cause) {
    throw new Error(options.invalidMessage, { cause });
  }
}

export async function validateEnterpriseAiGatewayModel(
  configuration: EnterpriseAiGatewayConfiguration,
  fetchImplementation: typeof fetch = fetch,
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<EnterpriseAiGatewayReadiness> {
  const timeoutMs = Math.min(
    configuration.requestTimeoutMs,
    options.timeoutMs ?? MAX_AI_GATEWAY_CONTROL_PLANE_TIMEOUT_MS,
    MAX_AI_GATEWAY_CONTROL_PLANE_TIMEOUT_MS,
  );
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeoutSignal]) : timeoutSignal;
  const livenessRequest = fetchImplementation(
    `${enterpriseAiGatewayOrigin(configuration.baseUrl)}/health/liveliness`,
    { method: 'GET', signal, redirect: 'error' },
  ).catch((cause: unknown) => {
    throw new EnterpriseAiGatewayProbeError(
      'AI gateway liveness could not reach the configured service',
      true,
      { cause },
    );
  });
  const unauthenticatedRequest = fetchImplementation(`${configuration.baseUrl}/models`, {
    method: 'GET',
    signal,
    redirect: 'error',
  }).catch((cause: unknown) => {
    throw new EnterpriseAiGatewayProbeError(
      'AI gateway unauthenticated model discovery could not reach the configured service',
      true,
      {
        cause,
      },
    );
  });
  const [livenessResult, unauthenticatedResult] = await Promise.allSettled([
    livenessRequest,
    unauthenticatedRequest,
  ]);
  if (livenessResult.status === 'rejected' || unauthenticatedResult.status === 'rejected') {
    await Promise.all([
      livenessResult.status === 'fulfilled' ? discardProbeBody(livenessResult.value) : undefined,
      unauthenticatedResult.status === 'fulfilled'
        ? discardProbeBody(unauthenticatedResult.value)
        : undefined,
    ]);
    if (livenessResult.status === 'rejected') throw livenessResult.reason;
    if (unauthenticatedResult.status === 'rejected') throw unauthenticatedResult.reason;
  }
  const liveness = livenessResult.value;
  const unauthenticated = unauthenticatedResult.value;
  if (!liveness.ok) {
    await discardProbeBody(liveness);
    await discardProbeBody(unauthenticated);
    throw new EnterpriseAiGatewayProbeError(
      `AI gateway liveness failed with status ${liveness.status}`,
      liveness.status >= 500,
    );
  }
  await discardProbeBody(liveness);
  if (![401, 403].includes(unauthenticated.status)) {
    await discardProbeBody(unauthenticated);
    throw new Error(
      `AI gateway model discovery must reject unauthenticated requests (received ${unauthenticated.status})`,
    );
  }
  await discardProbeBody(unauthenticated);
  // The authenticated catalog is a second round trip; it gets its own control-plane budget.
  const discoveryTimeout = AbortSignal.timeout(timeoutMs);
  const discoverySignal = options.signal
    ? AbortSignal.any([options.signal, discoveryTimeout])
    : discoveryTimeout;
  const response = await fetchImplementation(`${configuration.baseUrl}/models`, {
    method: 'GET',
    headers: { authorization: `Bearer ${configuration.masterKey}` },
    signal: discoverySignal,
    redirect: 'error',
  }).catch((cause: unknown) => {
    throw new EnterpriseAiGatewayProbeError(
      'AI gateway model discovery could not reach the configured service',
      true,
      { cause },
    );
  });
  if (!response.ok) {
    await discardProbeBody(response);
    throw discoveryError(response.status);
  }
  const payload = (await boundedJson(response, {
    maximumBytes: MAX_MODEL_CATALOG_BYTES,
    exceededMessage: 'AI gateway model discovery response exceeded 2 MiB',
    emptyMessage: 'AI gateway model discovery returned an empty body',
    invalidMessage: 'AI gateway model discovery returned invalid JSON',
    streamFailureMessage: 'AI gateway model discovery response stream failed',
  })) as { data?: unknown };
  if (!Array.isArray(payload.data)) {
    throw new Error('AI gateway model discovery returned an invalid model list');
  }
  const models: string[] = [];
  const seenModels = new Set<string>();
  for (const entry of payload.data) {
    if (typeof entry !== 'object' || entry === null || typeof (entry as { id?: unknown }).id !== 'string') {
      continue;
    }
    const id = (entry as { id: string }).id.trim();
    if (!id || id.length > 200) throw new Error('AI gateway model discovery returned an invalid model id');
    if (seenModels.has(id)) continue;
    seenModels.add(id);
    models.push(id);
  }
  if (!models.includes(configuration.model)) {
    throw new Error(`Configured AI gateway model ${configuration.model} is not available`);
  }
  return {
    status: 'ready',
    model: configuration.model,
    availableModelCount: models.length,
    availableModels: models,
    livenessStatus: liveness.status,
    unauthenticatedModelsStatus: unauthenticated.status,
    checkedAt: new Date(Date.now()).toISOString(),
  };
}

export function createEnterpriseAiGatewayReadinessProbe(
  configuration: EnterpriseAiGatewayConfiguration,
  fetchImplementation: typeof fetch = fetch,
): () => Promise<EnterpriseAiGatewayReadiness> {
  let active: Promise<EnterpriseAiGatewayReadiness> | undefined;
  return () => {
    active ??= validateEnterpriseAiGatewayModel(configuration, fetchImplementation).finally(() => {
      active = undefined;
    });
    return active;
  };
}

function operationSnapshot(
  configuration: EnterpriseAiGatewayConfiguration,
  readiness: EnterpriseAiGatewayReadiness,
): EnterpriseAiGatewayOperationSnapshot {
  const models = Object.freeze([...readiness.availableModels]);
  const authorizedModels = new Set(models);
  return Object.freeze({
    defaultModel: configuration.model,
    models,
    checkedAt: readiness.checkedAt,
    assertAuthorized(model: string) {
      assertEnterpriseAiGatewayModelAuthorized(model, authorizedModels);
    },
    resolveModel(requested?: string) {
      return resolveEnterpriseChatModel(requested, configuration.model, authorizedModels);
    },
  });
}

export function createEnterpriseAiGatewayAuthorizationState(
  configuration: EnterpriseAiGatewayConfiguration,
  fetchImplementation: typeof fetch = fetch,
): EnterpriseAiGatewayCatalogAuthority {
  let active: Promise<EnterpriseAiGatewayReadiness> | undefined;
  let accepted: { readiness: EnterpriseAiGatewayReadiness; validatedAt: number } | undefined;
  let failedRefresh: { error: unknown; retryAt: number } | undefined;
  let nextBackgroundRefreshAt = 0;
  const validate = () => {
    if (active) return active;
    const attemptedAt = Date.now();
    active = validateEnterpriseAiGatewayModel(configuration, fetchImplementation)
      .then((readiness) => {
        const validatedAt = Date.now();
        accepted = { readiness, validatedAt };
        failedRefresh = undefined;
        nextBackgroundRefreshAt = validatedAt + AI_GATEWAY_AUTHORIZATION_SOFT_TTL_MS;
        return readiness;
      })
      .catch((error: unknown) => {
        nextBackgroundRefreshAt = attemptedAt + AI_GATEWAY_AUTHORIZATION_SOFT_TTL_MS;
        if (accepted || failedRefresh) {
          // A known validation failure revokes the cached catalog for future operations.
          // Snapshots already issued to in-flight operations remain immutable.
          accepted = undefined;
          failedRefresh = { error, retryAt: nextBackgroundRefreshAt };
        }
        throw error;
      })
      .finally(() => {
        active = undefined;
      });
    return active;
  };
  return {
    async refreshSnapshot() {
      const cached = accepted;
      if (!cached) {
        if (failedRefresh && Date.now() < failedRefresh.retryAt) throw failedRefresh.error;
        return operationSnapshot(configuration, await validate());
      }
      const now = Date.now();
      if (now - cached.validatedAt >= AI_GATEWAY_AUTHORIZATION_HARD_TTL_MS) {
        return operationSnapshot(configuration, await validate());
      }
      if (now >= nextBackgroundRefreshAt && !active) {
        void validate().catch(() => undefined);
      }
      return operationSnapshot(configuration, cached.readiness);
    },
    validate,
  };
}

function completionContent(payload: unknown): string {
  if (!payload || typeof payload !== 'object') {
    throw new Error('AI gateway structured completion returned malformed JSON');
  }
  const choice = (payload as { choices?: unknown }).choices;
  const first = Array.isArray(choice) ? choice[0] : undefined;
  const message = first && typeof first === 'object' ? (first as { message?: unknown }).message : undefined;
  const content =
    message && typeof message === 'object' ? (message as { content?: unknown }).content : undefined;
  if (typeof content !== 'string' || !content.trim()) {
    throw new Error('AI gateway structured completion returned empty content');
  }
  return content;
}

function usageNumber(...candidates: unknown[]): number | undefined {
  let zeroProvided = false;
  for (const candidate of candidates) {
    if (candidate === null || candidate === undefined || candidate === '') continue;
    const value = Number(candidate);
    if (!Number.isFinite(value) || value < 0) continue;
    if (value > 0) return value;
    zeroProvided = true;
  }
  return zeroProvided ? 0 : undefined;
}

function completionUsage(payload: unknown, headers: Headers): ModelUsage | null {
  if (!payload || typeof payload !== 'object') return null;
  const usage = (payload as { usage?: unknown }).usage;
  if (!usage || typeof usage !== 'object') return null;
  const value = usage as Record<string, unknown>;
  const promptDetails =
    value.prompt_tokens_details && typeof value.prompt_tokens_details === 'object'
      ? (value.prompt_tokens_details as Record<string, unknown>)
      : {};
  const inputTokens = usageNumber(value.prompt_tokens, value.input_tokens) ?? 0;
  const outputTokens = usageNumber(value.completion_tokens, value.output_tokens) ?? 0;
  const totalTokens = usageNumber(value.total_tokens) ?? inputTokens + outputTokens;
  const cacheReadTokens =
    usageNumber(
      promptDetails.cached_tokens,
      value.cache_read_input_tokens,
      value.cache_read_tokens,
      value.prompt_cache_hit_tokens,
    ) ?? 0;
  const cacheWriteTokens =
    usageNumber(
      promptDetails.cache_write_tokens,
      promptDetails.cache_creation_tokens,
      value.cache_creation_input_tokens,
      value.cache_write_input_tokens,
      value.cache_write_tokens,
    ) ?? 0;
  const hiddenParameters =
    (payload as { _hidden_params?: unknown })._hidden_params &&
    typeof (payload as { _hidden_params?: unknown })._hidden_params === 'object'
      ? ((payload as { _hidden_params: Record<string, unknown> })._hidden_params as Record<string, unknown>)
      : {};
  const totalCost =
    usageNumber(
      value.response_cost,
      value.total_cost,
      value.cost,
      (payload as { response_cost?: unknown }).response_cost,
      hiddenParameters.response_cost,
      headers.get('x-litellm-response-cost'),
    ) ?? 0;
  return {
    inputTokens,
    outputTokens,
    cacheReadTokens,
    cacheWriteTokens,
    totalTokens,
    totalCost,
  };
}

export function createEnterpriseAiGatewayClient(
  configuration: EnterpriseAiGatewayConfiguration,
  fetchImplementation: typeof fetch = fetch,
): EnterpriseAiGatewayClient {
  return {
    async complete(input) {
      const timeout = AbortSignal.timeout(configuration.requestTimeoutMs);
      const signal = input.signal ? AbortSignal.any([input.signal, timeout]) : timeout;
      const response = await fetchImplementation(`${configuration.baseUrl}/chat/completions`, {
        method: 'POST',
        redirect: 'error',
        headers: {
          authorization: `Bearer ${configuration.masterKey}`,
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          model: configuration.model,
          stream: false,
          messages: input.messages,
          ...(input.temperature === undefined ? {} : { temperature: input.temperature }),
          ...(input.responseFormat === undefined ? {} : { response_format: input.responseFormat }),
        }),
        signal,
      });
      if (!response.ok) {
        await response.body?.cancel().catch(() => undefined);
        throw new EnterpriseAiGatewayCompletionError(
          new Error(`AI gateway structured completion failed with HTTP ${response.status}`),
          {
            usage: null,
            providerCorrelationId: redactProviderCorrelation(
              response.headers.get('x-request-id') ?? response.headers.get('x-ai-gateway-request-id'),
            ),
          },
        );
      }
      let payload: unknown;
      try {
        payload = await boundedJson(response, {
          maximumBytes: MAX_STRUCTURED_COMPLETION_BYTES,
          exceededMessage: 'AI gateway structured completion response exceeded 4 MiB',
          emptyMessage: 'AI gateway structured completion returned an empty body',
          invalidMessage: 'AI gateway structured completion returned malformed JSON',
          streamFailureMessage: 'AI gateway structured completion response stream failed',
        });
      } catch (cause) {
        throw new EnterpriseAiGatewayCompletionError(cause, {
          usage: null,
          providerCorrelationId: redactProviderCorrelation(
            response.headers.get('x-request-id') ?? response.headers.get('x-ai-gateway-request-id'),
          ),
        });
      }
      const responseId =
        payload && typeof payload === 'object' && typeof (payload as { id?: unknown }).id === 'string'
          ? (payload as { id: string }).id
          : null;
      const usage = completionUsage(payload, response.headers);
      const providerCorrelationId = redactProviderCorrelation(
        response.headers.get('x-request-id') ?? response.headers.get('x-ai-gateway-request-id') ?? responseId,
      );
      let content: string;
      try {
        content = completionContent(payload);
      } catch (cause) {
        throw new EnterpriseAiGatewayCompletionError(cause, {
          usage,
          providerCorrelationId,
        });
      }
      return {
        content,
        usage,
        providerCorrelationId,
      };
    },
  };
}
