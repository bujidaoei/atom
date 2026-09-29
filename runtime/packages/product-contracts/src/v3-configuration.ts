import { Type, type Static } from 'typebox';

const uuidPattern = '[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';

export const SecretReferenceSchema = Type.String({
  pattern: `^secret://workspace/${uuidPattern}/${uuidPattern}$`,
});
export type SecretReference = Static<typeof SecretReferenceSchema>;

export const SecretReferenceStatusSchema = Type.Object(
  {
    configured: Type.Boolean(),
    hint: Type.Optional(Type.String({ pattern: '^••••.{4}$' })),
  },
  { additionalProperties: false },
);
export type SecretReferenceStatus = Static<typeof SecretReferenceStatusSchema>;

export const ProtectedConfigurationSchema = Type.Object(
  {
    aiGateway: Type.Object(
      {
        model: Type.String({ maxLength: 200 }),
      },
      { additionalProperties: false },
    ),
    cos: Type.Object(
      {
        endpoint: Type.String({ minLength: 1, maxLength: 2_048 }),
        bucket: Type.String({ minLength: 1, maxLength: 255 }),
        region: Type.String({ minLength: 1, maxLength: 255 }),
        prefix: Type.String({ maxLength: 1_024 }),
        accessKeyRef: SecretReferenceSchema,
        secretKeyRef: SecretReferenceSchema,
      },
      { additionalProperties: false },
    ),
    feishu: Type.Object(
      {
        appIdRef: SecretReferenceSchema,
        appSecretRef: SecretReferenceSchema,
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
export type ProtectedConfiguration = Static<typeof ProtectedConfigurationSchema>;

const AiGatewayStatusSchema = Type.Object(
  {
    configured: Type.Boolean(),
    model: Type.String({ maxLength: 200 }),
    serverManaged: Type.Literal(true),
  },
  { additionalProperties: false },
);

const CosStatusSchema = Type.Object(
  {
    configured: Type.Boolean(),
    endpointConfigured: Type.Boolean(),
    bucketConfigured: Type.Boolean(),
    regionConfigured: Type.Boolean(),
    prefixConfigured: Type.Boolean(),
    accessKey: SecretReferenceStatusSchema,
    secretKey: SecretReferenceStatusSchema,
  },
  { additionalProperties: false },
);

const FeishuStatusSchema = Type.Object(
  {
    configured: Type.Boolean(),
    appId: SecretReferenceStatusSchema,
    appSecret: SecretReferenceStatusSchema,
  },
  { additionalProperties: false },
);

export const ProtectedConfigurationIssueSchema = Type.Union([
  Type.Literal('ai_gateway_model_missing'),
  Type.Literal('cos_endpoint_missing'),
  Type.Literal('cos_bucket_missing'),
  Type.Literal('cos_region_missing'),
  Type.Literal('cos_access_key_missing'),
  Type.Literal('cos_secret_key_missing'),
  Type.Literal('feishu_app_id_missing'),
  Type.Literal('feishu_app_secret_missing'),
]);
export type ProtectedConfigurationIssue = Static<typeof ProtectedConfigurationIssueSchema>;

export const ProtectedConfigurationStatusSchema = Type.Object(
  {
    ready: Type.Boolean(),
    aiGateway: AiGatewayStatusSchema,
    cos: CosStatusSchema,
    feishu: FeishuStatusSchema,
    issues: Type.Array(ProtectedConfigurationIssueSchema),
  },
  { additionalProperties: false },
);
export type ProtectedConfigurationStatus = Static<typeof ProtectedConfigurationStatusSchema>;

export interface SecretReferenceInspector {
  status(reference: SecretReference): Promise<SecretReferenceStatus>;
}

function isConfigured(value: string): boolean {
  return value.trim().length > 0;
}

export async function inspectProtectedConfiguration(
  configuration: ProtectedConfiguration,
  secrets: SecretReferenceInspector,
): Promise<ProtectedConfigurationStatus> {
  const [cosAccessKey, cosSecretKey, feishuAppId, feishuAppSecret] = await Promise.all([
    secrets.status(configuration.cos.accessKeyRef),
    secrets.status(configuration.cos.secretKeyRef),
    secrets.status(configuration.feishu.appIdRef),
    secrets.status(configuration.feishu.appSecretRef),
  ]);
  const modelConfigured = isConfigured(configuration.aiGateway.model);
  const endpointConfigured = isConfigured(configuration.cos.endpoint);
  const bucketConfigured = isConfigured(configuration.cos.bucket);
  const regionConfigured = isConfigured(configuration.cos.region);
  const prefixConfigured = isConfigured(configuration.cos.prefix);
  const issues: ProtectedConfigurationIssue[] = [];
  if (!modelConfigured) issues.push('ai_gateway_model_missing');
  if (!endpointConfigured) issues.push('cos_endpoint_missing');
  if (!bucketConfigured) issues.push('cos_bucket_missing');
  if (!regionConfigured) issues.push('cos_region_missing');
  if (!cosAccessKey.configured) issues.push('cos_access_key_missing');
  if (!cosSecretKey.configured) issues.push('cos_secret_key_missing');
  if (!feishuAppId.configured) issues.push('feishu_app_id_missing');
  if (!feishuAppSecret.configured) issues.push('feishu_app_secret_missing');

  const aiGateway = {
    configured: modelConfigured,
    model: configuration.aiGateway.model.trim(),
    serverManaged: true as const,
  };
  const cos = {
    configured:
      endpointConfigured &&
      bucketConfigured &&
      regionConfigured &&
      cosAccessKey.configured &&
      cosSecretKey.configured,
    endpointConfigured,
    bucketConfigured,
    regionConfigured,
    prefixConfigured,
    accessKey: cosAccessKey,
    secretKey: cosSecretKey,
  };
  const feishu = {
    configured: feishuAppId.configured && feishuAppSecret.configured,
    appId: feishuAppId,
    appSecret: feishuAppSecret,
  };
  return {
    ready: aiGateway.configured && cos.configured && feishu.configured,
    aiGateway,
    cos,
    feishu,
    issues,
  };
}
