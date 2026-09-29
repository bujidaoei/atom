const MAX_PROVIDER_CORRELATION_LENGTH = 200;
const MAX_RUN_FAILURE_CATEGORY_LENGTH = 120;
const MAX_RUN_FAILURE_DETAIL_LENGTH = 4_000;
const NAMED_CREDENTIAL_FIELD_NAME_PATTERN = String.raw`(?:[a-z0-9]+[-_])*(?:access[-_]?key[-_]?id|secret[-_]?access[-_]?key|(?:client|app)[-_]?secret|api[-_]?key|access[-_]?key|secret[-_]?key|master[-_]?key|private[-_]?key|key|token|password|secret|credential|signature)`;
const CREDENTIAL_FIELD_NAME_PATTERN = String.raw`(?:authorization|set[-_]?cookie|cookie|${NAMED_CREDENTIAL_FIELD_NAME_PATTERN})`;
const DOUBLE_QUOTED_CREDENTIAL = new RegExp(
  `("${CREDENTIAL_FIELD_NAME_PATTERN}"\\s*:\\s*")(?:\\\\.|[^"\\\\])*(")`,
  'giu',
);
const SINGLE_QUOTED_CREDENTIAL = new RegExp(
  `('${CREDENTIAL_FIELD_NAME_PATTERN}'\\s*:\\s*')(?:\\\\.|[^'\\\\])*(')`,
  'giu',
);
const UNQUOTED_DOUBLE_QUOTED_CREDENTIAL = new RegExp(
  `\\b(${CREDENTIAL_FIELD_NAME_PATTERN})\\s*([=:])\\s*"(?:\\\\.|[^"\\\\])*"`,
  'giu',
);
const UNQUOTED_SINGLE_QUOTED_CREDENTIAL = new RegExp(
  `\\b(${CREDENTIAL_FIELD_NAME_PATTERN})\\s*([=:])\\s*'(?:\\\\.|[^'\\\\])*'`,
  'giu',
);
const NAMED_CREDENTIAL = new RegExp(
  `\\b(${NAMED_CREDENTIAL_FIELD_NAME_PATTERN})\\s*([=:])\\s*[^\\s,;]+`,
  'giu',
);

export function isCredentialFieldName(value: string): boolean {
  const normalized = value
    .replace(/([A-Z]+)([A-Z][a-z])/gu, '$1_$2')
    .replace(/([a-z0-9])([A-Z])/gu, '$1_$2')
    .replace(/[^A-Za-z0-9]+/gu, '_')
    .replace(/^_+|_+$/gu, '')
    .toLowerCase();
  return (
    /^(?:device_)?rebind_grant$/u.test(normalized) ||
    /(?:^|_)(?:password|secret|token|credential|signature|key|authorization|cookie)(?:_value)?$/u.test(
      normalized,
    ) ||
    /(?:^|_)(?:authorization|cookie)_header$/u.test(normalized) ||
    /(?:^|_)(?:api|access|secret|master|private)_key_id$/u.test(normalized)
  );
}

function normalizeControlCharacters(value: string): string {
  let normalized = '';
  let previousWasControl = false;
  for (const character of value) {
    const codePoint = character.codePointAt(0)!;
    const isControl = codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f);
    if (isControl) {
      if (!previousWasControl) normalized += ' ';
      previousWasControl = true;
      continue;
    }
    normalized += character;
    previousWasControl = false;
  }
  return normalized;
}

