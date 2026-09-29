import { Type, type Static } from 'typebox';

import { V3PrincipalSchema } from './v3.ts';

export const V3AuthModeSchema = Type.Union([
  Type.Literal('feishu'),
  Type.Literal('legacy'),
  Type.Literal('api-key'),
]);
export type V3AuthMode = Static<typeof V3AuthModeSchema>;

const TokenSchema = Type.String({ minLength: 16, maxLength: 256, pattern: '^[A-Za-z0-9._~-]+$' });
const PkceVerifierSchema = Type.String({ minLength: 43, maxLength: 128, pattern: '^[A-Za-z0-9._~-]+$' });
const NonceSchema = Type.String({ minLength: 16, maxLength: 256, pattern: '^[A-Za-z0-9._~-]+$' });

export const V3AuthUnauthenticatedSchema = Type.Object(
  { authenticated: Type.Literal(false) },
  { additionalProperties: false },
);

export const V3AuthSessionSchema = Type.Union([
  V3AuthUnauthenticatedSchema,
  Type.Object(
    { authenticated: Type.Literal(true), principal: V3PrincipalSchema },
    { additionalProperties: false },
  ),
]);
export type V3AuthSession = Static<typeof V3AuthSessionSchema>;

export const V3FeishuDesktopStartInputSchema = Type.Object(
  {
    transactionId: TokenSchema,
    codeChallenge: PkceVerifierSchema,
    nonce: NonceSchema,
  },
  { additionalProperties: false },
);
export type V3FeishuDesktopStartInput = Static<typeof V3FeishuDesktopStartInputSchema>;
/** Names retained for the Desktop adapter contract. */
export const V3FeishuDesktopAuthStartInputSchema = V3FeishuDesktopStartInputSchema;
export type V3FeishuDesktopAuthStartInput = V3FeishuDesktopStartInput;

export const V3FeishuDesktopStartResponseSchema = Type.Object(
  {
    transactionId: TokenSchema,
    /** Non-secret values echoed from the trusted Platform broker. */
    clientId: Type.String({ minLength: 1, maxLength: 128 }),
    state: Type.String({ minLength: 16, maxLength: 512, pattern: '^[A-Za-z0-9._~-]+$' }),
    authorizationUrl: Type.String({ minLength: 1, maxLength: 4_096, format: 'uri' }),
    redirectUri: Type.String({ minLength: 1, maxLength: 2_048, format: 'uri' }),
    expiresAt: Type.String({ format: 'date-time' }),
  },
  { additionalProperties: false },
);
export type V3FeishuDesktopStartResponse = Static<typeof V3FeishuDesktopStartResponseSchema>;
export const V3FeishuDesktopAuthStartSchema = V3FeishuDesktopStartResponseSchema;
export type V3FeishuDesktopAuthStart = V3FeishuDesktopStartResponse;

export const V3FeishuDesktopCompleteInputSchema = Type.Object(
  {
    transactionId: TokenSchema,
    codeVerifier: PkceVerifierSchema,
    nonce: NonceSchema,
  },
  { additionalProperties: false },
);
export type V3FeishuDesktopCompleteInput = Static<typeof V3FeishuDesktopCompleteInputSchema>;
export const V3FeishuDesktopAuthCompleteInputSchema = V3FeishuDesktopCompleteInputSchema;
export type V3FeishuDesktopAuthCompleteInput = V3FeishuDesktopCompleteInput;

/**
 * Desktop completion is deliberately a discriminated HTTP/body contract:
 * 202 carries `pending`, 410 carries `denied`/`expired`, and 200 carries
 * the authenticated session projection.  Keeping all body variants in one
 * schema lets each adapter reject status-shaped responses that are missing
 * required fields before they cross the platform boundary.
 */
export const V3FeishuDesktopCompleteResponseSchema = Type.Union([
  Type.Object(
    { status: Type.Literal('pending'), pollAfterMs: Type.Integer({ minimum: 250, maximum: 60_000 }) },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      authenticated: Type.Literal(true),
      principal: V3PrincipalSchema,
      sessionToken: Type.String({ minLength: 16, maxLength: 4_096, pattern: '^[A-Za-z0-9._~-]+$' }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      status: Type.Union([Type.Literal('denied'), Type.Literal('expired')]),
      pollAfterMs: Type.Optional(Type.Integer({ minimum: 250, maximum: 60_000 })),
    },
    { additionalProperties: false },
  ),
]);
export type V3FeishuDesktopCompleteResponse = Static<typeof V3FeishuDesktopCompleteResponseSchema>;
/** Alias retained for callers using the explicit auth naming. */
export const V3FeishuDesktopAuthCompleteSchema = V3FeishuDesktopCompleteResponseSchema;
export type V3FeishuDesktopAuthComplete = V3FeishuDesktopCompleteResponse;

export const V3FeishuDesktopPollResponseSchema = Type.Object(
  {
    status: Type.Union([
      Type.Literal('pending'),
      Type.Literal('authorized'),
      Type.Literal('denied'),
      Type.Literal('expired'),
    ]),
  },
  { additionalProperties: false },
);
export type V3FeishuDesktopPollResponse = Static<typeof V3FeishuDesktopPollResponseSchema>;

/** OpenAPI coverage for the authentication boundary (kept separate to avoid a v3.ts import cycle). */
export const V3_FEISHU_OPENAPI_SCHEMA_COVERAGE = {
  // A distinct schema object keeps the OpenAPI component map one-to-one while
  // the session union continues to reuse the canonical V3 principal contract.
  Principal: Type.Object(
    {
      userId: Type.String({ format: 'uuid' }),
      workspaceId: Type.String({ format: 'uuid' }),
      displayName: Type.String({ minLength: 1, maxLength: 200 }),
      role: Type.Union([
        Type.Literal('owner'),
        Type.Literal('admin'),
        Type.Literal('member'),
        Type.Literal('viewer'),
      ]),
      permissions: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
        maxItems: 500,
        uniqueItems: true,
      }),
    },
    { additionalProperties: false },
  ),
  AuthSession: V3AuthSessionSchema,
  AuthUnauthenticated: V3AuthUnauthenticatedSchema,
  FeishuDesktopAuthStartInput: V3FeishuDesktopAuthStartInputSchema,
  FeishuDesktopAuthStart: V3FeishuDesktopAuthStartSchema,
  FeishuDesktopAuthCompleteInput: V3FeishuDesktopAuthCompleteInputSchema,
  FeishuDesktopAuthComplete: V3FeishuDesktopAuthCompleteSchema,
  FeishuDesktopAuthPoll: V3FeishuDesktopPollResponseSchema,
} as const;