export function redactCredentialText(value: string, maximumLength: number): string {
  if (!Number.isSafeInteger(maximumLength) || maximumLength < 1) {
    throw new Error('Credential text maximum length must be a positive safe integer');
  }
  return normalizeControlCharacters(value)
    .replace(/([a-z][a-z0-9+.-]*:\/\/[^:\s/@]+:)[^@\s/]+@/giu, '$1[REDACTED]@')
    .replace(DOUBLE_QUOTED_CREDENTIAL, '$1[REDACTED]$2')
    .replace(SINGLE_QUOTED_CREDENTIAL, '$1[REDACTED]$2')
    .replace(UNQUOTED_DOUBLE_QUOTED_CREDENTIAL, '$1$2"[REDACTED]"')
    .replace(UNQUOTED_SINGLE_QUOTED_CREDENTIAL, "$1$2'[REDACTED]'")
    .replace(
      /\b(authorization)\s*([=:])\s*(basic|bearer)\s+[^\s,;]+/giu,
      (_match, name: string, separator: string, scheme: string) =>
        `${name}${separator}${separator === ':' ? ' ' : ''}${scheme} [REDACTED]`,
    )
    .replace(/\b(basic|bearer)\s+[^\s,;]+/giu, '$1 [REDACTED]')
    .replace(/\b(set-cookie|cookie)\s*([=:])\s*[^\r\n,]+/giu, '$1$2 [REDACTED]')
    .replace(/\b(authorization)\s*([=:])\s*(?!(?:basic|bearer)\b)[^\s,;]+/giu, '$1$2[REDACTED]')
    .replace(NAMED_CREDENTIAL, '$1$2[REDACTED]')
    .replace(/\bgh[pousr]_[A-Za-z0-9]{20,}\b/gu, '[REDACTED]')
    .replace(/\bgithub_pat_[A-Za-z0-9_]{20,}\b/gu, '[REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b/gu, '[REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/gu, '[REDACTED]')
    .replace(/\b(?:(?:AKIA|ASIA)[A-Za-z0-9]{16,}|AKID[A-Za-z0-9]{12,})\b/gu, '[REDACTED]')
    .slice(0, maximumLength);
}

export function redactProviderCorrelation(value: string | null | undefined): string | null {
  if (!value?.trim()) return null;
  return redactCredentialText(value, MAX_PROVIDER_CORRELATION_LENGTH) || null;
}

export function redactRunFailureDetail(value: string): string {
  return redactCredentialText(value, MAX_RUN_FAILURE_DETAIL_LENGTH);
}

export function redactExternalFailureDetail(value: string, maximumLength: number): string {
  return redactCredentialText(value.replace(/https?:\/\/[^\s]+/giu, '[redacted-url]'), maximumLength);
}

export function redactKnowledgeFailureDetail(value: string, maximumLength: number): string {
  return redactExternalFailureDetail(value, maximumLength);
}

export function redactConnectorDiagnostic<
  T extends { message: string; tools: Array<{ name: string; description: string }> },
>(diagnostic: T): T {
  return {
    ...diagnostic,
    message: redactExternalFailureDetail(diagnostic.message, 2_000),
    tools: diagnostic.tools.map((tool) => ({
      ...tool,
      description: redactCredentialText(tool.description, 2_000),
    })),
  };
}

export function redactRunFailureCategory(value: string): string {
  return redactCredentialText(value, MAX_RUN_FAILURE_CATEGORY_LENGTH);
}

const MAX_FAILURE_PAYLOAD_DEPTH = 8;

function redactFailurePayloadAtDepth(
  payload: Record<string, unknown>,
  depth: number,
): Record<string, unknown> {
  const redacted = { ...payload };
  if (typeof redacted.category === 'string') {
    redacted.category = redactRunFailureCategory(redacted.category);
  }
  if (typeof redacted.code === 'string') {
    redacted.code = redactRunFailureCategory(redacted.code);
  }
  for (const field of [
    'detail',
    'failureDetail',
    'failure',
    'error',
    'message',
    'errorMessage',
    'finalError',
  ] as const) {
    if (typeof redacted[field] === 'string') {
      redacted[field] = redactRunFailureDetail(redacted[field]);
    }
  }
  for (const field of ['failure', 'error'] as const) {
    const nested = redacted[field];
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      redacted[field] =
        depth < MAX_FAILURE_PAYLOAD_DEPTH
          ? redactFailurePayloadAtDepth(nested as Record<string, unknown>, depth + 1)
          : '[REDACTED]';
    }
  }
  if (Array.isArray(redacted.failures)) {
    redacted.failures = redacted.failures.map((failure) =>
      typeof failure === 'string'
        ? redactRunFailureDetail(failure)
        : failure && typeof failure === 'object' && !Array.isArray(failure)
          ? depth < MAX_FAILURE_PAYLOAD_DEPTH
            ? redactFailurePayloadAtDepth(failure as Record<string, unknown>, depth + 1)
            : '[REDACTED]'
          : failure,
    );
  }
  return redacted;
}

export function redactFailurePayload(payload: Record<string, unknown>): Record<string, unknown> {
  return redactFailurePayloadAtDepth(payload, 0);
}

export function redactFailureEventPayload(
  eventType: string,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  return /(?:^|[._-])(?:failed|failure|rejected|error)(?:$|[._-])/iu.test(eventType) ||
    Array.isArray(payload.failures) ||
    Object.hasOwn(payload, 'errorMessage') ||
    Object.hasOwn(payload, 'finalError')
    ? redactFailurePayload(payload)
    : payload;
}

export function redactRemoteProductEventPayload(
  frameKind: string,
  framePayload: Record<string, unknown>,
): Record<string, unknown> {
  if (frameKind !== 'product_event') return framePayload;
  const eventType = framePayload.type;
  const eventPayload = framePayload.payload;
  if (
    typeof eventType !== 'string' ||
    !eventPayload ||
    typeof eventPayload !== 'object' ||
    Array.isArray(eventPayload)
  ) {
    return framePayload;
  }
  return {
    ...framePayload,
    payload: redactFailureEventPayload(eventType, eventPayload as Record<string, unknown>),
  };
}
