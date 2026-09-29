import { Type, type Static } from 'typebox';

/** Stable identifier for every V3 product boundary. */
export const V3_PRODUCT_CONTRACT_VERSION = '3.0.0' as const;

const UuidSchema = Type.String({ format: 'uuid' });
const DateTimeSchema = Type.String({ format: 'date-time' });
const Sha256Schema = Type.String({ pattern: '^[a-f0-9]{64}$' });
const JsonObjectSchema = Type.Record(Type.String(), Type.Unknown());
const NullableUuidSchema = Type.Union([UuidSchema, Type.Null()]);
const NullableDateTimeSchema = Type.Union([DateTimeSchema, Type.Null()]);

const PrincipalRoleSchema = Type.Union([
  Type.Literal('owner'),
  Type.Literal('admin'),
  Type.Literal('member'),
  Type.Literal('viewer'),
]);

export const V3PrincipalSchema = Type.Object(
  {
    userId: UuidSchema,
    workspaceId: UuidSchema,
    displayName: Type.String({ minLength: 1, maxLength: 200 }),
    role: PrincipalRoleSchema,
    permissions: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
      maxItems: 500,
      uniqueItems: true,
    }),
  },
  { additionalProperties: false },
);
export type V3Principal = Static<typeof V3PrincipalSchema>;

export const V3PaginationInputSchema = Type.Object(
  {
    cursor: Type.Optional(Type.String({ minLength: 1, maxLength: 1_000 })),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  },
  { additionalProperties: false },
);
export type V3PaginationInput = Static<typeof V3PaginationInputSchema>;

export const V3KnowledgeCatalogSchema = Type.Union([
  Type.Literal('created'),
  Type.Literal('shared'),
  Type.Literal('featured'),
]);
export type V3KnowledgeCatalog = Static<typeof V3KnowledgeCatalogSchema>;

export const V3KnowledgeListInputSchema = Type.Object(
  {
    cursor: Type.Optional(Type.String({ minLength: 1, maxLength: 1_000 })),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
    catalog: Type.Optional(V3KnowledgeCatalogSchema),
  },
  { additionalProperties: false },
);
export type V3KnowledgeListInput = Static<typeof V3KnowledgeListInputSchema>;

export const V3PageSchema = Type.Object(
  {
    items: Type.Array(Type.Unknown()),
    nextCursor: Type.Union([Type.String({ maxLength: 1_000 }), Type.Null()]),
    hasMore: Type.Boolean(),
  },
  { additionalProperties: false },
);
export interface V3Page<T> {
  items: T[];
  nextCursor: string | null;
  hasMore: boolean;
}

export const V3ProblemSchema = Type.Object(
  {
    type: Type.String({ minLength: 1, maxLength: 2_000 }),
    title: Type.String({ minLength: 1, maxLength: 500 }),
    status: Type.Integer({ minimum: 400, maximum: 599 }),
    detail: Type.Optional(Type.String({ maxLength: 10_000 })),
    correlationId: Type.String({ minLength: 1, maxLength: 200 }),
    fieldErrors: Type.Optional(
      Type.Record(
        Type.String({ minLength: 1, maxLength: 500 }),
        Type.String({ minLength: 1, maxLength: 2_000 }),
      ),
    ),
    retryable: Type.Optional(Type.Boolean()),
  },
  { additionalProperties: false },
);
export type V3Problem = Static<typeof V3ProblemSchema>;

export const V3IdempotencySchema = Type.Object(
  {
    key: Type.String({ minLength: 16, maxLength: 200 }),
    requestHash: Sha256Schema,
  },
  { additionalProperties: false },
);
export type V3Idempotency = Static<typeof V3IdempotencySchema>;

export const V3ExpectedVersionSchema = Type.Object(
  { expectedVersion: Type.Integer({ minimum: 1 }) },
  { additionalProperties: false },
);
export type V3ExpectedVersion = Static<typeof V3ExpectedVersionSchema>;

export const V3VersionMetadataSchema = Type.Object(
  {
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3VersionMetadata = Static<typeof V3VersionMetadataSchema>;

export const V3AvatarObjectSchema = Type.Object(
  {
    id: UuidSchema,
    mediaType: Type.Union([Type.Literal('image/png'), Type.Literal('image/jpeg')]),
    sizeBytes: Type.Integer({ minimum: 1, maximum: 2 * 1024 * 1024 }),
    sha256: Sha256Schema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3AvatarObject = Static<typeof V3AvatarObjectSchema>;

const WakerEnvironmentSchema = Type.Union([Type.Literal('local'), Type.Literal('cloud')]);
const WakerStatusSchema = Type.Union([
  Type.Literal('draft'),
  Type.Literal('enabling'),
  Type.Literal('online'),
  Type.Literal('offline'),
  Type.Literal('disabled'),
  Type.Literal('archived'),
]);

export const V3WakerResourceSelectionSchema = Type.Object(
  {
    roleSkillNames: Type.Optional(
      Type.Array(Type.String({ minLength: 1, maxLength: 160 }), { maxItems: 100, uniqueItems: true }),
    ),
    knowledgeBaseIds: Type.Optional(Type.Array(UuidSchema, { maxItems: 50, uniqueItems: true })),
    mcpConfigs: Type.Optional(
      Type.Array(Type.String({ minLength: 1, maxLength: 100_000 }), { maxItems: 20 }),
    ),
    skillPackagePreparationIds: Type.Optional(Type.Array(UuidSchema, { maxItems: 50, uniqueItems: true })),
    roleSkillVersionIds: Type.Optional(Type.Array(UuidSchema, { maxItems: 50, uniqueItems: true })),
  },
  { additionalProperties: false },
);
export type V3WakerResourceSelection = Static<typeof V3WakerResourceSelectionSchema>;

export const V3CreateWakerSchema = Type.Object(
  {
    roleTemplateVersionId: Type.Optional(NullableUuidSchema),
    name: Type.String({ minLength: 1, maxLength: 80 }),
    roleName: Type.String({ minLength: 1, maxLength: 120 }),
    bio: Type.String({ minLength: 1, maxLength: 10_000, pattern: '\\S' }),
    avatarObjectId: Type.Optional(NullableUuidSchema),
    environment: WakerEnvironmentSchema,
    deviceId: Type.Optional(NullableUuidSchema),
    resources: Type.Optional(V3WakerResourceSelectionSchema),
  },
  { additionalProperties: false },
);
export type V3CreateWaker = Static<typeof V3CreateWakerSchema>;

/**
 * Credential-free core payload accepted by a Waker package import.
 * Optional package resources (skills, connectors, automations, memory archives
 * and permissions) deliberately stay outside this contract until their
 * install transactions are defined by the product boundary.
 */
export interface V3WakerPackageCoreImport {
  waker: V3CreateWaker;
  documents: {
    identity: string;
    persona: string;
    bible: string;
  };
}

export const V3UpdateWakerSchema = Type.Object(
  {
    expectedVersion: Type.Integer({ minimum: 1 }),
    roleTemplateVersionId: Type.Optional(NullableUuidSchema),
    name: Type.String({ minLength: 1, maxLength: 80 }),
    roleName: Type.String({ minLength: 1, maxLength: 120 }),
    bio: Type.String({ maxLength: 10_000 }),
    avatarObjectId: Type.Optional(NullableUuidSchema),
    environment: WakerEnvironmentSchema,
    deviceId: Type.Optional(NullableUuidSchema),
  },
  { additionalProperties: false },
);
export type V3UpdateWaker = Static<typeof V3UpdateWakerSchema>;

export const V3WakerLifecycleInputSchema = Type.Object(
  {
    action: Type.Union([Type.Literal('enable'), Type.Literal('disable'), Type.Literal('archive')]),
    expectedVersion: Type.Integer({ minimum: 1 }),
    acknowledgeGroupRemoval: Type.Optional(Type.Boolean()),
  },
  { additionalProperties: false },
);
export type V3WakerLifecycleInput = Static<typeof V3WakerLifecycleInputSchema>;

export const V3DefaultQuestionsSchema = Type.Object(
  {
    EN: Type.Array(Type.String({ minLength: 1, maxLength: 500 }), { maxItems: 3 }),
    ZH: Type.Array(Type.String({ minLength: 1, maxLength: 500 }), { maxItems: 3 }),
  },
  { additionalProperties: false },
);
export type V3DefaultQuestions = Static<typeof V3DefaultQuestionsSchema>;

export const V3CreateRoleTemplateSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 20 }),
    summary: Type.String({ minLength: 1, maxLength: 2_000, pattern: '\\S' }),
    avatarObjectId: Type.Optional(NullableUuidSchema),
    identity: Type.String({ maxLength: 100_000 }),
    persona: Type.String({ maxLength: 100_000 }),
    bible: Type.String({ maxLength: 100_000 }),
    defaultQuestions: Type.Optional(V3DefaultQuestionsSchema),
    mcpConfigs: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 20_000 }), { maxItems: 20 })),
    skillPackagePreparationIds: Type.Optional(Type.Array(UuidSchema, { maxItems: 50, uniqueItems: true })),
  },
  { additionalProperties: false },
);
export type V3CreateRoleTemplate = Static<typeof V3CreateRoleTemplateSchema>;

export const V3UpdateRoleTemplateSchema = Type.Object(
  {
    ...V3CreateRoleTemplateSchema.properties,
    expectedVersionId: UuidSchema,
    roleSkillVersionIds: Type.Array(UuidSchema, { maxItems: 50, uniqueItems: true }),
  },
  { additionalProperties: false },
);
export type V3UpdateRoleTemplate = Static<typeof V3UpdateRoleTemplateSchema>;

export const V3RoleSkillVersionSchema = Type.Object(
  {
    resourceId: UuidSchema,
    versionId: UuidSchema,
    name: Type.String({ minLength: 1, maxLength: 80 }),
    description: Type.String({ minLength: 1, maxLength: 500 }),
    source: Type.Union([Type.Literal('upload'), Type.Literal('marketplace')]),
    marketplaceSkillId: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
    fileName: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.Union([
      Type.Literal('text/markdown'),
      Type.Literal('application/zip'),
      Type.Literal('application/gzip'),
    ]),
    sizeBytes: Type.Integer({ minimum: 1, maximum: 20 * 1024 * 1024 }),
    packageSha256: Sha256Schema,
    contentSha256: Sha256Schema,
    selfEvolution: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3RoleSkillVersion = Static<typeof V3RoleSkillVersionSchema>;

export const V3GenerateRoleDocumentsInputSchema = Type.Object(
  {
    name: V3CreateRoleTemplateSchema.properties.name,
    description: V3CreateRoleTemplateSchema.properties.summary,
  },
  { additionalProperties: false },
);
export type V3GenerateRoleDocumentsInput = Static<typeof V3GenerateRoleDocumentsInputSchema>;

export const V3RoleDocumentsSchema = Type.Object(
  {
    identityMd: Type.String({ ...V3CreateRoleTemplateSchema.properties.identity, minLength: 1 }),
    personaMd: Type.String({ ...V3CreateRoleTemplateSchema.properties.persona, minLength: 1 }),
    bibleMd: Type.String({ ...V3CreateRoleTemplateSchema.properties.bible, minLength: 1 }),
  },
  { additionalProperties: false },
);
export type V3RoleDocuments = Static<typeof V3RoleDocumentsSchema>;

export const V3RoleTemplateVersionSchema = Type.Object(
  {
    id: UuidSchema,
    number: Type.Integer({ minimum: 1 }),
    identity: Type.String({ maxLength: 100_000 }),
    persona: Type.String({ maxLength: 100_000 }),
    bible: Type.String({ maxLength: 100_000 }),
    coreCapabilities: Type.String({ maxLength: 100_000 }),
    workStyles: Type.String({ maxLength: 100_000 }),
    deliveryCommitments: Type.String({ maxLength: 100_000 }),
    defaultQuestions: Type.Optional(V3DefaultQuestionsSchema),
    skillVersions: Type.Optional(Type.Array(V3RoleSkillVersionSchema, { maxItems: 50 })),
    mcpConfigs: Type.Optional(
      Type.Array(Type.String({ minLength: 1, maxLength: 100_000 }), { maxItems: 20 }),
    ),
    createdBy: NullableUuidSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3RoleTemplateVersion = Static<typeof V3RoleTemplateVersionSchema>;

export const V3RoleTemplateSchema = Type.Object(
  {
    id: UuidSchema,
    name: Type.String({ minLength: 1, maxLength: 120 }),
    summary: Type.String({ maxLength: 2_000 }),
    avatarObjectId: Type.Optional(NullableUuidSchema),
    source: Type.Union([Type.Literal('builtin'), Type.Literal('custom')]),
    status: Type.Union([Type.Literal('draft'), Type.Literal('active'), Type.Literal('archived')]),
    currentVersion: V3RoleTemplateVersionSchema,
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3RoleTemplate = Static<typeof V3RoleTemplateSchema>;

export const V3WakerSchema = Type.Object(
  {
    id: UuidSchema,
    systemKind: Type.Optional(Type.Literal('wakey')),
    roleTemplateVersionId: Type.Optional(NullableUuidSchema),
    roleTemplateSource: Type.Optional(Type.Union([Type.Literal('builtin'), Type.Literal('custom')])),
    name: Type.String({ minLength: 1, maxLength: 80 }),
    roleName: Type.String({ minLength: 1, maxLength: 120 }),
    bio: Type.String({ maxLength: 10_000 }),
    avatarObjectId: Type.Optional(NullableUuidSchema),
    environment: WakerEnvironmentSchema,
    deviceId: Type.Optional(NullableUuidSchema),
    status: WakerStatusSchema,
    taskCount: Type.Optional(Type.Integer({ minimum: 0 })),
    lastRunAt: Type.Optional(Type.Union([DateTimeSchema, Type.Null()])),
    effectiveConfigurationVersionId: Type.Optional(NullableUuidSchema),
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Waker = Static<typeof V3WakerSchema>;

export const V3WakerShareConfigSchema = Type.Object(
  {
    expirationPreset: Type.Union([
      Type.Literal('1d'),
      Type.Literal('3d'),
      Type.Literal('7d'),
      Type.Literal('30d'),
    ]),
    usagePreset: Type.Union([Type.Literal('once'), Type.Literal('unlimited')]),
  },
  { additionalProperties: false },
);
export type V3WakerShareConfig = Static<typeof V3WakerShareConfigSchema>;

export const V3WakerShareIncludeOptionsSchema = Type.Object(
  {
    profile: Type.Boolean(),
    about: Type.Boolean(),
    skills: Type.Boolean(),
    connectors: Type.Boolean(),
    automations: Type.Boolean(),
    memory: Type.Boolean(),
    projects: Type.Boolean(),
    permissions: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3WakerShareIncludeOptions = Static<typeof V3WakerShareIncludeOptionsSchema>;

export const V3WakerShareCreateSchema = Type.Object(
  {
    includeOptions: Type.Optional(V3WakerShareIncludeOptionsSchema),
    shareConfig: Type.Optional(V3WakerShareConfigSchema),
  },
  { additionalProperties: false },
);
export type V3WakerShareCreate = Static<typeof V3WakerShareCreateSchema>;

export const V3WakerShareCreatedSchema = Type.Object(
  { shareId: Type.String({ minLength: 1 }), packageSize: Type.Integer({ minimum: 0 }) },
  { additionalProperties: false },
);
export type V3WakerShareCreated = Static<typeof V3WakerShareCreatedSchema>;

export const V3WakerShareLinkRowSchema = Type.Object(
  {
    share_id: Type.String({ minLength: 1 }),
    status: Type.String({ minLength: 1 }),
    created_at: DateTimeSchema,
    share_count: Type.Optional(Type.Integer({ minimum: 0 })),
    extension_name: Type.Optional(Type.String({ maxLength: 160 })),
    description: Type.Optional(Type.String({ maxLength: 10_000 })),
    author: Type.Optional(Type.String({ maxLength: 160 })),
    extension_version: Type.Optional(Type.String({ maxLength: 80 })),
    local_avatar: Type.Optional(Type.String({ maxLength: 2_000 })),
    expires_at: Type.Optional(NullableDateTimeSchema),
    failure_reason: Type.Optional(Type.String({ maxLength: 2_000 })),
  },
  { additionalProperties: false },
);
export type V3WakerShareLinkRow = Static<typeof V3WakerShareLinkRowSchema>;

export const V3WakerShareLinkListQuerySchema = Type.Object(
  {
    page: Type.Optional(Type.Integer({ minimum: 1, maximum: 10_000 })),
    pageSize: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
    status: Type.Optional(Type.String({ minLength: 1, maxLength: 40 })),
  },
  { additionalProperties: false },
);
export type V3WakerShareLinkListQuery = Static<typeof V3WakerShareLinkListQuerySchema>;

export const V3WakerShareLinkListSchema = Type.Object(
  { share_links: Type.Array(V3WakerShareLinkRowSchema) },
  { additionalProperties: false },
);
export type V3WakerShareLinkList = Static<typeof V3WakerShareLinkListSchema>;

export const V3WakerImportLinkSchema = Type.Object(
  {
    url: Type.String({ minLength: 1, maxLength: 4_000 }),
    name: Type.Optional(Type.String({ minLength: 1, maxLength: 50 })),
  },
  { additionalProperties: false },
);
export type V3WakerImportLink = Static<typeof V3WakerImportLinkSchema>;

export const V3WakerDocumentKindSchema = Type.Union([
  Type.Literal('identity'),
  Type.Literal('persona'),
  Type.Literal('bible'),
  Type.Literal('memory'),
  Type.Literal('core_capabilities'),
  Type.Literal('work_styles'),
  Type.Literal('delivery_commitments'),
]);
export type V3WakerDocumentKind = Static<typeof V3WakerDocumentKindSchema>;

export const V3WakerDocumentVersionSchema = Type.Object(
  {
    id: UuidSchema,
    documentId: UuidSchema,
    wakerId: UuidSchema,
    kind: V3WakerDocumentKindSchema,
    number: Type.Integer({ minimum: 1 }),
    content: Type.String({ maxLength: 100_000 }),
    sha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
    changeSummary: Type.String({ maxLength: 2_000 }),
    restoredFromVersionId: NullableUuidSchema,
    createdBy: NullableUuidSchema,
    createdAt: DateTimeSchema,
    isCurrent: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3WakerDocumentVersion = Static<typeof V3WakerDocumentVersionSchema>;

export const V3WakerEffectiveSnapshotSchema = Type.Object(
  {
    profile: Type.Object(
      {
        name: Type.String({ minLength: 1, maxLength: 80 }),
        roleName: Type.String({ minLength: 1, maxLength: 120 }),
        bio: Type.String({ maxLength: 10_000 }),
        roleTemplateVersionId: NullableUuidSchema,
        avatarObjectId: NullableUuidSchema,
      },
      { additionalProperties: false },
    ),
    documents: Type.Object(
      {
        identity: UuidSchema,
        persona: UuidSchema,
        bible: UuidSchema,
        memory: UuidSchema,
        // The official context documents behind the home About grid; optional
        // so configuration snapshots persisted before the six-document model
        // stay valid and immutable.
        core_capabilities: Type.Optional(UuidSchema),
        work_styles: Type.Optional(UuidSchema),
        delivery_commitments: Type.Optional(UuidSchema),
      },
      { additionalProperties: false },
    ),
    resources: Type.Object(
      {
        skillInstallationVersionIds: Type.Array(UuidSchema, { uniqueItems: true }),
        pluginInstallationVersionIds: Type.Optional(Type.Array(UuidSchema, { uniqueItems: true })),
        knowledgeBindingVersionIds: Type.Array(UuidSchema, { uniqueItems: true }),
        connectorToolSelectionVersionIds: Type.Array(UuidSchema, { uniqueItems: true }),
        imPairingVersionIds: Type.Array(UuidSchema, { uniqueItems: true }),
        permissionPolicyVersionIds: Type.Array(UuidSchema, { uniqueItems: true }),
      },
      { additionalProperties: false },
    ),
    modelPolicy: Type.Record(Type.String(), Type.Unknown()),
  },
  { additionalProperties: false },
);
export type V3WakerEffectiveSnapshot = Static<typeof V3WakerEffectiveSnapshotSchema>;

export const V3WakerConfigurationVersionSchema = Type.Object(
  {
    id: UuidSchema,
    wakerId: UuidSchema,
    number: Type.Integer({ minimum: 1 }),
    effectiveSnapshot: V3WakerEffectiveSnapshotSchema,
    snapshotSha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
    createdBy: NullableUuidSchema,
    reason: Type.String({ maxLength: 2_000 }),
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3WakerConfigurationVersion = Static<typeof V3WakerConfigurationVersionSchema>;

export const V3UpdateWakerDocumentSchema = Type.Object(
  {
    expectedConfigurationVersionId: UuidSchema,
    content: Type.String({ maxLength: 100_000 }),
    changeSummary: Type.String({ minLength: 1, maxLength: 2_000 }),
  },
  { additionalProperties: false },
);
export type V3UpdateWakerDocument = Static<typeof V3UpdateWakerDocumentSchema>;

export const V3RestoreWakerDocumentSchema = Type.Object(
  {
    expectedConfigurationVersionId: UuidSchema,
    versionId: UuidSchema,
    changeSummary: Type.Optional(Type.String({ minLength: 1, maxLength: 2_000 })),
  },
  { additionalProperties: false },
);
export type V3RestoreWakerDocument = Static<typeof V3RestoreWakerDocumentSchema>;

export const V3DocumentComparisonSchema = Type.Object(
  {
    kind: V3WakerDocumentKindSchema,
    from: V3WakerDocumentVersionSchema,
    to: V3WakerDocumentVersionSchema,
    addedLines: Type.Integer({ minimum: 0 }),
    removedLines: Type.Integer({ minimum: 0 }),
    unchangedLines: Type.Integer({ minimum: 0 }),
  },
  { additionalProperties: false },
);
export type V3DocumentComparison = Static<typeof V3DocumentComparisonSchema>;

export const V3MemoryTimelineEventKindSchema = Type.Union([
  Type.Literal('memory_added'),
  Type.Literal('memory_updated'),
]);
export type V3MemoryTimelineEventKind = Static<typeof V3MemoryTimelineEventKindSchema>;

export const V3MemoryTimelineOriginSchema = Type.Union([
  Type.Literal('manual_update'),
  Type.Literal('user_deleted'),
]);
export type V3MemoryTimelineOrigin = Static<typeof V3MemoryTimelineOriginSchema>;

export const V3MemoryTimelineEventSchema = Type.Object(
  {
    id: UuidSchema,
    wakerId: UuidSchema,
    scope: Type.Union([Type.Literal('waker'), Type.Literal('project')]),
    projectId: NullableUuidSchema,
    kind: V3MemoryTimelineEventKindSchema,
    title: Type.String({ minLength: 1, maxLength: 2_000 }),
    description: Type.String({ maxLength: 4_000 }),
    origin: V3MemoryTimelineOriginSchema,
    documentVersionId: NullableUuidSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3MemoryTimelineEvent = Static<typeof V3MemoryTimelineEventSchema>;

export const V3MemoryTimelineQuerySchema = Type.Object(
  {
    scope: Type.Optional(Type.Union([Type.Literal('waker'), Type.Literal('project')])),
    projectId: Type.Optional(UuidSchema),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  },
  { additionalProperties: false },
);
export type V3MemoryTimelineQuery = Static<typeof V3MemoryTimelineQuerySchema>;

export const V3PermissionPolicyKindSchema = Type.Union([
  Type.Literal('tool_guard'),
  Type.Literal('file_guard'),
  Type.Literal('builtin_tools'),
  Type.Literal('model_security'),
  Type.Literal('host_capability'),
]);
export type V3PermissionPolicyKind = Static<typeof V3PermissionPolicyKindSchema>;

export const V3ToolDecisionSchema = Type.Union([
  Type.Literal('allow'),
  Type.Literal('ask'),
  Type.Literal('deny'),
]);
export type V3ToolDecision = Static<typeof V3ToolDecisionSchema>;

export const V3PermissionPolicyConfigurationSchema = Type.Union([
  Type.Object(
    {
      kind: Type.Literal('tool_guard'),
      enabled: Type.Boolean(),
      enabledRuleIds: Type.Array(Type.String({ minLength: 1, maxLength: 120 }), { uniqueItems: true }),
      enabledShellEscapeRuleIds: Type.Array(Type.String({ minLength: 1, maxLength: 120 }), {
        uniqueItems: true,
      }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      kind: Type.Literal('file_guard'),
      enabled: Type.Boolean(),
      sensitivePaths: Type.Array(Type.String({ minLength: 1, maxLength: 2_000 }), { uniqueItems: true }),
      imWorkspaceOnly: Type.Boolean(),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      kind: Type.Literal('builtin_tools'),
      enabled: Type.Boolean(),
      decisions: Type.Record(Type.String({ minLength: 1, maxLength: 120 }), V3ToolDecisionSchema),
    },
    { additionalProperties: false },
  ),
  Type.Union([
    Type.Object(
      {
        kind: Type.Literal('model_security'),
        enabled: Type.Literal(true),
        allowedModels: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
          minItems: 1,
          uniqueItems: true,
        }),
        crossDeviceSync: Type.Boolean(),
      },
      { additionalProperties: false },
    ),
    Type.Object(
      {
        kind: Type.Literal('model_security'),
        enabled: Type.Literal(false),
        allowedModels: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
          uniqueItems: true,
        }),
        crossDeviceSync: Type.Boolean(),
      },
      { additionalProperties: false },
    ),
  ]),
  Type.Object(
    {
      kind: Type.Literal('host_capability'),
      workspaceBoundaryRequired: Type.Literal(true),
      decisions: Type.Record(Type.String({ minLength: 1, maxLength: 120 }), V3ToolDecisionSchema),
    },
    { additionalProperties: false },
  ),
]);
export type V3PermissionPolicyConfiguration = Static<typeof V3PermissionPolicyConfigurationSchema>;

export const V3PermissionPolicyVersionSchema = Type.Object(
  {
    id: UuidSchema,
    policyId: UuidSchema,
    wakerId: UuidSchema,
    kind: V3PermissionPolicyKindSchema,
    number: Type.Integer({ minimum: 1 }),
    configuration: V3PermissionPolicyConfigurationSchema,
    createdBy: NullableUuidSchema,
    createdAt: DateTimeSchema,
    isCurrent: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3PermissionPolicyVersion = Static<typeof V3PermissionPolicyVersionSchema>;

export const V3UpdatePermissionPolicySchema = Type.Object(
  {
    expectedConfigurationVersionId: UuidSchema,
    expectedPolicyVersionId: NullableUuidSchema,
    configuration: V3PermissionPolicyConfigurationSchema,
    changeSummary: Type.String({ minLength: 1, maxLength: 2_000 }),
  },
  { additionalProperties: false },
);
export type V3UpdatePermissionPolicy = Static<typeof V3UpdatePermissionPolicySchema>;

export const V3PolicyDecisionEvidenceSchema = Type.Object(
  {
    id: UuidSchema,
    runId: NullableUuidSchema,
    requestHash: Type.String({ pattern: '^[a-f0-9]{64}$' }),
    decision: V3ToolDecisionSchema,
    ruleIds: Type.Array(Type.String({ minLength: 1, maxLength: 200 })),
    policyVersionIds: Type.Array(UuidSchema, { uniqueItems: true }),
    normalizedTarget: Type.String({ maxLength: 4_000 }),
    reason: Type.String({ maxLength: 4_000 }),
    occurredAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3PolicyDecisionEvidence = Static<typeof V3PolicyDecisionEvidenceSchema>;

export const V3GroupMemberConfigurationInputSchema = Type.Object(
  {
    wakerId: UuidSchema,
    model: Type.String({ minLength: 1, maxLength: 200 }),
    workspaceReferenceId: NullableUuidSchema,
  },
  { additionalProperties: false },
);
export type V3GroupMemberConfigurationInput = Static<typeof V3GroupMemberConfigurationInputSchema>;

export const V3GroupMemberConfigurationSchema = Type.Object(
  {
    wakerId: UuidSchema,
    model: Type.Union([Type.String({ minLength: 1, maxLength: 200 }), Type.Null()]),
    workspaceReferenceId: NullableUuidSchema,
    configurationState: Type.Union([Type.Literal('ready'), Type.Literal('requires_configuration')]),
  },
  { additionalProperties: false },
);
export type V3GroupMemberConfiguration = Static<typeof V3GroupMemberConfigurationSchema>;

export const V3GroupSkillSchema = Type.Object(
  {
    id: UuidSchema,
    groupId: UuidSchema,
    versionId: UuidSchema,
    name: Type.String({ minLength: 1, maxLength: 160 }),
    description: Type.String(),
    markdown: Type.String(),
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3GroupSkill = Static<typeof V3GroupSkillSchema>;

export const V3InstallGroupSkillsSchema = Type.Object(
  {
    preparedSkillIds: Type.Array(UuidSchema, { minItems: 1, maxItems: 50, uniqueItems: true }),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3InstallGroupSkills = Static<typeof V3InstallGroupSkillsSchema>;

export const V3RemoveGroupSkillSchema = Type.Object(
  { skillId: UuidSchema, expectedVersion: Type.Integer({ minimum: 1 }) },
  { additionalProperties: false },
);
export type V3RemoveGroupSkill = Static<typeof V3RemoveGroupSkillSchema>;

export const V3CreateGroupSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 100 }),
    mission: Type.Optional(Type.String({ maxLength: 10_000 })),
    leaderWakerId: UuidSchema,
    memberWakerIds: Type.Array(UuidSchema, { minItems: 1, maxItems: 8, uniqueItems: true }),
    memberConfigurations: Type.Array(V3GroupMemberConfigurationInputSchema, {
      minItems: 1,
      maxItems: 8,
      uniqueItems: true,
    }),
  },
  { additionalProperties: false },
);
export type V3CreateGroup = Static<typeof V3CreateGroupSchema>;

export const V3RenameGroupSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 100 }),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3RenameGroup = Static<typeof V3RenameGroupSchema>;

export const V3GroupLifecycleInputSchema = Type.Object(
  {
    action: Type.Literal('archive'),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3GroupLifecycleInput = Static<typeof V3GroupLifecycleInputSchema>;

export const V3GroupMembershipVersionSchema = Type.Object(
  {
    id: UuidSchema,
    groupId: UuidSchema,
    number: Type.Integer({ minimum: 1 }),
    leaderWakerId: UuidSchema,
    memberWakerIds: Type.Array(UuidSchema, { minItems: 1, maxItems: 8, uniqueItems: true }),
    memberConfigurations: Type.Array(V3GroupMemberConfigurationSchema, {
      minItems: 1,
      maxItems: 8,
    }),
    reason: Type.String({ maxLength: 2_000 }),
    createdBy: UuidSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3GroupMembershipVersion = Static<typeof V3GroupMembershipVersionSchema>;

export const V3GroupSchema = Type.Object(
  {
    id: UuidSchema,
    name: Type.String({ minLength: 1, maxLength: 100 }),
    mission: Type.String({ maxLength: 10_000 }),
    status: Type.Union([Type.Literal('active'), Type.Literal('disabled'), Type.Literal('archived')]),
    currentMembershipVersion: V3GroupMembershipVersionSchema,
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Group = Static<typeof V3GroupSchema>;

const ConversationSubjectTypeSchema = Type.Union([Type.Literal('waker'), Type.Literal('group')]);

export const V3CreateConversationSchema = Type.Object(
  {
    subjectType: ConversationSubjectTypeSchema,
    subjectId: UuidSchema,
    title: Type.String({ minLength: 1, maxLength: 200 }),
    workspaceReferenceId: Type.Optional(NullableUuidSchema),
    projectId: Type.Optional(NullableUuidSchema),
  },
  { additionalProperties: false },
);
export type V3CreateConversation = Static<typeof V3CreateConversationSchema>;

export const V3ConversationSchema = Type.Object(
  {
    id: UuidSchema,
    subjectType: ConversationSubjectTypeSchema,
    subjectId: UuidSchema,
    title: Type.String({ minLength: 1, maxLength: 255 }),
    pinnedAt: Type.Optional(DateTimeSchema),
    workspaceReferenceId: NullableUuidSchema,
    projectId: NullableUuidSchema,
    status: Type.Union([Type.Literal('active'), Type.Literal('archived')]),
    lastEventSequence: Type.Integer({ minimum: 0 }),
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Conversation = Static<typeof V3ConversationSchema>;

export const V3UnreadQuerySchema = Type.Object(
  {
    wakerIds: Type.Array(UuidSchema, { maxItems: 200 }),
    groupIds: Type.Array(UuidSchema, { maxItems: 200 }),
  },
  { additionalProperties: false },
);
export type V3UnreadQuery = Static<typeof V3UnreadQuerySchema>;

export const V3WakerUnreadSchema = Type.Object(
  {
    wakerId: UuidSchema,
    unreadCount: Type.Integer({ minimum: 0 }),
    normalUnreadCount: Type.Integer({ minimum: 0 }),
    triggerUnreadCount: Type.Integer({ minimum: 0 }),
  },
  { additionalProperties: false },
);
export type V3WakerUnread = Static<typeof V3WakerUnreadSchema>;

export const V3GroupUnreadSchema = Type.Object(
  {
    groupId: UuidSchema,
    unreadCount: Type.Integer({ minimum: 0 }),
  },
  { additionalProperties: false },
);
export type V3GroupUnread = Static<typeof V3GroupUnreadSchema>;

export const V3UnreadCountsSchema = Type.Object(
  {
    wakers: Type.Array(V3WakerUnreadSchema),
    groups: Type.Array(V3GroupUnreadSchema),
  },
  { additionalProperties: false },
);
export type V3UnreadCounts = Static<typeof V3UnreadCountsSchema>;

export const V3MarkSubjectReadSchema = Type.Object(
  {
    subjectType: ConversationSubjectTypeSchema,
    subjectId: UuidSchema,
  },
  { additionalProperties: false },
);
export type V3MarkSubjectRead = Static<typeof V3MarkSubjectReadSchema>;

export const V3ConversationAttachmentSchema = Type.Object(
  {
    id: UuidSchema,
    fileName: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.String({ minLength: 1, maxLength: 255 }),
    sizeBytes: Type.Integer({ minimum: 1, maximum: 50 * 1024 * 1024 }),
    sha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
  },
  { additionalProperties: false },
);
export type V3ConversationAttachment = Static<typeof V3ConversationAttachmentSchema>;

export const V3SendMessageSchema = Type.Object(
  {
    content: Type.String({ maxLength: 100_000 }),
    attachmentIds: Type.Optional(Type.Array(UuidSchema, { maxItems: 20, uniqueItems: true })),
    revisionOfTaskId: Type.Optional(NullableUuidSchema),
    responseLanguage: Type.Optional(Type.Union([Type.Literal('en'), Type.Literal('zh-CN')])),
    model: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  },
  { additionalProperties: false },
);
export type V3SendMessage = Static<typeof V3SendMessageSchema>;

export const V3ConfirmGroupPlanSchema = Type.Object(
  { planVersion: Type.Integer({ minimum: 1 }) },
  { additionalProperties: false },
);
export type V3ConfirmGroupPlan = Static<typeof V3ConfirmGroupPlanSchema>;

export const V3GroupAcceptanceCriterionSchema = Type.Object(
  {
    key: Type.String({ minLength: 1, maxLength: 160 }),
    description: Type.String({ minLength: 1, maxLength: 2_000 }),
  },
  { additionalProperties: false },
);
export type V3GroupAcceptanceCriterion = Static<typeof V3GroupAcceptanceCriterionSchema>;

export const V3GroupEvidenceKindSchema = Type.Union([
  Type.Literal('artifact'),
  Type.Literal('handoff_package'),
  Type.Literal('verification_report'),
]);
export type V3GroupEvidenceKind = Static<typeof V3GroupEvidenceKindSchema>;

export const V3GroupEvidenceRequirementSchema = Type.Object(
  {
    key: Type.String({ minLength: 1, maxLength: 160 }),
    kind: V3GroupEvidenceKindSchema,
    description: Type.String({ minLength: 1, maxLength: 2_000 }),
  },
  { additionalProperties: false },
);
export type V3GroupEvidenceRequirement = Static<typeof V3GroupEvidenceRequirementSchema>;

export const V3RoleRunArtifactReferenceSchema = Type.Object(
  {
    path: Type.String({ minLength: 1, maxLength: 2_000 }),
    displayName: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.String({ minLength: 1, maxLength: 255 }),
  },
  { additionalProperties: false },
);
export type V3RoleRunArtifactReference = Static<typeof V3RoleRunArtifactReferenceSchema>;

export const V3RoleRunEvidenceSubmissionSchema = Type.Object(
  {
    requirementKey: Type.String({ minLength: 1, maxLength: 160 }),
    acceptanceKeys: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
      minItems: 1,
      maxItems: 100,
      uniqueItems: true,
    }),
    kind: V3GroupEvidenceKindSchema,
    artifactPath: Type.String({ minLength: 1, maxLength: 2_000 }),
    summary: Type.String({ minLength: 1, maxLength: 4_000 }),
  },
  { additionalProperties: false },
);
export type V3RoleRunEvidenceSubmission = Static<typeof V3RoleRunEvidenceSubmissionSchema>;

export const V3RoleRunReportSchema = Type.Object(
  {
    schemaVersion: Type.Literal(V3_PRODUCT_CONTRACT_VERSION),
    reportType: Type.Literal('role_run_completion'),
    roleRunId: UuidSchema,
    taskId: UuidSchema,
    planVersion: Type.Integer({ minimum: 1 }),
    status: Type.Union([Type.Literal('completed'), Type.Literal('blocked')]),
    summary: Type.String({ minLength: 1, maxLength: 10_000 }),
    inputSummary: Type.String({ minLength: 1, maxLength: 10_000 }),
    roleResult: Type.String({ minLength: 1, maxLength: 20_000 }),
    workPerformed: Type.Array(Type.String({ minLength: 1, maxLength: 4_000 }), {
      maxItems: 200,
    }),
    changeSet: Type.Array(Type.String({ minLength: 1, maxLength: 2_000 }), {
      maxItems: 1_000,
      uniqueItems: true,
    }),
    artifacts: Type.Array(V3RoleRunArtifactReferenceSchema, { maxItems: 1_000 }),
    evidence: Type.Array(V3RoleRunEvidenceSubmissionSchema, { maxItems: 1_000 }),
    unresolvedIssues: Type.Array(Type.String({ minLength: 1, maxLength: 4_000 }), {
      maxItems: 200,
    }),
    nextStepInput: Type.String({ maxLength: 20_000 }),
    completion: Type.Object(
      {
        acceptanceKeys: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
          maxItems: 500,
          uniqueItems: true,
        }),
        evidenceRequirementKeys: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
          maxItems: 500,
          uniqueItems: true,
        }),
        readyForReview: Type.Boolean(),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
export type V3RoleRunReport = Static<typeof V3RoleRunReportSchema>;

const V3GroupPlanProposalTaskSchema = Type.Object(
  {
    taskKey: Type.String({ minLength: 1, maxLength: 160 }),
    title: Type.String({ minLength: 1, maxLength: 200 }),
    description: Type.String({ minLength: 1, maxLength: 10_000 }),
    ownerWakerId: UuidSchema,
    reviewerWakerIds: Type.Array(UuidSchema, { maxItems: 8, uniqueItems: true }),
    dependsOnTaskKeys: Type.Array(Type.String({ minLength: 1, maxLength: 160 }), {
      maxItems: 100,
      uniqueItems: true,
    }),
    acceptanceCriteria: Type.Array(V3GroupAcceptanceCriterionSchema, {
      minItems: 1,
      maxItems: 100,
    }),
    evidenceRequirements: Type.Array(V3GroupEvidenceRequirementSchema, {
      minItems: 1,
      maxItems: 100,
    }),
    recommendedSkillIds: Type.Array(Type.String({ minLength: 1, maxLength: 200 }), {
      maxItems: 100,
      uniqueItems: true,
    }),
  },
  { additionalProperties: false },
);

export const V3GroupPlanProposalSchema = Type.Object(
  {
    schemaVersion: Type.Literal(V3_PRODUCT_CONTRACT_VERSION),
    reportType: Type.Literal('group_plan_proposal'),
    missionId: UuidSchema,
    goal: Type.String({ minLength: 1, maxLength: 10_000 }),
    scope: Type.Array(Type.String({ minLength: 1, maxLength: 4_000 }), { maxItems: 200 }),
    outOfScope: Type.Array(Type.String({ minLength: 1, maxLength: 4_000 }), { maxItems: 200 }),
    constraints: Type.Array(Type.String({ minLength: 1, maxLength: 4_000 }), { maxItems: 200 }),
    tasks: Type.Array(V3GroupPlanProposalTaskSchema, { minItems: 1, maxItems: 50 }),
    risks: Type.Array(Type.String({ minLength: 1, maxLength: 4_000 }), { maxItems: 200 }),
    completionPolicy: Type.String({ minLength: 1, maxLength: 10_000 }),
  },
  { additionalProperties: false },
);
export type V3GroupPlanProposal = Static<typeof V3GroupPlanProposalSchema>;

const TaskTypeSchema = Type.Union([
  Type.Literal('individual'),
  Type.Literal('group_leader'),
  Type.Literal('group_child'),
  Type.Literal('automation'),
  Type.Literal('workflow_step'),
  Type.Literal('integration'),
]);
const TaskStateSchema = Type.Union([
  Type.Literal('draft'),
  Type.Literal('awaiting_confirmation'),
  Type.Literal('queued'),
  Type.Literal('preparing'),
  Type.Literal('running'),
  Type.Literal('awaiting_approval'),
  Type.Literal('awaiting_input'),
  Type.Literal('completed'),
  Type.Literal('failed'),
  Type.Literal('cancelled'),
]);

export const V3TaskSchema = Type.Object(
  {
    id: UuidSchema,
    parentTaskId: NullableUuidSchema,
    sourceType: Type.String({ minLength: 1, maxLength: 80 }),
    sourceId: UuidSchema,
    type: TaskTypeSchema,
    title: Type.String({ minLength: 1, maxLength: 255 }),
    conversationTitle: Type.Optional(Type.String({ minLength: 1, maxLength: 255 })),
    description: Type.Optional(V3SendMessageSchema.properties.content),
    assigneeWakerId: Type.Optional(NullableUuidSchema),
    effectiveWakerConfigurationVersionId: Type.Optional(NullableUuidSchema),
    state: TaskStateSchema,
    actionNeeded: Type.Union([Type.String({ minLength: 1, maxLength: 120 }), Type.Null()]),
    position: Type.Optional(Type.Integer({ minimum: 0 })),
    currentRunId: Type.Optional(NullableUuidSchema),
    sourceUrl: Type.String({ minLength: 1, maxLength: 2_000 }),
    createdAt: Type.Optional(DateTimeSchema),
    updatedAt: DateTimeSchema,
    pinnedAt: Type.Optional(DateTimeSchema),
    resultReadAt: Type.Optional(DateTimeSchema),
    triggerType: Type.Optional(
      Type.Union([
        Type.Literal('manual'),
        Type.Literal('schedule'),
        Type.Literal('event'),
        Type.Literal('api'),
        Type.Literal('at_waker'),
        Type.Literal('conversation'),
      ]),
    ),
  },
  { additionalProperties: false },
);
export type V3Task = Static<typeof V3TaskSchema>;

export const V3ReadTaskResultSchema = Type.Object(
  { resultVersion: Type.String({ minLength: 1, maxLength: 100 }) },
  { additionalProperties: false },
);
export type V3ReadTaskResult = Static<typeof V3ReadTaskResultSchema>;

export const V3RenameTaskSchema = Type.Object(
  {
    title: Type.String({ minLength: 1, maxLength: 255 }),
    expectedUpdatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3RenameTask = Static<typeof V3RenameTaskSchema>;

export const V3HideTaskSchema = Type.Object(
  { expectedUpdatedAt: DateTimeSchema },
  { additionalProperties: false },
);
export type V3HideTask = Static<typeof V3HideTaskSchema>;

export const V3PinTaskSchema = Type.Object(
  {
    pinned: Type.Boolean(),
    expectedUpdatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3PinTask = Static<typeof V3PinTaskSchema>;

export const V3TaskStateCountsSchema = Type.Object(
  {
    draft: Type.Integer({ minimum: 0 }),
    awaiting_confirmation: Type.Integer({ minimum: 0 }),
    queued: Type.Integer({ minimum: 0 }),
    preparing: Type.Integer({ minimum: 0 }),
    running: Type.Integer({ minimum: 0 }),
    awaiting_approval: Type.Integer({ minimum: 0 }),
    awaiting_input: Type.Integer({ minimum: 0 }),
    completed: Type.Integer({ minimum: 0 }),
    failed: Type.Integer({ minimum: 0 }),
    cancelled: Type.Integer({ minimum: 0 }),
  },
  { additionalProperties: false },
);
export type V3TaskStateCounts = Static<typeof V3TaskStateCountsSchema>;

export const V3TaskPageSchema = Type.Object(
  {
    items: Type.Array(V3TaskSchema),
    nextCursor: Type.Union([Type.String({ maxLength: 1_000 }), Type.Null()]),
    hasMore: Type.Boolean(),
    total: Type.Integer({ minimum: 0 }),
    counts: V3TaskStateCountsSchema,
  },
  { additionalProperties: false },
);
export type V3TaskPage = Static<typeof V3TaskPageSchema>;

export const V3ModelUsageSchema = Type.Object(
  {
    inputTokens: Type.Integer({ minimum: 0 }),
    outputTokens: Type.Integer({ minimum: 0 }),
    cacheReadTokens: Type.Optional(Type.Integer({ minimum: 0 })),
    cacheWriteTokens: Type.Optional(Type.Integer({ minimum: 0 })),
    totalTokens: Type.Integer({ minimum: 0 }),
    totalCost: Type.Optional(Type.Number({ minimum: 0 })),
  },
  { additionalProperties: false },
);
export type V3ModelUsage = Static<typeof V3ModelUsageSchema>;

const RunStatusSchema = Type.Union([
  Type.Literal('queued'),
  Type.Literal('preparing'),
  Type.Literal('running'),
  Type.Literal('awaiting_approval'),
  Type.Literal('awaiting_input'),
  Type.Literal('completed'),
  Type.Literal('failed'),
  Type.Literal('cancelled'),
]);

export const V3RunSchema = Type.Object(
  {
    id: UuidSchema,
    taskId: UuidSchema,
    attempt: Type.Integer({ minimum: 1 }),
    executionTarget: Type.Union([Type.Literal('local'), Type.Literal('cloud')]),
    workspaceReferenceId: Type.Optional(NullableUuidSchema),
    effectiveConfigurationVersionId: Type.Optional(NullableUuidSchema),
    provider: Type.String({
      minLength: 1,
      maxLength: 120,
      pattern: '^[a-z][a-z0-9-]{0,119}$',
    }),
    model: Type.String({ minLength: 1, maxLength: 200 }),
    providerCorrelationId: Type.Union([Type.String({ maxLength: 200 }), Type.Null()]),
    status: RunStatusSchema,
    usage: Type.Union([V3ModelUsageSchema, Type.Null()]),
    failureCategory: Type.Union([Type.String({ minLength: 1, maxLength: 120 }), Type.Null()]),
    failureDetail: Type.Optional(Type.Union([Type.String({ maxLength: 4_000 }), Type.Null()])),
    startedAt: Type.Optional(NullableDateTimeSchema),
    finishedAt: Type.Optional(NullableDateTimeSchema),
    createdAt: Type.Optional(DateTimeSchema),
    updatedAt: Type.Optional(DateTimeSchema),
  },
  { additionalProperties: false },
);
export type V3Run = Static<typeof V3RunSchema>;

export const V3ConversationRunPageSchema = Type.Object({
  runs: Type.Array(
    Type.Object({
      run: V3RunSchema,
      wakerId: Type.String(),
      sessionId: Type.Union([Type.String(), Type.Null()]),
    }),
  ),
  hasMore: Type.Boolean(),
  nextCursor: Type.String(),
});
export type V3ConversationRunPage = Static<typeof V3ConversationRunPageSchema>;

export const V3EventSchema = Type.Object(
  {
    id: UuidSchema,
    sequence: Type.Integer({ minimum: 1 }),
    type: Type.String({ minLength: 1, maxLength: 160 }),
    occurredAt: DateTimeSchema,
    payload: JsonObjectSchema,
  },
  { additionalProperties: false },
);
export type V3Event = Static<typeof V3EventSchema>;

export const V3DurableEventSchema = Type.Object(
  {
    id: UuidSchema,
    workspaceId: UuidSchema,
    runId: UuidSchema,
    sequence: Type.Integer({ minimum: 1 }),
    type: Type.String({ minLength: 1, maxLength: 160 }),
    occurredAt: DateTimeSchema,
    correlationId: Type.String({ minLength: 1, maxLength: 200 }),
    payload: JsonObjectSchema,
  },
  { additionalProperties: false },
);
export type V3DurableEvent = Static<typeof V3DurableEventSchema>;

export const V3GroupActivitySnapshotSchema = Type.Object(
  {
    events: Type.Array(V3DurableEventSchema),
    runCursors: Type.Array(
      Type.Object(
        {
          runId: UuidSchema,
          afterSequence: Type.Integer({ minimum: 0 }),
        },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);
export type V3GroupActivitySnapshot = Static<typeof V3GroupActivitySnapshotSchema>;

const V3_TERMINAL_RUN_EVENT_TYPES = new Set(['run.completed', 'run.failed', 'run.cancelled']);

export function isV3RunEventSubscriptionTerminal(event: Pick<V3DurableEvent, 'type' | 'payload'>): boolean {
  if (event.type === 'run.queue.settled') return true;
  if (
    event.type === 'run.cancelled' &&
    (event.payload.reason === 'user_stop' || event.payload.reason === 'send_now_preempt')
  ) {
    return false;
  }
  return V3_TERMINAL_RUN_EVENT_TYPES.has(event.type);
}

export const V3EventPageSchema = Type.Object(
  {
    events: Type.Array(V3EventSchema),
    afterSequence: Type.Integer({ minimum: 0 }),
    nextAfterSequence: Type.Integer({ minimum: 0 }),
    hasMore: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3EventPage = Static<typeof V3EventPageSchema>;

export const V3ApprovalSchema = Type.Object(
  {
    id: UuidSchema,
    runId: UuidSchema,
    capability: Type.String({ minLength: 1, maxLength: 200 }),
    requestHash: Sha256Schema,
    scope: Type.String({ minLength: 1, maxLength: 1_000 }),
    risk: Type.Union([Type.Literal('read'), Type.Literal('write'), Type.Literal('execute')]),
    status: Type.Union([
      Type.Literal('pending'),
      Type.Literal('approved'),
      Type.Literal('rejected'),
      Type.Literal('expired'),
      Type.Literal('cancelled'),
    ]),
    policyVersion: Type.Integer({ minimum: 1 }),
    requestedAt: DateTimeSchema,
    expiresAt: DateTimeSchema,
    resolvedAt: Type.Optional(NullableDateTimeSchema),
    resolvedBy: Type.Optional(NullableUuidSchema),
    /** `task` is the official `proceed_always` outcome (本任务内始终允许). */
    rememberedFor: Type.Optional(Type.Union([Type.Literal('task'), Type.Null()])),
  },
  { additionalProperties: false },
);
export type V3Approval = Static<typeof V3ApprovalSchema>;

export const V3ApprovalWorkItemSchema = Type.Object(
  {
    approval: V3ApprovalSchema,
    task: V3TaskSchema,
  },
  { additionalProperties: false },
);
export type V3ApprovalWorkItem = Static<typeof V3ApprovalWorkItemSchema>;

export const V3ResolveApprovalSchema = Type.Object(
  {
    decision: Type.Union([Type.Literal('approved'), Type.Literal('rejected')]),
    requestHash: Sha256Schema,
    remember: Type.Optional(Type.Literal('task')),
  },
  { additionalProperties: false },
);
export type V3ResolveApproval = Static<typeof V3ResolveApprovalSchema>;

export const V3ArtifactTypeSchema = Type.Union([
  Type.Literal('presentation'),
  Type.Literal('document'),
  Type.Literal('media'),
  Type.Literal('archive'),
  Type.Literal('other'),
]);
export type V3ArtifactType = Static<typeof V3ArtifactTypeSchema>;

/**
 * `kind` is the file role in the conversation: `artifact` for files the agent
 * presented to the user (最终文件), `process_file` for files a tool wrote while
 * working (工作区文件).
 */
export const V3ArtifactKindSchema = Type.Union([Type.Literal('artifact'), Type.Literal('process_file')]);
export type V3ArtifactKind = Static<typeof V3ArtifactKindSchema>;

export const V3ArtifactSchema = Type.Object(
  {
    id: UuidSchema,
    runId: UuidSchema,
    fileObjectId: UuidSchema,
    kind: V3ArtifactKindSchema,
    artifactType: V3ArtifactTypeSchema,
    source: Type.Union([
      Type.Literal('present_files'),
      Type.Literal('tool_hook'),
      Type.Literal('finalization'),
    ]),
    toolName: Type.Union([Type.String({ minLength: 1, maxLength: 200 }), Type.Null()]),
    title: Type.String({ minLength: 1, maxLength: 255 }),
    description: Type.Union([Type.String({ minLength: 1, maxLength: 2_000 }), Type.Null()]),
    relativePath: Type.String({ minLength: 1, maxLength: 1_024 }),
    displayName: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.String({ minLength: 1, maxLength: 255 }),
    sizeBytes: Type.Integer({ minimum: 0 }),
    sha256: Sha256Schema,
    state: Type.Union([
      Type.Literal('pending'),
      Type.Literal('available'),
      Type.Literal('quarantined'),
      Type.Literal('failed'),
      Type.Literal('deleted'),
    ]),
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Artifact = Static<typeof V3ArtifactSchema>;

export const V3RemoteArtifactMetadataSchema = Type.Pick(V3ArtifactSchema, [
  'kind',
  'artifactType',
  'source',
  'toolName',
  'title',
  'description',
  'relativePath',
  'mediaType',
]);
export type V3RemoteArtifactMetadata = Static<typeof V3RemoteArtifactMetadataSchema>;

/** Conversation-level projection behind the 产物 panel and inline artifact cards. */
export const V3ConversationArtifactManifestSchema = Type.Object(
  {
    conversationId: UuidSchema,
    /** Local working directory; null when the Run executed on the Cloud. */
    workingDirectory: Type.Union([Type.String({ minLength: 1, maxLength: 4_096 }), Type.Null()]),
    /** Host URL that opens `workingDirectory` in the system file manager. */
    workingDirectoryUrl: Type.Union([Type.String({ minLength: 1, maxLength: 4_096 }), Type.Null()]),
    artifacts: Type.Array(V3ArtifactSchema),
    fileChanges: Type.Array(V3ArtifactSchema),
    /** Content URL per artifact id, used for thumbnails, previews and downloads. */
    fileUrls: Type.Record(Type.String(), Type.String({ minLength: 1, maxLength: 8_192 })),
  },
  { additionalProperties: false },
);
export type V3ConversationArtifactManifest = Static<typeof V3ConversationArtifactManifestSchema>;

export const V3WorkspaceReferenceSchema = Type.Object(
  {
    id: UuidSchema,
    deviceId: Type.Optional(NullableUuidSchema),
    kind: Type.Union([Type.Literal('local_directory'), Type.Literal('cloud_project')]),
    displayName: Type.String({ minLength: 1, maxLength: 255 }),
    availability: Type.Union([
      Type.Literal('available'),
      Type.Literal('unavailable'),
      Type.Literal('revoked'),
      Type.Literal('unknown'),
    ]),
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3WorkspaceReference = Static<typeof V3WorkspaceReferenceSchema>;

export const V3ProjectVisibilitySchema = Type.Union([Type.Literal('workspace'), Type.Literal('private')]);
export type V3ProjectVisibility = Static<typeof V3ProjectVisibilitySchema>;

export const V3_PROJECT_HTTPS_GIT_URL = /^https:\/\/[^\s/?#]+\/[^\s/?#]+\/[^\s?#]+$/u;

export const V3ProjectSourceInputSchema = Type.Union([
  Type.Object(
    {
      kind: Type.Literal('local_directory'),
      workspaceReferenceId: UuidSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      kind: Type.Literal('git_repository'),
      locator: Type.String({ minLength: 12, maxLength: 1_000, pattern: V3_PROJECT_HTTPS_GIT_URL.source }),
      branch: Type.Optional(Type.String({ minLength: 1, maxLength: 255 })),
    },
    { additionalProperties: false },
  ),
]);
export type V3ProjectSourceInput = Static<typeof V3ProjectSourceInputSchema>;

export const V3ProjectSourceSchema = Type.Object(
  {
    id: UuidSchema,
    kind: Type.Union([Type.Literal('local_directory'), Type.Literal('git_repository')]),
    workspaceReferenceId: NullableUuidSchema,
    locator: Type.Union([Type.String({ minLength: 1, maxLength: 1_000 }), Type.Null()]),
    branch: Type.Union([Type.String({ minLength: 1, maxLength: 255 }), Type.Null()]),
    displayName: Type.String({ minLength: 1, maxLength: 255 }),
    availability: Type.Union([
      Type.Literal('available'),
      Type.Literal('unavailable'),
      Type.Literal('revoked'),
      Type.Literal('unknown'),
    ]),
    position: Type.Integer({ minimum: 0 }),
  },
  { additionalProperties: false },
);
export type V3ProjectSource = Static<typeof V3ProjectSourceSchema>;

export const V3CreateProjectSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 120 }),
    summary: Type.String({ maxLength: 500 }),
    visibility: V3ProjectVisibilitySchema,
    ownerWakerId: Type.Optional(NullableUuidSchema),
    sources: Type.Array(V3ProjectSourceInputSchema, { minItems: 1, maxItems: 20 }),
  },
  { additionalProperties: false },
);
export type V3CreateProject = Static<typeof V3CreateProjectSchema>;

export const V3UpdateProjectSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 120 }),
    summary: Type.String({ maxLength: 500 }),
    sources: Type.Array(V3ProjectSourceInputSchema, { minItems: 1, maxItems: 20 }),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3UpdateProject = Static<typeof V3UpdateProjectSchema>;

export const V3ProjectLifecycleInputSchema = Type.Object(
  {
    action: Type.Literal('archive'),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3ProjectLifecycleInput = Static<typeof V3ProjectLifecycleInputSchema>;

export const V3ProjectPreparationStateSchema = Type.Union([
  Type.Literal('initializing'),
  Type.Literal('ready'),
  Type.Literal('error'),
]);
export type V3ProjectPreparationState = Static<typeof V3ProjectPreparationStateSchema>;

export const V3ProjectPreparationSchema = Type.Union([
  Type.Object(
    {
      state: Type.Literal('initializing'),
      attempt: Type.Integer({ minimum: 1 }),
      errorCode: Type.Null(),
      errorDetail: Type.Null(),
      updatedAt: DateTimeSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      state: Type.Literal('ready'),
      attempt: Type.Integer({ minimum: 1 }),
      errorCode: Type.Null(),
      errorDetail: Type.Null(),
      updatedAt: DateTimeSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      state: Type.Literal('error'),
      attempt: Type.Integer({ minimum: 1 }),
      errorCode: Type.String({ minLength: 1, maxLength: 100 }),
      errorDetail: Type.String({ minLength: 1, maxLength: 1_000 }),
      updatedAt: DateTimeSchema,
    },
    { additionalProperties: false },
  ),
]);
export type V3ProjectPreparation = Static<typeof V3ProjectPreparationSchema>;

export const V3RetryProjectPreparationSchema = Type.Object(
  { expectedVersion: Type.Integer({ minimum: 1 }) },
  { additionalProperties: false },
);
export type V3RetryProjectPreparation = Static<typeof V3RetryProjectPreparationSchema>;

export const V3ProjectSchema = Type.Object(
  {
    id: UuidSchema,
    ownerWakerId: NullableUuidSchema,
    name: Type.String({ minLength: 1, maxLength: 120 }),
    summary: Type.String({ maxLength: 500 }),
    visibility: V3ProjectVisibilitySchema,
    availability: Type.Union([
      Type.Literal('available'),
      Type.Literal('unavailable'),
      Type.Literal('revoked'),
      Type.Literal('unknown'),
    ]),
    preparation: V3ProjectPreparationSchema,
    sources: Type.Array(V3ProjectSourceSchema, { minItems: 1, maxItems: 20 }),
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Project = Static<typeof V3ProjectSchema>;

export const V3RegisterCloudWorkspaceSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 120 }),
    projectLocator: Type.String({ minLength: 1, maxLength: 1_000 }),
  },
  { additionalProperties: false },
);
export type V3RegisterCloudWorkspace = Static<typeof V3RegisterCloudWorkspaceSchema>;

export const V3AutomationStatusSchema = Type.Union([
  Type.Literal('draft'),
  Type.Literal('enabled'),
  Type.Literal('disabled'),
  Type.Literal('archived'),
]);
export type V3AutomationStatus = Static<typeof V3AutomationStatusSchema>;

const V3AutomationTriggerIdSchema = Type.String({
  minLength: 1,
  maxLength: 80,
  pattern: '^[A-Za-z0-9_-]+$',
});
const AutomationTimeSchema = Type.String({ pattern: '^(?:[01]\\d|2[0-3]):[0-5]\\d$' });
const V3AutomationScheduleTriggerSchema = Type.Union([
  Type.Object(
    {
      id: V3AutomationTriggerIdSchema,
      type: Type.Literal('schedule'),
      mode: Type.Literal('recurring'),
      cadence: Type.Union([
        Type.Literal('hourly'),
        Type.Literal('daily'),
        Type.Literal('weekdays'),
        Type.Literal('weekly'),
        Type.Literal('monthly'),
        Type.Literal('custom'),
      ]),
      time: AutomationTimeSchema,
      daysOfWeek: Type.Optional(
        Type.Array(Type.Integer({ minimum: 0, maximum: 6 }), {
          minItems: 1,
          maxItems: 7,
          uniqueItems: true,
        }),
      ),
      dayOfMonth: Type.Optional(Type.Integer({ minimum: 1, maximum: 31 })),
      cronExpression: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      id: V3AutomationTriggerIdSchema,
      type: Type.Literal('schedule'),
      mode: Type.Literal('once'),
      runAt: DateTimeSchema,
    },
    { additionalProperties: false },
  ),
]);
const V3AutomationEventTriggerSchema = Type.Object(
  {
    id: V3AutomationTriggerIdSchema,
    type: Type.Literal('event'),
    provider: Type.Literal('github'),
    repository: Type.String({ minLength: 1, maxLength: 500 }),
    resources: Type.Array(Type.Union([Type.Literal('issue'), Type.Literal('pull_request')]), {
      minItems: 1,
      maxItems: 2,
      uniqueItems: true,
    }),
    changes: Type.Array(Type.Union([Type.Literal('opened'), Type.Literal('edited')]), {
      minItems: 1,
      maxItems: 2,
      uniqueItems: true,
    }),
    resourceChanges: Type.Optional(
      Type.Object(
        {
          issue: Type.Array(Type.Union([Type.Literal('opened'), Type.Literal('edited')]), {
            maxItems: 2,
            uniqueItems: true,
          }),
          pull_request: Type.Array(Type.Union([Type.Literal('opened'), Type.Literal('edited')]), {
            maxItems: 2,
            uniqueItems: true,
          }),
        },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);
const V3AutomationApiTriggerSchema = Type.Object(
  {
    id: V3AutomationTriggerIdSchema,
    type: Type.Literal('api'),
    invokeKey: Type.Optional(Type.String({ minLength: 32, maxLength: 128 })),
  },
  { additionalProperties: false },
);

export const V3AutomationTriggerSchema = Type.Union([
  V3AutomationScheduleTriggerSchema,
  V3AutomationEventTriggerSchema,
  V3AutomationApiTriggerSchema,
]);
export type V3AutomationTrigger = Static<typeof V3AutomationTriggerSchema>;

export const V3AutomationRetryPolicySchema = Type.Object(
  {
    maxAttempts: Type.Integer({ minimum: 1, maximum: 5 }),
    delaySeconds: Type.Integer({ minimum: 1, maximum: 86_400 }),
  },
  { additionalProperties: false },
);
export type V3AutomationRetryPolicy = Static<typeof V3AutomationRetryPolicySchema>;

const AutomationDefinitionFields = {
  name: Type.String({ minLength: 1, maxLength: 160 }),
  instruction: Type.String({ minLength: 1, maxLength: 10_000 }),
  workspaceReferenceId: Type.Optional(NullableUuidSchema),
  model: Type.String({ minLength: 1, maxLength: 200 }),
  triggers: Type.Array(V3AutomationTriggerSchema, { minItems: 1, maxItems: 5 }),
  timezone: Type.String({ minLength: 1, maxLength: 120 }),
  missedRunPolicy: Type.Union([Type.Literal('skip'), Type.Literal('run_once')]),
  overlapPolicy: Type.Union([Type.Literal('skip'), Type.Literal('queue'), Type.Literal('cancel_previous')]),
  retryPolicy: V3AutomationRetryPolicySchema,
  maxRunCount: Type.Union([Type.Integer({ minimum: 1, maximum: 1_000_000 }), Type.Null()]),
  deadlineAt: NullableDateTimeSchema,
} as const;

const V3AutomationDefinitionSchema = Type.Object(AutomationDefinitionFields, {
  additionalProperties: false,
});

export const V3CreateAutomationSchema = Type.Object(AutomationDefinitionFields, {
  additionalProperties: false,
});
export type V3CreateAutomation = Static<typeof V3CreateAutomationSchema>;

export const V3UpdateAutomationSchema = Type.Object(
  {
    expectedVersion: Type.Integer({ minimum: 1 }),
    ...AutomationDefinitionFields,
  },
  { additionalProperties: false },
);
export type V3UpdateAutomation = Static<typeof V3UpdateAutomationSchema>;

export const V3AutomationVersionSchema = Type.Object(
  {
    id: UuidSchema,
    automationId: UuidSchema,
    number: Type.Integer({ minimum: 1 }),
    instruction: Type.String({ minLength: 1, maxLength: 10_000 }),
    workspaceReferenceId: Type.Optional(NullableUuidSchema),
    model: Type.String({ minLength: 1, maxLength: 200 }),
    triggers: Type.Array(V3AutomationTriggerSchema, { minItems: 1, maxItems: 5 }),
    timezone: Type.String({ minLength: 1, maxLength: 120 }),
    missedRunPolicy: Type.Union([Type.Literal('skip'), Type.Literal('run_once')]),
    overlapPolicy: Type.Union([Type.Literal('skip'), Type.Literal('queue'), Type.Literal('cancel_previous')]),
    retryPolicy: V3AutomationRetryPolicySchema,
    maxRunCount: Type.Union([Type.Integer({ minimum: 1, maximum: 1_000_000 }), Type.Null()]),
    deadlineAt: NullableDateTimeSchema,
    createdBy: NullableUuidSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3AutomationVersion = Static<typeof V3AutomationVersionSchema>;

export const V3AutomationSchema = Type.Object(
  {
    id: UuidSchema,
    wakerId: UuidSchema,
    name: Type.String({ minLength: 1, maxLength: 160 }),
    status: V3AutomationStatusSchema,
    version: Type.Integer({ minimum: 1 }),
    runCount: Type.Integer({ minimum: 0 }),
    currentVersion: V3AutomationVersionSchema,
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Automation = Static<typeof V3AutomationSchema>;

export const V3AutomationLifecycleInputSchema = Type.Object(
  {
    action: Type.Union([Type.Literal('enable'), Type.Literal('disable'), Type.Literal('delete')]),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3AutomationLifecycleInput = Static<typeof V3AutomationLifecycleInputSchema>;

export const V3AutomationInvocationSchema = Type.Object(
  {
    id: UuidSchema,
    deliveryId: UuidSchema,
    automationId: UuidSchema,
    automationVersion: Type.Integer({ minimum: 1 }),
    summary: Type.String({ minLength: 1, maxLength: 10_000 }),
    triggerType: Type.Union([
      Type.Literal('schedule'),
      Type.Literal('event'),
      Type.Literal('api'),
      Type.Literal('manual'),
    ]),
    deliveryIdentity: Type.String({ minLength: 1, maxLength: 500 }),
    conversationId: NullableUuidSchema,
    taskId: NullableUuidSchema,
    runId: NullableUuidSchema,
    attempt: Type.Integer({ minimum: 1, maximum: 5 }),
    state: Type.Union([
      Type.Literal('accepted'),
      Type.Literal('queued'),
      Type.Literal('running'),
      Type.Literal('completed'),
      Type.Literal('failed'),
      Type.Literal('cancelled'),
      Type.Literal('skipped'),
    ]),
    failure: Type.Union([Type.String({ maxLength: 10_000 }), Type.Null()]),
    scheduledAt: NullableDateTimeSchema,
    startedAt: NullableDateTimeSchema,
    finishedAt: NullableDateTimeSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3AutomationInvocation = Static<typeof V3AutomationInvocationSchema>;

export type V3AutomationInvocationListInput = V3PaginationInput & { automaticOnly?: boolean };

export const V3AutomationDispatchInputSchema = Type.Object(
  {
    triggerType: Type.Union([
      Type.Literal('schedule'),
      Type.Literal('event'),
      Type.Literal('api'),
      Type.Literal('manual'),
    ]),
    triggerId: Type.Optional(V3AutomationTriggerIdSchema),
    eventType: Type.Optional(Type.Union([Type.Literal('issues'), Type.Literal('pull_request')])),
    deliveryIdentity: Type.String({ minLength: 1, maxLength: 500 }),
    payload: Type.Optional(JsonObjectSchema),
    scheduledAt: Type.Optional(NullableDateTimeSchema),
  },
  { additionalProperties: false },
);
export type V3AutomationDispatchInput = Static<typeof V3AutomationDispatchInputSchema>;

export const V3AutomationDispatchResultSchema = Type.Object(
  {
    created: Type.Boolean(),
    invocation: V3AutomationInvocationSchema,
    conversation: Type.Union([V3ConversationSchema, Type.Null()]),
    task: Type.Union([V3TaskSchema, Type.Null()]),
    run: Type.Union([V3RunSchema, Type.Null()]),
  },
  { additionalProperties: false },
);
export type V3AutomationDispatchResult = Static<typeof V3AutomationDispatchResultSchema>;

export const V3WorkflowInputFieldSchema = Type.Object(
  {
    key: Type.String({ minLength: 1, maxLength: 120, pattern: '^[A-Za-z][A-Za-z0-9_]*$' }),
    label: Type.String({ minLength: 1, maxLength: 200 }),
    description: Type.String({ maxLength: 2_000 }),
    type: Type.Union([
      Type.Literal('string'),
      Type.Literal('number'),
      Type.Literal('boolean'),
      Type.Literal('object'),
      Type.Literal('array'),
    ]),
    required: Type.Boolean(),
    defaultValue: Type.Optional(Type.Unknown()),
  },
  { additionalProperties: false },
);
export type V3WorkflowInputField = Static<typeof V3WorkflowInputFieldSchema>;

const WorkflowNodeBaseFields = {
  id: Type.String({ minLength: 1, maxLength: 120, pattern: '^[A-Za-z][A-Za-z0-9_-]*$' }),
  name: Type.String({ minLength: 1, maxLength: 200 }),
  next: Type.Array(Type.String({ minLength: 1, maxLength: 120 }), {
    maxItems: 20,
    uniqueItems: true,
  }),
} as const;

export const V3WorkflowNodeSchema = Type.Union([
  Type.Object({ ...WorkflowNodeBaseFields, type: Type.Literal('phase') }, { additionalProperties: false }),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('worker'),
      wakerId: UuidSchema,
      instruction: Type.String({ minLength: 1, maxLength: 20_000 }),
    },
    { additionalProperties: false },
  ),
  Type.Object({ ...WorkflowNodeBaseFields, type: Type.Literal('parallel') }, { additionalProperties: false }),
  Type.Object({ ...WorkflowNodeBaseFields, type: Type.Literal('join') }, { additionalProperties: false }),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('pipeline'),
      wakerId: UuidSchema,
      itemsExpression: Type.String({ minLength: 1, maxLength: 2_000 }),
      instruction: Type.String({ minLength: 1, maxLength: 20_000 }),
      concurrency: Type.Integer({ minimum: 1, maximum: 20 }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('ask_user'),
      question: Type.String({ minLength: 1, maxLength: 5_000 }),
      responseKey: Type.String({ minLength: 1, maxLength: 120, pattern: '^[A-Za-z][A-Za-z0-9_]*$' }),
      choices: Type.Array(Type.String({ minLength: 1, maxLength: 500 }), {
        maxItems: 20,
        uniqueItems: true,
      }),
      timeoutSeconds: Type.Union([Type.Integer({ minimum: 1, maximum: 604_800 }), Type.Null()]),
      defaultResponse: Type.Optional(Type.Unknown()),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('action'),
      actionId: Type.String({ minLength: 1, maxLength: 240 }),
      actionType: Type.Literal('script'),
      command: Type.String({ minLength: 1, maxLength: 16_000 }),
      args: Type.Unknown(),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('action'),
      actionId: Type.String({ minLength: 1, maxLength: 240 }),
      actionType: Type.Literal('builtin'),
      handlerSource: Type.String({ minLength: 1, maxLength: 16_000 }),
      args: Type.Unknown(),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('action'),
      actionId: Type.String({ minLength: 1, maxLength: 240 }),
      actionType: Type.Literal('http'),
      url: Type.String({ minLength: 1, maxLength: 8_000 }),
      method: Type.Optional(
        Type.Union([
          Type.Literal('GET'),
          Type.Literal('POST'),
          Type.Literal('PUT'),
          Type.Literal('PATCH'),
          Type.Literal('DELETE'),
        ]),
      ),
      args: Type.Unknown(),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('subflow'),
      workflowId: UuidSchema,
      input: JsonObjectSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('log'),
      level: Type.Union([Type.Literal('info'), Type.Literal('warn'), Type.Literal('error')]),
      message: Type.String({ minLength: 1, maxLength: 5_000 }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...WorkflowNodeBaseFields,
      type: Type.Literal('return'),
      value: Type.Unknown(),
    },
    { additionalProperties: false },
  ),
]);
export type V3WorkflowNode = Static<typeof V3WorkflowNodeSchema>;

const WorkflowDefinitionFields = {
  name: Type.String({ minLength: 1, maxLength: 160 }),
  description: Type.String({ maxLength: 5_000 }),
  script: Type.String({ maxLength: 100_000 }),
  startNodeId: Type.String({ maxLength: 120 }),
  inputSchema: Type.Array(V3WorkflowInputFieldSchema, { maxItems: 100 }),
  nodes: Type.Array(V3WorkflowNodeSchema, { maxItems: 500 }),
} as const;

export const V3CreateWorkflowSchema = Type.Object(
  {
    ...WorkflowDefinitionFields,
    ownerWakerId: Type.Optional(NullableUuidSchema),
    conversationId: Type.Optional(NullableUuidSchema),
  },
  { additionalProperties: false },
);
export type V3CreateWorkflow = Static<typeof V3CreateWorkflowSchema>;

export const V3UpdateWorkflowSchema = Type.Object(
  {
    expectedVersion: Type.Integer({ minimum: 1 }),
    ...WorkflowDefinitionFields,
  },
  { additionalProperties: false },
);
export type V3UpdateWorkflow = Static<typeof V3UpdateWorkflowSchema>;

export const V3WorkflowVersionSchema = Type.Object(
  {
    id: UuidSchema,
    workflowId: UuidSchema,
    number: Type.Integer({ minimum: 1 }),
    state: Type.Union([Type.Literal('draft'), Type.Literal('published')]),
    description: Type.String({ maxLength: 5_000 }),
    script: Type.String({ maxLength: 100_000 }),
    startNodeId: Type.String({ maxLength: 120 }),
    inputSchema: Type.Array(V3WorkflowInputFieldSchema, { maxItems: 100 }),
    nodes: Type.Array(V3WorkflowNodeSchema, { maxItems: 500 }),
    createdBy: NullableUuidSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3WorkflowVersion = Static<typeof V3WorkflowVersionSchema>;

export const V3WorkflowTriggerConfigurationSchema = Type.Object(
  {
    enabled: Type.Boolean(),
    name: Type.Optional(Type.String({ minLength: 1, maxLength: 160 })),
    triggers: Type.Array(V3AutomationTriggerSchema, { maxItems: 5 }),
    defaultArgs: JsonObjectSchema,
    timezone: Type.String({ minLength: 1, maxLength: 120 }),
    missedRunPolicy: Type.Union([Type.Literal('skip'), Type.Literal('run_once')]),
    maxRunCount: Type.Union([Type.Integer({ minimum: 1, maximum: 1_000_000 }), Type.Null()]),
    deadlineAt: NullableDateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3WorkflowTriggerConfiguration = Static<typeof V3WorkflowTriggerConfigurationSchema>;

export const V3UpdateWorkflowTriggersSchema = Type.Object(
  {
    expectedVersion: Type.Integer({ minimum: 1 }),
    ...V3WorkflowTriggerConfigurationSchema.properties,
    enabled: Type.Optional(Type.Boolean()),
  },
  { additionalProperties: false },
);
export type V3UpdateWorkflowTriggers = Static<typeof V3UpdateWorkflowTriggersSchema>;

export const V3CreateWorkflowAutomationSchema = Type.Object(
  {
    ...V3WorkflowTriggerConfigurationSchema.properties,
    name: Type.String({ minLength: 1, maxLength: 160 }),
    triggers: Type.Array(V3AutomationTriggerSchema, { minItems: 1, maxItems: 5 }),
  },
  { additionalProperties: false },
);
export type V3CreateWorkflowAutomation = Static<typeof V3CreateWorkflowAutomationSchema>;

export const V3UpdateWorkflowAutomationSchema = Type.Object(
  {
    ...V3CreateWorkflowAutomationSchema.properties,
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3UpdateWorkflowAutomation = Static<typeof V3UpdateWorkflowAutomationSchema>;

export const V3DeleteWorkflowAutomationSchema = Type.Object(
  { expectedVersion: Type.Integer({ minimum: 1 }) },
  { additionalProperties: false },
);
export type V3DeleteWorkflowAutomation = Static<typeof V3DeleteWorkflowAutomationSchema>;

export const V3WorkflowAutomationSchema = Type.Object(
  {
    id: UuidSchema,
    workflowId: UuidSchema,
    createdBy: Type.Union([UuidSchema, Type.Null()]),
    version: Type.Integer({ minimum: 1 }),
    configuration: V3CreateWorkflowAutomationSchema,
    automaticRunCount: Type.Integer({ minimum: 0 }),
    lastAutomaticRunAt: NullableDateTimeSchema,
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3WorkflowAutomation = Static<typeof V3WorkflowAutomationSchema>;

export const V3WorkflowTriggerDispatchInputSchema = Type.Object(
  {
    triggerType: Type.Union([Type.Literal('schedule'), Type.Literal('event'), Type.Literal('api')]),
    triggerId: V3AutomationTriggerIdSchema,
    deliveryIdentity: Type.String({ minLength: 1, maxLength: 500 }),
    payload: Type.Optional(JsonObjectSchema),
    scheduledAt: Type.Optional(NullableDateTimeSchema),
  },
  { additionalProperties: false },
);
export type V3WorkflowTriggerDispatchInput = Static<typeof V3WorkflowTriggerDispatchInputSchema>;

export const V3WorkflowAutomationDispatchInputSchema = Type.Union([
  V3WorkflowTriggerDispatchInputSchema,
  Type.Object(
    {
      triggerType: Type.Literal('manual'),
      deliveryIdentity: Type.String({ minLength: 1, maxLength: 500 }),
      payload: Type.Optional(JsonObjectSchema),
    },
    { additionalProperties: false },
  ),
]);
export type V3WorkflowAutomationDispatchInput = Static<typeof V3WorkflowAutomationDispatchInputSchema>;

export const V3WorkflowSchema = Type.Object(
  {
    id: UuidSchema,
    ownerWakerId: NullableUuidSchema,
    conversationId: NullableUuidSchema,
    name: Type.String({ minLength: 1, maxLength: 160 }),
    status: Type.Union([Type.Literal('draft'), Type.Literal('published'), Type.Literal('archived')]),
    version: Type.Integer({ minimum: 1 }),
    currentVersion: V3WorkflowVersionSchema,
    publishedVersion: Type.Union([V3WorkflowVersionSchema, Type.Null()]),
    triggerConfiguration: V3WorkflowTriggerConfigurationSchema,
    automaticRunCount: Type.Integer({ minimum: 0 }),
    lastAutomaticRunAt: NullableDateTimeSchema,
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Workflow = Static<typeof V3WorkflowSchema>;

export const V3WorkflowLifecycleInputSchema = Type.Object(
  {
    action: Type.Union([Type.Literal('publish'), Type.Literal('archive'), Type.Literal('delete')]),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3WorkflowLifecycleInput = Static<typeof V3WorkflowLifecycleInputSchema>;

export const V3WorkflowRollbackInputSchema = Type.Object(
  {
    expectedVersion: Type.Integer({ minimum: 1 }),
    versionNumber: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3WorkflowRollbackInput = Static<typeof V3WorkflowRollbackInputSchema>;

export const V3WorkflowRunInputSchema = Type.Object(
  {
    triggerType: Type.Union([
      Type.Literal('manual'),
      Type.Literal('schedule'),
      Type.Literal('event'),
      Type.Literal('api'),
    ]),
    deliveryIdentity: Type.String({ minLength: 1, maxLength: 500 }),
    args: JsonObjectSchema,
  },
  { additionalProperties: false },
);
export type V3WorkflowRunInput = Static<typeof V3WorkflowRunInputSchema>;

export const V3WorkflowRunSchema = Type.Object(
  {
    sourceRunId: Type.Optional(UuidSchema),
    cachedWorkerCount: Type.Optional(Type.Integer({ minimum: 0 })),
    failedItemCount: Type.Optional(Type.Integer({ minimum: 0 })),
    id: UuidSchema,
    workflowId: UuidSchema,
    workflowVersion: Type.Integer({ minimum: 1 }),
    triggerType: Type.Union([
      Type.Literal('manual'),
      Type.Literal('schedule'),
      Type.Literal('event'),
      Type.Literal('api'),
    ]),
    deliveryIdentity: Type.String({ minLength: 1, maxLength: 500 }),
    state: Type.Union([
      Type.Literal('queued'),
      Type.Literal('running'),
      Type.Literal('awaiting_input'),
      Type.Literal('completed'),
      Type.Literal('failed'),
      Type.Literal('cancelled'),
    ]),
    args: JsonObjectSchema,
    output: Type.Unknown(),
    pendingNodeId: Type.Union([Type.String({ minLength: 1, maxLength: 120 }), Type.Null()]),
    failure: Type.Union([Type.String({ maxLength: 4_000 }), Type.Null()]),
    startedAt: NullableDateTimeSchema,
    finishedAt: NullableDateTimeSchema,
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3WorkflowRun = Static<typeof V3WorkflowRunSchema>;

export const V3WorkflowRunEventSchema = Type.Object(
  {
    id: UuidSchema,
    workflowRunId: UuidSchema,
    sequence: Type.Integer({ minimum: 1 }),
    type: Type.Union([
      Type.Literal('run.queued'),
      Type.Literal('run.started'),
      Type.Literal('run.recovered'),
      Type.Literal('node.started'),
      Type.Literal('node.completed'),
      Type.Literal('worker.cache_hit'),
      Type.Literal('pipeline.item.completed'),
      Type.Literal('pipeline.item.started'),
      Type.Literal('pipeline.item.failed'),
      Type.Literal('node.failed'),
      Type.Literal('action.dispatched'),
      Type.Literal('action.completed'),
      Type.Literal('action.failed'),
      Type.Literal('input.requested'),
      Type.Literal('input.resolved'),
      Type.Literal('log'),
      Type.Literal('run.completed'),
      Type.Literal('run.failed'),
      Type.Literal('run.cancelled'),
    ]),
    nodeId: Type.Union([Type.String({ minLength: 1, maxLength: 120 }), Type.Null()]),
    payload: JsonObjectSchema,
    occurredAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3WorkflowRunEvent = Static<typeof V3WorkflowRunEventSchema>;

export const V3WorkflowNodeExecutionSchema = Type.Object(
  {
    workflowRunId: UuidSchema,
    nodeId: Type.String({ minLength: 1, maxLength: 240 }),
    taskId: UuidSchema,
    assigneeWakerId: NullableUuidSchema,
    agentRunId: NullableUuidSchema,
    conversationId: NullableUuidSchema,
  },
  { additionalProperties: false },
);
export type V3WorkflowNodeExecution = Static<typeof V3WorkflowNodeExecutionSchema>;

export const V3ResolveWorkflowInputSchema = Type.Object(
  {
    nodeId: Type.String({ minLength: 1, maxLength: 120 }),
    response: Type.Unknown(),
    skip: Type.Optional(Type.Boolean()),
  },
  { additionalProperties: false },
);
export type V3ResolveWorkflowInput = Static<typeof V3ResolveWorkflowInputSchema>;

export const V3CreateKnowledgeBaseSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 160 }),
    description: Type.String({ maxLength: 2_000 }),
  },
  { additionalProperties: false },
);
export type V3CreateKnowledgeBase = Static<typeof V3CreateKnowledgeBaseSchema>;

export const V3KnowledgeBaseSchema = Type.Object(
  {
    id: UuidSchema,
    ownerUserId: UuidSchema,
    name: Type.String({ minLength: 1, maxLength: 160 }),
    description: Type.String({ maxLength: 2_000 }),
    status: Type.Union([
      Type.Literal('ready'),
      Type.Literal('processing'),
      Type.Literal('failed'),
      Type.Literal('archived'),
    ]),
    currentCompilationVersion: Type.Integer({ minimum: 0 }),
    sourceCount: Type.Integer({ minimum: 0 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeBase = Static<typeof V3KnowledgeBaseSchema>;

export const V3RenameKnowledgeBaseSchema = Type.Object(
  { name: Type.String({ minLength: 1, maxLength: 160 }) },
  { additionalProperties: false },
);
export type V3RenameKnowledgeBase = Static<typeof V3RenameKnowledgeBaseSchema>;

export const V3KnowledgeFolderSchema = Type.Object(
  {
    id: UuidSchema,
    knowledgeBaseId: UuidSchema,
    parentFolderId: NullableUuidSchema,
    name: Type.String({ minLength: 1, maxLength: 500, pattern: '\\S' }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeFolder = Static<typeof V3KnowledgeFolderSchema>;

export const V3CreateKnowledgeFolderSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 500, pattern: '\\S' }),
    parentFolderId: NullableUuidSchema,
  },
  { additionalProperties: false },
);
export type V3CreateKnowledgeFolder = Static<typeof V3CreateKnowledgeFolderSchema>;

export const V3RenameKnowledgeFolderSchema = Type.Object(
  { name: Type.String({ minLength: 1, maxLength: 500, pattern: '\\S' }) },
  { additionalProperties: false },
);
export type V3RenameKnowledgeFolder = Static<typeof V3RenameKnowledgeFolderSchema>;
export const V3RenameKnowledgeMaterialSchema = V3RenameKnowledgeFolderSchema;
export type V3RenameKnowledgeMaterial = Static<typeof V3RenameKnowledgeMaterialSchema>;

const V3KnowledgeFolderIdSelectionSchema = Type.Array(UuidSchema, {
  minItems: 1,
  maxItems: 200,
  uniqueItems: true,
});
const V3KnowledgeMaterialIdSelectionSchema = Type.Array(UuidSchema, {
  minItems: 1,
  maxItems: 200,
  uniqueItems: true,
});
export const V3DeleteKnowledgeSelectionSchema = Type.Union([
  Type.Object(
    {
      folderIds: V3KnowledgeFolderIdSelectionSchema,
      materialIds: Type.Array(UuidSchema, { maxItems: 200, uniqueItems: true }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      folderIds: Type.Array(UuidSchema, { maxItems: 200, uniqueItems: true }),
      materialIds: V3KnowledgeMaterialIdSelectionSchema,
    },
    { additionalProperties: false },
  ),
]);
export type V3DeleteKnowledgeSelection = Static<typeof V3DeleteKnowledgeSelectionSchema>;

export const V3CreateKnowledgeUrlMaterialSchema = Type.Object(
  {
    title: Type.String({ minLength: 1, maxLength: 500 }),
    sourceUrl: Type.String({ format: 'uri', minLength: 8, maxLength: 2_000 }),
    parentFolderId: Type.Optional(NullableUuidSchema),
  },
  { additionalProperties: false },
);
export type V3CreateKnowledgeUrlMaterial = Static<typeof V3CreateKnowledgeUrlMaterialSchema>;

export const V3KnowledgeMaterialSchema = Type.Object(
  {
    id: UuidSchema,
    knowledgeBaseId: UuidSchema,
    parentFolderId: NullableUuidSchema,
    kind: Type.Union([Type.Literal('file'), Type.Literal('url')]),
    fileObjectId: NullableUuidSchema,
    sourceUrl: Type.Union([Type.String({ format: 'uri', maxLength: 2_000 }), Type.Null()]),
    title: Type.String({ minLength: 1, maxLength: 500 }),
    sourceSha256: Sha256Schema,
    processingState: Type.Union([
      Type.Literal('queued'),
      Type.Literal('processing'),
      Type.Literal('ready'),
      Type.Literal('failed'),
    ]),
    failureDetail: Type.Union([Type.String({ maxLength: 4_000 }), Type.Null()]),
    compiledVersion: Type.Union([Type.Integer({ minimum: 0 }), Type.Null()]),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeMaterial = Static<typeof V3KnowledgeMaterialSchema>;

export const V3KnowledgeEmailPreviewSchema = Type.Object(
  {
    subject: Type.String(),
    from: Type.String(),
    to: Type.String(),
    cc: Type.String(),
    sentAt: Type.Union([DateTimeSchema, Type.Null()]),
    attachmentCount: Type.Integer({ minimum: 0 }),
    html: Type.String(),
    text: Type.String(),
  },
  { additionalProperties: false },
);
export type V3KnowledgeEmailPreview = Static<typeof V3KnowledgeEmailPreviewSchema>;

export const V3KnowledgeMaterialContentSchema = Type.Object(
  {
    materialId: UuidSchema,
    fileName: Type.Union([Type.String({ minLength: 1, maxLength: 500 }), Type.Null()]),
    mediaType: Type.Union([Type.String({ minLength: 1, maxLength: 200 }), Type.Null()]),
    sizeBytes: Type.Union([Type.Integer({ minimum: 0 }), Type.Null()]),
    compiledText: Type.Union([Type.String(), Type.Null()]),
    sourceText: Type.Optional(Type.String()),
    email: Type.Optional(V3KnowledgeEmailPreviewSchema),
    compiledSha256: Type.Union([Sha256Schema, Type.Null()]),
    characterCount: Type.Union([Type.Integer({ minimum: 0 }), Type.Null()]),
  },
  { additionalProperties: false },
);
export type V3KnowledgeMaterialContent = Static<typeof V3KnowledgeMaterialContentSchema>;

export const V3KnowledgeCardSchema = Type.Object(
  {
    id: UuidSchema,
    knowledgeBaseId: UuidSchema,
    materialId: UuidSchema,
    position: Type.Integer({ minimum: 0 }),
    title: Type.String({ minLength: 1, maxLength: 200 }),
    contentMarkdown: Type.String({ minLength: 1, maxLength: 50_000 }),
    keywords: Type.Array(Type.String({ minLength: 1, maxLength: 80 }), {
      minItems: 1,
      maxItems: 12,
      uniqueItems: true,
    }),
    relatedCardIds: Type.Array(UuidSchema, { maxItems: 5, uniqueItems: true }),
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeCard = Static<typeof V3KnowledgeCardSchema>;

const KnowledgeCollaboratorRoleSchema = Type.Union([
  Type.Literal('owner'),
  Type.Literal('manager'),
  Type.Literal('editor'),
  Type.Literal('viewer'),
]);

export const V3InviteKnowledgeCollaboratorSchema = Type.Object(
  {
    email: Type.String({ format: 'email', minLength: 3, maxLength: 320 }),
    role: Type.Union([Type.Literal('manager'), Type.Literal('editor'), Type.Literal('viewer')]),
  },
  { additionalProperties: false },
);
export type V3InviteKnowledgeCollaborator = Static<typeof V3InviteKnowledgeCollaboratorSchema>;

export const V3KnowledgeCollaboratorSchema = Type.Object(
  {
    id: UuidSchema,
    knowledgeBaseId: UuidSchema,
    userId: NullableUuidSchema,
    email: Type.Union([Type.String({ format: 'email', maxLength: 320 }), Type.Null()]),
    displayName: Type.Union([Type.String({ minLength: 1, maxLength: 200 }), Type.Null()]),
    role: KnowledgeCollaboratorRoleSchema,
    status: Type.Union([Type.Literal('pending'), Type.Literal('active')]),
    isCurrentUser: Type.Boolean(),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeCollaborator = Static<typeof V3KnowledgeCollaboratorSchema>;

export const V3KnowledgeTaskTypeSchema = Type.Union([
  Type.Literal('compilation'),
  Type.Literal('lint'),
  Type.Literal('source_refresh'),
]);
export type V3KnowledgeTaskType = Static<typeof V3KnowledgeTaskTypeSchema>;

export const V3KnowledgeScheduleExpressionSchema = Type.String({
  minLength: 5,
  maxLength: 120,
  pattern: '^\\S+(?:\\s+\\S+){4}$',
});
export type V3KnowledgeScheduleExpression = Static<typeof V3KnowledgeScheduleExpressionSchema>;

export const V3CreateKnowledgeScheduleSchema = Type.Object(
  {
    taskType: V3KnowledgeTaskTypeSchema,
    schedule: V3KnowledgeScheduleExpressionSchema,
  },
  { additionalProperties: false },
);
export type V3CreateKnowledgeSchedule = Static<typeof V3CreateKnowledgeScheduleSchema>;

export const V3UpdateKnowledgeScheduleSchema = Type.Object(
  { enabled: Type.Boolean() },
  { additionalProperties: false },
);
export type V3UpdateKnowledgeSchedule = Static<typeof V3UpdateKnowledgeScheduleSchema>;

export const V3KnowledgeScheduleSchema = Type.Object(
  {
    id: UuidSchema,
    knowledgeBaseId: UuidSchema,
    taskType: V3KnowledgeTaskTypeSchema,
    schedule: V3KnowledgeScheduleExpressionSchema,
    timezone: Type.String({ minLength: 1, maxLength: 120 }),
    enabled: Type.Boolean(),
    lastRunAt: NullableDateTimeSchema,
    lastRunState: Type.Union([
      Type.Literal('never'),
      Type.Literal('running'),
      Type.Literal('succeeded'),
      Type.Literal('failed'),
    ]),
    failureDetail: Type.Union([Type.String({ maxLength: 2_000 }), Type.Null()]),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeSchedule = Static<typeof V3KnowledgeScheduleSchema>;

export const V3KnowledgeScheduleRunSchema = Type.Object(
  {
    id: UuidSchema,
    knowledgeBaseId: UuidSchema,
    scheduledTaskId: UuidSchema,
    taskType: V3KnowledgeTaskTypeSchema,
    status: Type.Union([
      Type.Literal('scheduled'),
      Type.Literal('running'),
      Type.Literal('success'),
      Type.Literal('failed'),
      Type.Literal('canceled'),
    ]),
    reportMarkdown: Type.Union([Type.String({ maxLength: 200_000 }), Type.Null()]),
    errorMessage: Type.Union([Type.String({ maxLength: 2_000 }), Type.Null()]),
    scheduledFor: DateTimeSchema,
    createdAt: DateTimeSchema,
    startedAt: NullableDateTimeSchema,
    finishedAt: NullableDateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeScheduleRun = Static<typeof V3KnowledgeScheduleRunSchema>;

export const V3KnowledgeCompilationTemplateSchema = Type.Union([
  Type.Literal('llm_wiki'),
  Type.Literal('multi_repo_wiki'),
  Type.Literal('custom'),
]);
export type V3KnowledgeCompilationTemplate = Static<typeof V3KnowledgeCompilationTemplateSchema>;

export const V3KnowledgeSettingsSchema = Type.Object(
  {
    knowledgeBaseId: UuidSchema,
    compilationTemplate: V3KnowledgeCompilationTemplateSchema,
    appendPrompt: Type.String({ maxLength: 5_000 }),
    customPrompt: Type.String({ maxLength: 5_000 }),
    autoCompile: Type.Boolean(),
    autoCompileDelayMinutes: Type.Union([Type.Literal(1), Type.Literal(30)]),
    lastCompiledAt: NullableDateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeSettings = Static<typeof V3KnowledgeSettingsSchema>;

export const V3UpdateKnowledgeSettingsSchema = Type.Object(
  {
    compilationTemplate: V3KnowledgeCompilationTemplateSchema,
    appendPrompt: Type.String({ maxLength: 5_000 }),
    customPrompt: Type.String({ maxLength: 5_000 }),
    autoCompile: Type.Boolean(),
    autoCompileDelayMinutes: Type.Union([Type.Literal(1), Type.Literal(30)]),
  },
  { additionalProperties: false },
);
export type V3UpdateKnowledgeSettings = Static<typeof V3UpdateKnowledgeSettingsSchema>;

export const V3CompileKnowledgeBaseSchema = Type.Object(
  { mode: Type.Union([Type.Literal('incremental'), Type.Literal('full')]) },
  { additionalProperties: false },
);
export type V3CompileKnowledgeBase = Static<typeof V3CompileKnowledgeBaseSchema>;

export const V3KnowledgeBindingInputSchema = Type.Object(
  {
    wakerId: UuidSchema,
    expectedConfigurationVersionId: UuidSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeBindingInput = Static<typeof V3KnowledgeBindingInputSchema>;

export const V3KnowledgeBindingSchema = Type.Object(
  {
    versionId: UuidSchema,
    knowledgeBaseId: UuidSchema,
    wakerId: UuidSchema,
    knowledgeVersion: Type.Integer({ minimum: 0 }),
    createdBy: NullableUuidSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3KnowledgeBinding = Static<typeof V3KnowledgeBindingSchema>;

export const V3SkillMarketplaceCategorySchema = Type.Union([
  Type.Literal('devops'),
  Type.Literal('productivity'),
  Type.Literal('research-analysis'),
  Type.Literal('content-creation'),
  Type.Literal('design-ui'),
  Type.Literal('data-ai'),
  Type.Literal('docs-writing'),
]);
export type V3SkillMarketplaceCategory = Static<typeof V3SkillMarketplaceCategorySchema>;

export const V3SkillMarketplaceSortSchema = Type.Union([
  Type.Literal('hottest'),
  Type.Literal('newest'),
  Type.Literal('name'),
]);
export type V3SkillMarketplaceSort = Static<typeof V3SkillMarketplaceSortSchema>;

export const V3SkillMarketplaceItemSchema = Type.Object(
  {
    id: Type.String({ minLength: 1, maxLength: 120 }),
    name: Type.String({ minLength: 1, maxLength: 160 }),
    localizedName: Type.Union([Type.String({ minLength: 1, maxLength: 160 }), Type.Null()]),
    description: Type.String({ maxLength: 20_000 }),
    localizedDescription: Type.Union([Type.String({ minLength: 1, maxLength: 20_000 }), Type.Null()]),
    author: Type.String({ maxLength: 200 }),
    category: Type.String({ maxLength: 120 }),
    iconUrl: Type.Union([Type.String({ format: 'uri', maxLength: 2_000 }), Type.Null()]),
    installCount: Type.Integer({ minimum: 0 }),
    recommended: Type.Boolean(),
    updatedAt: NullableDateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3SkillMarketplaceItem = Static<typeof V3SkillMarketplaceItemSchema>;

export const V3SkillMarketplaceDetailSchema = Type.Object(
  {
    id: Type.String({ minLength: 1, maxLength: 120 }),
    name: Type.String({ minLength: 1, maxLength: 160 }),
    localizedName: Type.Union([Type.String({ minLength: 1, maxLength: 160 }), Type.Null()]),
    description: Type.String({ maxLength: 20_000 }),
    localizedDescription: Type.Union([Type.String({ minLength: 1, maxLength: 20_000 }), Type.Null()]),
    author: Type.String({ maxLength: 200 }),
    authorName: Type.String({ maxLength: 200 }),
    category: Type.String({ maxLength: 120 }),
    iconUrl: Type.Union([Type.String({ format: 'uri', maxLength: 2_000 }), Type.Null()]),
    installCount: Type.Integer({ minimum: 0 }),
    updatedAt: NullableDateTimeSchema,
    version: Type.String({ minLength: 1, maxLength: 80 }),
    recommended: Type.Boolean(),
    readmeMarkdown: Type.String({ maxLength: 200_000 }),
  },
  { additionalProperties: false },
);
export type V3SkillMarketplaceDetail = Static<typeof V3SkillMarketplaceDetailSchema>;

export const V3SkillMarketplacePageSchema = Type.Object(
  {
    items: Type.Array(V3SkillMarketplaceItemSchema, { maxItems: 24 }),
    page: Type.Integer({ minimum: 1 }),
    pageSize: Type.Integer({ minimum: 1, maximum: 24 }),
    total: Type.Integer({ minimum: 0 }),
    lastPage: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3SkillMarketplacePage = Static<typeof V3SkillMarketplacePageSchema>;

export const V3SkillPackagePreparationSourceSchema = Type.Union([
  Type.Literal('upload'),
  Type.Literal('marketplace'),
]);
export type V3SkillPackagePreparationSource = Static<typeof V3SkillPackagePreparationSourceSchema>;

export const V3SkillPackagePreparationSchema = Type.Object(
  {
    id: UuidSchema,
    source: V3SkillPackagePreparationSourceSchema,
    marketplaceSkillId: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
    name: Type.String({ minLength: 1, maxLength: 80 }),
    description: Type.String({ minLength: 1, maxLength: 500 }),
    fileName: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.Union([
      Type.Literal('text/markdown'),
      Type.Literal('application/zip'),
      Type.Literal('application/gzip'),
    ]),
    packageSha256: Sha256Schema,
    contentSha256: Sha256Schema,
    sizeBytes: Type.Integer({ minimum: 1, maximum: 20 * 1024 * 1024 }),
    selfEvolution: Type.Boolean(),
    expiresAt: DateTimeSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3SkillPackagePreparation = Static<typeof V3SkillPackagePreparationSchema>;

export const V3InstallMarketplaceSkillSchema = Type.Object(
  {
    selfEvolution: Type.Boolean(),
    expectedConfigurationVersionId: UuidSchema,
  },
  { additionalProperties: false },
);
export type V3InstallMarketplaceSkill = Static<typeof V3InstallMarketplaceSkillSchema>;

export const V3SkillInstallationSchema = Type.Object(
  {
    id: UuidSchema,
    wakerId: UuidSchema,
    currentVersionId: UuidSchema,
    marketplaceSkillId: Type.Optional(Type.String({ minLength: 1 })),
    origin: Type.Optional(
      Type.Union([
        Type.Literal('built-in'),
        Type.Literal('template-preset'),
        Type.Literal('upload'),
        Type.Literal('marketplace'),
        Type.Literal('agent-created'),
      ]),
    ),
    name: Type.String({ minLength: 1, maxLength: 80 }),
    description: Type.String({ minLength: 1, maxLength: 500 }),
    source: Type.Union([Type.Literal('markdown'), Type.Literal('archive')]),
    status: Type.Union([Type.Literal('installed'), Type.Literal('disabled')]),
    version: Type.Integer({ minimum: 1 }),
    contentSha256: Sha256Schema,
    fileName: Type.String({ minLength: 1, maxLength: 255 }),
    selfEvolution: Type.Boolean(),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3SkillInstallation = Static<typeof V3SkillInstallationSchema>;

export const V3SkillVersionSchema = Type.Object(
  {
    id: UuidSchema,
    skillId: UuidSchema,
    wakerId: UuidSchema,
    number: Type.Integer({ minimum: 1 }),
    name: Type.String({ minLength: 1, maxLength: 80 }),
    description: Type.String({ minLength: 1, maxLength: 500 }),
    source: Type.Union([Type.Literal('markdown'), Type.Literal('archive')]),
    state: Type.Union([Type.Literal('installed'), Type.Literal('disabled')]),
    contentSha256: Sha256Schema,
    markdown: Type.String({ maxLength: 512_000 }),
    fileName: Type.String({ minLength: 1, maxLength: 255 }),
    selfEvolution: Type.Boolean(),
    historyKind: Type.Union([Type.Literal('system'), Type.Literal('manual'), Type.Literal('protective')]),
    origin: V3SkillInstallationSchema.properties.origin,
    managedOperation: Type.Optional(
      Type.Union([Type.Literal('create'), Type.Literal('edit'), Type.Literal('write_file')]),
    ),
    comparedWithVersionId: NullableUuidSchema,
    changeSummary: Type.String({ minLength: 1, maxLength: 2_000 }),
    createdBy: NullableUuidSchema,
    createdAt: DateTimeSchema,
    isCurrent: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3SkillVersion = Static<typeof V3SkillVersionSchema>;

export const V3SkillDiffLineSchema = Type.Object(
  {
    operation: Type.Union([Type.Literal('unchanged'), Type.Literal('added'), Type.Literal('removed')]),
    content: Type.String({ maxLength: 20_000 }),
    oldLineNumber: Type.Union([Type.Integer({ minimum: 1 }), Type.Null()]),
    newLineNumber: Type.Union([Type.Integer({ minimum: 1 }), Type.Null()]),
  },
  { additionalProperties: false },
);
export type V3SkillDiffLine = Static<typeof V3SkillDiffLineSchema>;

export const V3SkillFileDiffSchema = Type.Object(
  {
    path: Type.String(),
    status: Type.Union([Type.Literal('added'), Type.Literal('removed'), Type.Literal('modified')]),
    binary: Type.Boolean(),
    oldSizeBytes: Type.Union([Type.Integer({ minimum: 0 }), Type.Null()]),
    newSizeBytes: Type.Union([Type.Integer({ minimum: 0 }), Type.Null()]),
    addedLines: Type.Integer({ minimum: 0 }),
    removedLines: Type.Integer({ minimum: 0 }),
    unchangedLines: Type.Integer({ minimum: 0 }),
    oldLineCount: Type.Integer({ minimum: 0 }),
    newLineCount: Type.Integer({ minimum: 0 }),
    lines: Type.Array(V3SkillDiffLineSchema, { maxItems: 50_000 }),
  },
  { additionalProperties: false },
);
export type V3SkillFileDiff = Static<typeof V3SkillFileDiffSchema>;

export const V3SkillComparisonSchema = Type.Object(
  {
    from: Type.Union([V3SkillVersionSchema, Type.Null()]),
    to: V3SkillVersionSchema,
    addedLines: Type.Integer({ minimum: 0 }),
    removedLines: Type.Integer({ minimum: 0 }),
    unchangedLines: Type.Integer({ minimum: 0 }),
    files: Type.Array(V3SkillFileDiffSchema, { maxItems: 4000 }),
  },
  { additionalProperties: false },
);
export type V3SkillComparison = Static<typeof V3SkillComparisonSchema>;

export const V3SkillLifecycleInputSchema = Type.Union([
  Type.Object(
    {
      action: Type.Union([Type.Literal('enable'), Type.Literal('disable'), Type.Literal('remove')]),
      expectedVersion: Type.Integer({ minimum: 1 }),
      expectedConfigurationVersionId: UuidSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      action: Type.Literal('rollback'),
      targetVersionId: UuidSchema,
      expectedVersion: Type.Integer({ minimum: 1 }),
      expectedConfigurationVersionId: UuidSchema,
    },
    { additionalProperties: false },
  ),
]);
export type V3SkillLifecycleInput = Static<typeof V3SkillLifecycleInputSchema>;

export const V3ConnectorTransportSchema = Type.Union([
  Type.Literal('stdio'),
  Type.Literal('sse'),
  Type.Literal('streamable_http'),
]);
export type V3ConnectorTransport = Static<typeof V3ConnectorTransportSchema>;

export const V3WakerBuiltinCapabilitiesSchema = Type.Object(
  {
    memory: Type.Boolean(),
    knowledge: Type.Boolean(),
    imChannelSend: Type.Boolean(),
    groupChatContext: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3WakerBuiltinCapabilities = Static<typeof V3WakerBuiltinCapabilitiesSchema>;

export function defaultWakerBuiltinCapabilities(): V3WakerBuiltinCapabilities {
  return { memory: true, knowledge: true, imChannelSend: true, groupChatContext: true };
}

export const V3_BROWSER_CONNECTOR_CHROME_EXTENSION_ID = 'gblapfbnbicdckfhkllcnfleiemhmgeb' as const;
export const V3_BROWSER_CONNECTOR_CANDIDATE_EXTENSION_ID = 'kcncpeokigajockdclpncmgcgogednab' as const;

const V3BrowserConnectorVersionSchema = Type.String({
  minLength: 5,
  maxLength: 80,
  pattern: '^[0-9]+\\.[0-9]+\\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$',
});

export const V3BrowserConnectorManualProvenanceSchema = Type.Object(
  {
    source: Type.Literal('manual_fallback'),
    version: V3BrowserConnectorVersionSchema,
    manifestSha256: Type.Union([Sha256Schema, Type.Null()]),
    observedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3BrowserConnectorManualProvenance = Static<typeof V3BrowserConnectorManualProvenanceSchema>;

export const V3BrowserConnectorCandidateProvenanceSchema = Type.Object(
  {
    source: Type.Literal('candidate_manual_package'),
    extensionId: Type.Literal(V3_BROWSER_CONNECTOR_CANDIDATE_EXTENSION_ID),
    version: V3BrowserConnectorVersionSchema,
    manifestSha256: Type.Union([Sha256Schema, Type.Null()]),
    observedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3BrowserConnectorCandidateProvenance = Static<
  typeof V3BrowserConnectorCandidateProvenanceSchema
>;

export const V3BrowserConnectorLiveProvenanceSchema = Type.Union([
  Type.Object(
    {
      source: Type.Literal('chrome_web_store'),
      extensionId: Type.Literal(V3_BROWSER_CONNECTOR_CHROME_EXTENSION_ID),
      version: V3BrowserConnectorVersionSchema,
      observedAt: DateTimeSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      source: Type.Literal('manual_fallback'),
      extensionId: Type.Null(),
      version: V3BrowserConnectorVersionSchema,
      observedAt: DateTimeSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      source: Type.Literal('candidate_manual_package'),
      extensionId: Type.Literal(V3_BROWSER_CONNECTOR_CANDIDATE_EXTENSION_ID),
      version: V3BrowserConnectorVersionSchema,
      observedAt: DateTimeSchema,
    },
    { additionalProperties: false },
  ),
]);
export type V3BrowserConnectorLiveProvenance = Static<typeof V3BrowserConnectorLiveProvenanceSchema>;

export const V3BrowserConnectorFallbackSchema = Type.Union([
  Type.Object(
    {
      status: Type.Union([Type.Literal('unknown'), Type.Literal('absent')]),
      displayPath: Type.Null(),
      provenance: Type.Null(),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      status: Type.Literal('available'),
      displayPath: Type.String({ minLength: 1, maxLength: 4_096 }),
      provenance: Type.Union([
        V3BrowserConnectorManualProvenanceSchema,
        V3BrowserConnectorCandidateProvenanceSchema,
      ]),
    },
    { additionalProperties: false },
  ),
]);
export type V3BrowserConnectorFallback = Static<typeof V3BrowserConnectorFallbackSchema>;

export const V3BrowserConnectorLiveSchema = Type.Union([
  Type.Object(
    {
      connectionStatus: Type.Literal('unavailable'),
      ready: Type.Literal(false),
      relayRunning: Type.Literal(false),
      relayEnabled: Type.Literal(false),
      protocolFamily: Type.Null(),
      provenance: Type.Null(),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      connectionStatus: Type.Literal('disconnected'),
      ready: Type.Literal(false),
      relayRunning: Type.Boolean(),
      relayEnabled: Type.Boolean(),
      protocolFamily: Type.Union([Type.Literal('v2'), Type.Null()]),
      provenance: Type.Union([V3BrowserConnectorLiveProvenanceSchema, Type.Null()]),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      connectionStatus: Type.Literal('connected'),
      ready: Type.Boolean(),
      relayRunning: Type.Literal(true),
      relayEnabled: Type.Literal(true),
      protocolFamily: Type.Literal('v2'),
      provenance: V3BrowserConnectorLiveProvenanceSchema,
    },
    { additionalProperties: false },
  ),
]);
export type V3BrowserConnectorLive = Static<typeof V3BrowserConnectorLiveSchema>;

export const V3BrowserConnectorGrantSchema = Type.Object(
  {
    status: Type.Union([
      Type.Literal('none'),
      Type.Literal('pending-observation'),
      Type.Literal('authorized-current-tab'),
      Type.Literal('revoked-or-expired'),
    ]),
  },
  { additionalProperties: false },
);
export type V3BrowserConnectorGrant = Static<typeof V3BrowserConnectorGrantSchema>;

export const V3BrowserConnectorEnablementSchema = Type.Object(
  {
    wakerId: UuidSchema,
    enabled: Type.Boolean(),
    version: Type.Integer({ minimum: 1 }),
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3BrowserConnectorEnablement = Static<typeof V3BrowserConnectorEnablementSchema>;

export const V3UpdateBrowserConnectorEnablementSchema = Type.Object(
  {
    enabled: Type.Boolean(),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3UpdateBrowserConnectorEnablement = Static<typeof V3UpdateBrowserConnectorEnablementSchema>;

export const V3SkillEvolutionPolicySchema = Type.Object(
  {
    wakerId: UuidSchema,
    enabled: Type.Boolean(),
    version: Type.Integer({ minimum: 1 }),
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3SkillEvolutionPolicy = Static<typeof V3SkillEvolutionPolicySchema>;

export const V3UpdateSkillEvolutionPolicySchema = Type.Object(
  {
    enabled: Type.Boolean(),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3UpdateSkillEvolutionPolicy = Static<typeof V3UpdateSkillEvolutionPolicySchema>;

export const V3BrowserConnectorStateSchema = Type.Object(
  {
    fallback: V3BrowserConnectorFallbackSchema,
    live: V3BrowserConnectorLiveSchema,
    grant: V3BrowserConnectorGrantSchema,
    enablement: V3BrowserConnectorEnablementSchema,
    browserContextToolAvailable: Type.Boolean(),
    browserPageToolReady: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3BrowserConnectorState = Static<typeof V3BrowserConnectorStateSchema>;

export function composeV3BrowserConnectorState(input: {
  fallback: V3BrowserConnectorFallback;
  live: V3BrowserConnectorLive;
  grant: V3BrowserConnectorGrant;
  enablement: V3BrowserConnectorEnablement;
}): V3BrowserConnectorState {
  const browserContextToolAvailable =
    input.enablement.enabled &&
    input.live.connectionStatus === 'connected' &&
    input.live.ready &&
    input.live.relayRunning &&
    input.live.relayEnabled;
  const browserPageToolReady = browserContextToolAvailable && input.grant.status === 'authorized-current-tab';
  return { ...input, browserContextToolAvailable, browserPageToolReady };
}

export function createV3BrowserConnectorWebNoopState(
  enablement: V3BrowserConnectorEnablement,
): V3BrowserConnectorState {
  return composeV3BrowserConnectorState({
    fallback: { status: 'unknown', displayPath: null, provenance: null },
    live: {
      connectionStatus: 'unavailable',
      ready: false,
      relayRunning: false,
      relayEnabled: false,
      protocolFamily: null,
      provenance: null,
    },
    grant: { status: 'none' },
    enablement,
  });
}

const V3ConnectorEnvironmentNameSchema = Type.String({ pattern: '^[A-Za-z_][A-Za-z0-9_]{0,127}$' });
const V3ConnectorHeaderNameSchema = Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,127}$' });

export const V3CreateConnectorSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 160 }),
    transport: V3ConnectorTransportSchema,
    command: Type.Optional(Type.String({ minLength: 1, maxLength: 2_000 })),
    arguments: Type.Optional(Type.Array(Type.String({ maxLength: 2_000 }), { maxItems: 100 })),
    url: Type.Optional(Type.String({ format: 'uri', maxLength: 2_000 })),
    environment: Type.Optional(
      Type.Record(V3ConnectorEnvironmentNameSchema, Type.String({ minLength: 1, maxLength: 65_536 })),
    ),
    headers: Type.Optional(
      Type.Record(V3ConnectorHeaderNameSchema, Type.String({ minLength: 1, maxLength: 65_536 })),
    ),
    headersHelper: Type.Optional(Type.String({ maxLength: 8_192 })),
    timeoutSeconds: Type.Integer({ minimum: 1, maximum: 600 }),
  },
  { additionalProperties: false },
);
export type V3CreateConnector = Static<typeof V3CreateConnectorSchema>;

export const V3CreateWakerConnectorSchema = Type.Object(
  {
    ...V3CreateConnectorSchema.properties,
    expectedConfigurationVersionId: UuidSchema,
  },
  { additionalProperties: false },
);
export type V3CreateWakerConnector = Static<typeof V3CreateWakerConnectorSchema>;

export const V3UpdateConnectorSchema = Type.Object(
  {
    command: Type.Optional(Type.String({ minLength: 1, maxLength: 2_000 })),
    arguments: Type.Optional(Type.Array(Type.String({ maxLength: 2_000 }), { maxItems: 100 })),
    url: Type.Optional(Type.String({ format: 'uri', maxLength: 2_000 })),
    environment: Type.Record(V3ConnectorEnvironmentNameSchema, Type.String({ maxLength: 65_536 })),
    headers: Type.Optional(Type.Record(V3ConnectorHeaderNameSchema, Type.String({ maxLength: 65_536 }))),
    headersHelper: Type.Optional(Type.String({ maxLength: 8_192 })),
    timeoutSeconds: Type.Integer({ minimum: 1, maximum: 600 }),
    expectedVersion: Type.Integer({ minimum: 1 }),
    expectedConfigurationVersionId: UuidSchema,
  },
  { additionalProperties: false },
);
export type V3UpdateConnector = Static<typeof V3UpdateConnectorSchema>;

export const V3ConnectorToolSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 300 }),
    description: Type.String({ maxLength: 2_000 }),
  },
  { additionalProperties: false },
);
export type V3ConnectorTool = Static<typeof V3ConnectorToolSchema>;

export const V3ConnectorDiagnosticSchema = Type.Object(
  {
    status: Type.Union([
      Type.Literal('not_run'),
      Type.Literal('ready'),
      Type.Literal('degraded'),
      Type.Literal('unavailable'),
    ]),
    message: Type.String({ minLength: 1, maxLength: 2_000 }),
    tools: Type.Array(V3ConnectorToolSchema, { maxItems: 2_000 }),
    checkedAt: NullableDateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3ConnectorDiagnostic = Static<typeof V3ConnectorDiagnosticSchema>;

export const V3ConnectorSchema = Type.Object(
  {
    id: UuidSchema,
    wakerId: UuidSchema,
    currentVersionId: UuidSchema,
    name: Type.String({ minLength: 1, maxLength: 160 }),
    transport: V3ConnectorTransportSchema,
    command: Type.Union([Type.String({ minLength: 1, maxLength: 2_000 }), Type.Null()]),
    arguments: Type.Array(Type.String({ maxLength: 2_000 }), { maxItems: 100 }),
    url: Type.Union([Type.String({ format: 'uri', maxLength: 2_000 }), Type.Null()]),
    credentialKeys: Type.Array(Type.String({ minLength: 1, maxLength: 128 }), {
      maxItems: 100,
      uniqueItems: true,
    }),
    selectedTools: Type.Array(Type.String({ minLength: 1, maxLength: 300 }), {
      maxItems: 2_000,
      uniqueItems: true,
    }),
    timeoutSeconds: Type.Integer({ minimum: 1, maximum: 600 }),
    headersHelper: Type.Optional(Type.String({ maxLength: 8_192 })),
    status: Type.Union([
      Type.Literal('configured'),
      Type.Literal('ready'),
      Type.Literal('degraded'),
      Type.Literal('disabled'),
    ]),
    diagnostic: V3ConnectorDiagnosticSchema,
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3Connector = Static<typeof V3ConnectorSchema>;

export const V3ConnectorToolSelectionInputSchema = Type.Object(
  {
    expectedVersion: Type.Integer({ minimum: 1 }),
    expectedConfigurationVersionId: UuidSchema,
    selectedTools: Type.Array(Type.String({ minLength: 1, maxLength: 300 }), {
      maxItems: 2_000,
      uniqueItems: true,
    }),
  },
  { additionalProperties: false },
);
export type V3ConnectorToolSelectionInput = Static<typeof V3ConnectorToolSelectionInputSchema>;

export const V3ConnectorLifecycleInputSchema = Type.Object(
  {
    action: Type.Union([Type.Literal('enable'), Type.Literal('disable'), Type.Literal('remove')]),
    expectedVersion: Type.Integer({ minimum: 1 }),
    expectedConfigurationVersionId: UuidSchema,
  },
  { additionalProperties: false },
);
export type V3ConnectorLifecycleInput = Static<typeof V3ConnectorLifecycleInputSchema>;

export const V3ImProviderSchema = Type.Union([
  Type.Literal('dingtalk_bot'),
  Type.Literal('dingtalk_account'),
  Type.Literal('feishu'),
  Type.Literal('wechat'),
  Type.Literal('wecom'),
  Type.Literal('qq_bot'),
]);
export type V3ImProvider = Static<typeof V3ImProviderSchema>;

export const V3ImAccessPolicySchema = Type.Union([
  Type.Literal('approval_required'),
  Type.Literal('open_access'),
]);
export type V3ImAccessPolicy = Static<typeof V3ImAccessPolicySchema>;

export const V3ImChannelDiagnosticSchema = Type.Object(
  {
    status: Type.Union([
      Type.Literal('not_run'),
      Type.Literal('ready'),
      Type.Literal('degraded'),
      Type.Literal('unavailable'),
    ]),
    message: Type.String({ minLength: 1, maxLength: 2_000 }),
    checkedAt: NullableDateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3ImChannelDiagnostic = Static<typeof V3ImChannelDiagnosticSchema>;

export const V3ImChannelSchema = Type.Object(
  {
    id: UuidSchema,
    currentVersionId: UuidSchema,
    wakerId: NullableUuidSchema,
    provider: V3ImProviderSchema,
    displayName: Type.String({ minLength: 1, maxLength: 160 }),
    accessPolicy: V3ImAccessPolicySchema,
    autoSendArtifacts: Type.Boolean(),
    enabled: Type.Boolean(),
    cardType: Type.Union([Type.Literal('standard'), Type.Literal('ai'), Type.Null()]),
    credentialKeys: Type.Array(Type.String({ minLength: 1, maxLength: 128 }), {
      maxItems: 20,
      uniqueItems: true,
    }),
    status: Type.Union([
      Type.Literal('configured'),
      Type.Literal('ready'),
      Type.Literal('degraded'),
      Type.Literal('disabled'),
    ]),
    diagnostic: V3ImChannelDiagnosticSchema,
    version: Type.Integer({ minimum: 1 }),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3ImChannel = Static<typeof V3ImChannelSchema>;

export const V3CreateImChannelSchema = Type.Object(
  {
    provider: V3ImProviderSchema,
    wakerId: NullableUuidSchema,
    displayName: Type.String({ minLength: 1, maxLength: 160 }),
    accessPolicy: V3ImAccessPolicySchema,
    autoSendArtifacts: Type.Boolean(),
    enabled: Type.Boolean(),
    cardType: Type.Optional(Type.Union([Type.Literal('standard'), Type.Literal('ai')])),
    credentials: Type.Record(
      Type.String({ pattern: '^[A-Z][A-Z0-9_]{1,63}$' }),
      Type.String({ minLength: 1, maxLength: 65_536 }),
    ),
  },
  { additionalProperties: false },
);
export type V3CreateImChannel = Static<typeof V3CreateImChannelSchema>;

export const V3UpdateImChannelSchema = Type.Object(
  {
    ...V3CreateImChannelSchema.properties,
    credentials: Type.Record(
      Type.String({ pattern: '^[A-Z][A-Z0-9_]{1,63}$' }),
      Type.String({ maxLength: 65_536 }),
    ),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3UpdateImChannel = Static<typeof V3UpdateImChannelSchema>;

export const V3ImChannelLifecycleInputSchema = Type.Object(
  {
    action: Type.Union([Type.Literal('enable'), Type.Literal('disable'), Type.Literal('remove')]),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3ImChannelLifecycleInput = Static<typeof V3ImChannelLifecycleInputSchema>;

export const V3ImQrAuthStartInputSchema = Type.Object(
  { provider: Type.Literal('feishu') },
  { additionalProperties: false },
);
export type V3ImQrAuthStartInput = Static<typeof V3ImQrAuthStartInputSchema>;

export const V3ImQrAuthSessionSchema = Type.Object(
  {
    sessionId: UuidSchema,
    provider: Type.Literal('feishu'),
    verificationUrl: Type.String({ format: 'uri', maxLength: 8_000 }),
    pollAfterMs: Type.Integer({ minimum: 1_000, maximum: 60_000 }),
    expiresAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3ImQrAuthSession = Static<typeof V3ImQrAuthSessionSchema>;

export const V3ImQrAuthPollInputSchema = Type.Object(
  { sessionId: UuidSchema },
  { additionalProperties: false },
);
export type V3ImQrAuthPollInput = Static<typeof V3ImQrAuthPollInputSchema>;

export const V3ImQrAuthPollResultSchema = Type.Object(
  {
    status: Type.Union([
      Type.Literal('pending'),
      Type.Literal('expired'),
      Type.Literal('denied'),
      Type.Literal('completed'),
    ]),
    pollAfterMs: Type.Integer({ minimum: 1_000, maximum: 60_000 }),
    channel: Type.Union([V3ImChannelSchema, Type.Null()]),
  },
  { additionalProperties: false },
);
export type V3ImQrAuthPollResult = Static<typeof V3ImQrAuthPollResultSchema>;

export const V3ImConversationSchema = Type.Object(
  {
    id: UuidSchema,
    channelId: UuidSchema,
    channelName: Type.String({ minLength: 1, maxLength: 160 }),
    provider: V3ImProviderSchema,
    name: Type.String({ minLength: 1, maxLength: 300 }),
    type: Type.Union([Type.Literal('group'), Type.Literal('direct')]),
    source: Type.String({ minLength: 1, maxLength: 160 }),
    wakerId: NullableUuidSchema,
    groupId: NullableUuidSchema,
    workspaceReferenceId: NullableUuidSchema,
    model: Type.Union([Type.String({ minLength: 1, maxLength: 200 }), Type.Null()]),
    atWaker: Type.Boolean(),
    pairingVersion: Type.Union([Type.Integer({ minimum: 1 }), Type.Null()]),
    status: Type.Union([
      Type.Literal('unpaired'),
      Type.Literal('pending'),
      Type.Literal('active'),
      Type.Literal('paused'),
      Type.Literal('invalid'),
      Type.Literal('disabled'),
    ]),
    lastEventAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3ImConversation = Static<typeof V3ImConversationSchema>;

export const V3ImPairingRequestSchema = Type.Object(
  {
    id: UuidSchema,
    channelId: UuidSchema,
    conversationId: UuidSchema,
    conversationName: Type.String({ minLength: 1, maxLength: 300 }),
    provider: V3ImProviderSchema,
    conversationType: Type.Union([Type.Literal('group'), Type.Literal('direct')]),
    status: Type.Union([
      Type.Literal('pending'),
      Type.Literal('approved'),
      Type.Literal('rejected'),
      Type.Literal('ignored'),
    ]),
    version: Type.Integer({ minimum: 1 }),
    requestedAt: DateTimeSchema,
    resolvedAt: NullableDateTimeSchema,
    resolvedBy: NullableUuidSchema,
  },
  { additionalProperties: false },
);
export type V3ImPairingRequest = Static<typeof V3ImPairingRequestSchema>;

export const V3CreateImPairingSchema = Type.Object(
  {
    conversationId: UuidSchema,
    wakerId: NullableUuidSchema,
    groupId: NullableUuidSchema,
    workspaceReferenceId: NullableUuidSchema,
    model: Type.String({ minLength: 1, maxLength: 200 }),
    atWaker: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type V3CreateImPairing = Static<typeof V3CreateImPairingSchema>;

const V3ManualImPairingBaseSchema = {
  channelId: UuidSchema,
  displayName: Type.String({ minLength: 1, maxLength: 300 }),
  wakerId: NullableUuidSchema,
  groupId: NullableUuidSchema,
  workspaceReferenceId: NullableUuidSchema,
  model: Type.String({ minLength: 1, maxLength: 200 }),
  atWaker: Type.Boolean(),
};

export const V3CreateManualImPairingSchema = Type.Union([
  Type.Object(
    {
      ...V3ManualImPairingBaseSchema,
      type: Type.Literal('direct'),
      receiveIdType: Type.Union([Type.Literal('open_id'), Type.Literal('user_id')]),
      receiveId: Type.String({ minLength: 1, maxLength: 500 }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...V3ManualImPairingBaseSchema,
      type: Type.Literal('group'),
      receiveIdType: Type.Literal('chat_id'),
      receiveId: Type.String({ minLength: 1, maxLength: 500 }),
    },
    { additionalProperties: false },
  ),
]);
export type V3CreateManualImPairing = Static<typeof V3CreateManualImPairingSchema>;

export const V3UpdateImPairingSchema = Type.Object(
  {
    wakerId: NullableUuidSchema,
    groupId: NullableUuidSchema,
    workspaceReferenceId: NullableUuidSchema,
    model: Type.String({ minLength: 1, maxLength: 200 }),
    atWaker: Type.Boolean(),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3UpdateImPairing = Static<typeof V3UpdateImPairingSchema>;

export const V3ImPairingLifecycleInputSchema = Type.Object(
  {
    action: Type.Union([Type.Literal('pause'), Type.Literal('resume'), Type.Literal('remove')]),
    expectedVersion: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type V3ImPairingLifecycleInput = Static<typeof V3ImPairingLifecycleInputSchema>;

export const V3ResolveImPairingRequestSchema = Type.Object(
  {
    decision: Type.Union([Type.Literal('approve'), Type.Literal('reject'), Type.Literal('ignore')]),
    expectedVersion: Type.Integer({ minimum: 1 }),
    pairing: Type.Optional(V3CreateImPairingSchema),
  },
  { additionalProperties: false },
);
export type V3ResolveImPairingRequest = Static<typeof V3ResolveImPairingRequestSchema>;

export const V3BootstrapSchema = Type.Object(
  {
    principal: V3PrincipalSchema,
    workspace: Type.Object(
      {
        id: UuidSchema,
        name: Type.String({ minLength: 1, maxLength: 200 }),
        status: Type.String({ minLength: 1, maxLength: 80 }),
        defaultTimezone: Type.String({ minLength: 1, maxLength: 120 }),
      },
      { additionalProperties: false },
    ),
    capabilities: Type.Record(Type.String(), Type.Boolean()),
    navigation: Type.Record(Type.String(), Type.Integer({ minimum: 0 })),
    aiGatewayModel: Type.String({ maxLength: 200 }),
    aiGatewayModels: Type.Array(Type.String({ minLength: 1, maxLength: 200 }), {
      maxItems: 10_000,
      uniqueItems: true,
    }),
    aiGatewayCatalogStale: Type.Optional(Type.Boolean()),
    preferences: Type.Optional(JsonObjectSchema),
  },
  { additionalProperties: false },
);
export type V3Bootstrap = Static<typeof V3BootstrapSchema>;

/**
 * Public, write-only status for the optional per-user AI gateway credential.
 * The credential itself is deliberately absent; `hint` is limited to the
 * first-two/last-two masked projection returned by the trusted settings boundary.
 */
export const V3AiGatewayVirtualKeyStatusSchema = Type.Union([
  Type.Object(
    {
      configured: Type.Literal(false),
      hint: Type.Optional(Type.String({ minLength: 8, maxLength: 512, pattern: '^.{2}\\*+.{2}$' })),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      configured: Type.Literal(true),
      hint: Type.String({ minLength: 8, maxLength: 512, pattern: '^.{2}\\*+.{2}$' }),
    },
    { additionalProperties: false },
  ),
]);
export type V3AiGatewayVirtualKeyStatus = Static<typeof V3AiGatewayVirtualKeyStatusSchema>;

export const V3UiLanguageSchema = Type.Union([Type.Literal('zh-CN'), Type.Literal('en-US')]);
export type V3UiLanguageCode = Static<typeof V3UiLanguageSchema>;

/**
 * Per-user interface language. `system` means no explicit choice was saved and the
 * host default applies; `retryable` asks the client to keep its local default and
 * read again after `retryAfterMs`.
 */
export const V3LanguageSettingSchema = Type.Object(
  {
    language: V3UiLanguageSchema,
    source: Type.Union([Type.Literal('system'), Type.Literal('user')]),
    retryable: Type.Boolean(),
    retryAfterMs: Type.Integer({ minimum: 0, maximum: 30_000 }),
  },
  { additionalProperties: false },
);
export type V3LanguageSetting = Static<typeof V3LanguageSettingSchema>;

export const V3LanguageSettingInputSchema = Type.Object(
  { language: V3UiLanguageSchema },
  { additionalProperties: false },
);
export type V3LanguageSettingInput = Static<typeof V3LanguageSettingInputSchema>;

export function resolveV3SystemUiLanguage(locales: readonly string[]): V3UiLanguageCode {
  const primary = locales.find((locale) => locale.trim().length > 0);
  return primary?.toLocaleLowerCase('en-US').startsWith('zh') ? 'zh-CN' : 'en-US';
}

/** Result of the authenticated, status-first Feishu virtual-key claim action. */
export const V3AiGatewayVirtualKeyClaimResponseSchema = Type.Union([
  Type.Object(
    {
      status: Type.Literal('ready'),
      configured: Type.Literal(true),
      hint: Type.String({ minLength: 8, maxLength: 512, pattern: '^.{2}\\*+.{2}$' }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      status: Type.Literal('pending'),
      configured: Type.Literal(false),
      pending: Type.Literal(true),
      eventId: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
    },
    { additionalProperties: false },
  ),
]);
export type V3AiGatewayVirtualKeyClaimResponse = Static<typeof V3AiGatewayVirtualKeyClaimResponseSchema>;

/** Input accepted by the write-only per-user AI gateway credential boundary. */
export const V3AiGatewayVirtualKeyInputSchema = Type.Object(
  {
    virtualKey: Type.String({
      minLength: 8,
      maxLength: 512,
      // LiteLLM keys are opaque, but whitespace and control characters are
      // never valid credentials and must not cross the settings boundary.
      pattern: '^[^\\s\\u0000-\\u001F\\u007F-\\u009F]+$',
    }),
  },
  { additionalProperties: false },
);
export type V3AiGatewayVirtualKeyInput = Static<typeof V3AiGatewayVirtualKeyInputSchema>;

const ExportResourceTypeSchema = Type.Union([
  Type.Literal('wakers'),
  Type.Literal('groups'),
  Type.Literal('conversations'),
  Type.Literal('tasks'),
  Type.Literal('runs'),
  Type.Literal('knowledge'),
  Type.Literal('audit_events'),
]);

export const V3CreateExportSchema = Type.Object(
  {
    resourceType: ExportResourceTypeSchema,
    filters: Type.Optional(JsonObjectSchema),
    fields: Type.Array(Type.String({ minLength: 1, maxLength: 200 }), {
      minItems: 1,
      maxItems: 100,
      uniqueItems: true,
    }),
    format: Type.Union([Type.Literal('csv'), Type.Literal('json')]),
  },
  { additionalProperties: false },
);
export type V3CreateExport = Static<typeof V3CreateExportSchema>;

export const V3ExportJobSchema = Type.Object(
  {
    id: UuidSchema,
    resourceType: ExportResourceTypeSchema,
    filters: Type.Optional(JsonObjectSchema),
    fields: Type.Array(Type.String({ minLength: 1, maxLength: 200 }), {
      minItems: 1,
      maxItems: 100,
      uniqueItems: true,
    }),
    format: Type.Union([Type.Literal('csv'), Type.Literal('json')]),
    status: Type.Union([
      Type.Literal('queued'),
      Type.Literal('running'),
      Type.Literal('completed'),
      Type.Literal('failed'),
      Type.Literal('expired'),
    ]),
    schemaVersion: Type.Integer({ minimum: 1 }),
    rowCount: Type.Integer({ minimum: 0 }),
    sha256: Type.Union([Sha256Schema, Type.Null()]),
    artifactId: NullableUuidSchema,
    createdAt: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3ExportJob = Static<typeof V3ExportJobSchema>;

export const V3DesktopMachineRegistrationInputSchema = Type.Object(
  {
    machine_name: Type.String({ minLength: 1, maxLength: 255 }),
    machine_id: UuidSchema,
    rebind_grant: Type.Optional(Type.String({ minLength: 1, maxLength: 1024 })),
    client_version: Type.String({ minLength: 1, maxLength: 100 }),
    platform: Type.Union([Type.Literal('win32'), Type.Literal('darwin'), Type.Literal('linux')]),
    architecture: Type.String({ minLength: 1, maxLength: 32, pattern: '^[A-Za-z0-9_-]+$' }),
  },
  { additionalProperties: false },
);
export type V3DesktopMachineRegistrationInput = Static<typeof V3DesktopMachineRegistrationInputSchema>;

const V3RemoteCredentialSchema = Type.String({
  minLength: 43,
  maxLength: 128,
  pattern: '^[A-Za-z0-9_-]+$',
});

export const V3RemoteMachineRegistrationResultSchema = Type.Object(
  { machine_secret: V3RemoteCredentialSchema },
  { additionalProperties: false },
);
export type V3RemoteMachineRegistrationResult = Static<typeof V3RemoteMachineRegistrationResultSchema>;

export const V3RemoteConversationLeaseSchema = Type.Object(
  {
    epoch: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    lease_token: V3RemoteCredentialSchema,
    run_credential: V3RemoteCredentialSchema,
    runner_instance_id: UuidSchema,
  },
  { additionalProperties: false },
);
export type V3RemoteConversationLease = Static<typeof V3RemoteConversationLeaseSchema>;

export const V3RemoteConversationRunWorkDataSchema = Type.Object(
  {
    type: Type.Literal('conversation_run'),
    run_id: UuidSchema,
    epoch: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    lease_token: V3RemoteCredentialSchema,
    run_credential: V3RemoteCredentialSchema,
    conversation_id: UuidSchema,
    participant_id: UuidSchema,
    waker_ref: Type.Object(
      {
        kind: Type.String({ minLength: 1, maxLength: 120 }),
        id: UuidSchema,
      },
      { additionalProperties: false },
    ),
    waker_snapshot: Type.Object(
      {
        name: Type.String({ minLength: 1, maxLength: 80 }),
        role_name: Type.String({ minLength: 1, maxLength: 120 }),
        bio: Type.String({ maxLength: 10_000 }),
        system_prompt: Type.String({ minLength: 1, maxLength: 500_000 }),
      },
      { additionalProperties: false },
    ),
    employee_id: UuidSchema,
    config_revision: Type.String({ minLength: 1, maxLength: 128 }),
    trigger_message_ids: Type.Array(UuidSchema, { minItems: 1, maxItems: 1_000, uniqueItems: true }),
    previous_executor_session_id: Type.Optional(Type.String({ minLength: 1, maxLength: 255 })),
    resolved_model: Type.Optional(Type.String({ minLength: 1, maxLength: 255 })),
  },
  { additionalProperties: false },
);
export type V3RemoteConversationRunWorkData = Static<typeof V3RemoteConversationRunWorkDataSchema>;

export const V3RemoteConversationRunWorkSchema = Type.Object(
  {
    id: UuidSchema,
    type: Type.Literal('conversation_run'),
    state: Type.Literal('claimed'),
    secret: V3RemoteCredentialSchema,
    token: V3RemoteCredentialSchema,
    data: V3RemoteConversationRunWorkDataSchema,
    created_at: DateTimeSchema,
  },
  { additionalProperties: false },
);
export type V3RemoteConversationRunWork = Static<typeof V3RemoteConversationRunWorkSchema>;

export const V3RemoteWorkPollResponseSchema = Type.Union([
  Type.Object({}, { additionalProperties: false }),
  V3RemoteConversationRunWorkSchema,
]);
export type V3RemoteWorkPollResponse = Static<typeof V3RemoteWorkPollResponseSchema>;

export const V3RemoteWorkAckInputSchema = Type.Object(
  { work_id: UuidSchema },
  { additionalProperties: false },
);
export type V3RemoteWorkAckInput = Static<typeof V3RemoteWorkAckInputSchema>;

export const V3RemoteConversationAcceptInputSchema = Type.Object(
  {
    epoch: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    lease_token: V3RemoteCredentialSchema,
    run_credential: V3RemoteCredentialSchema,
    runner_instance_id: UuidSchema,
    idempotency_key: Type.String({ minLength: 1, maxLength: 255 }),
  },
  { additionalProperties: false },
);

export const V3RemoteConversationFrameSchema = Type.Object(
  {
    seq: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    kind: Type.String({ minLength: 1, maxLength: 120 }),
    payload: Type.Record(Type.String(), Type.Unknown()),
  },
  { additionalProperties: false },
);
export type V3RemoteConversationFrame = Static<typeof V3RemoteConversationFrameSchema>;

export const V3RemoteConversationFramesInputSchema = Type.Object(
  {
    epoch: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    lease_token: V3RemoteCredentialSchema,
    run_credential: V3RemoteCredentialSchema,
    runner_instance_id: UuidSchema,
    frames: Type.Array(V3RemoteConversationFrameSchema, { minItems: 1, maxItems: 100 }),
  },
  { additionalProperties: false },
);

export const V3RemoteConversationCompleteInputSchema = Type.Object(
  {
    epoch: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    lease_token: V3RemoteCredentialSchema,
    run_credential: V3RemoteCredentialSchema,
    runner_instance_id: UuidSchema,
    idempotency_key: Type.String({ minLength: 1, maxLength: 255 }),
    result_message_id: Type.Optional(UuidSchema),
  },
  { additionalProperties: false },
);

export const V3RemoteConversationFailInputSchema = Type.Object(
  {
    epoch: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    lease_token: V3RemoteCredentialSchema,
    run_credential: V3RemoteCredentialSchema,
    runner_instance_id: UuidSchema,
    idempotency_key: Type.String({ minLength: 1, maxLength: 255 }),
    error: Type.Object(
      {
        code: Type.String({ minLength: 1, maxLength: 120 }),
        message: Type.String({ minLength: 1, maxLength: 20_000 }),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);

export const V3RemoteConversationCancelAckInputSchema = Type.Object(
  {
    epoch: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    lease_token: V3RemoteCredentialSchema,
    run_credential: V3RemoteCredentialSchema,
    runner_instance_id: UuidSchema,
    idempotency_key: Type.String({ minLength: 1, maxLength: 255 }),
  },
  { additionalProperties: false },
);

export const V3RemoteAttachmentSchema = Type.Object(
  {
    id: UuidSchema,
    originalName: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.String({ minLength: 1, maxLength: 255 }),
    sizeBytes: Type.Integer({ minimum: 1, maximum: 50 * 1024 * 1024 }),
    sha256: Sha256Schema,
  },
  { additionalProperties: false },
);
export type V3RemoteAttachment = Static<typeof V3RemoteAttachmentSchema>;

export const V3RemoteConversationSnapshotSchema = Type.Object(
  {
    conversation: Type.Object(
      {
        id: UuidSchema,
        kind: Type.Union([Type.Literal('direct_conversation'), Type.Literal('group_conversation')]),
        title: Type.String({ maxLength: 255 }),
      },
      { additionalProperties: false },
    ),
    execution: Type.Object(
      {
        prompt: Type.String({ maxLength: 500_000 }),
        system_prompt: Type.String({ minLength: 1, maxLength: 500_000 }),
        model: Type.String({ minLength: 1, maxLength: 255 }),
        response_language: Type.Optional(Type.Union([Type.Literal('en'), Type.Literal('zh-CN')])),
        permission_policies: Type.Optional(Type.Array(V3PermissionPolicyVersionSchema)),
        attachments: Type.Optional(Type.Array(V3RemoteAttachmentSchema, { maxItems: 20 })),
        plugin_resources_available: Type.Optional(Type.Boolean()),
        knowledge_tools_available: Type.Optional(Type.Boolean()),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
export type V3RemoteConversationSnapshot = Static<typeof V3RemoteConversationSnapshotSchema>;

export const V3RemoteToolApprovalInputSchema = Type.Object(
  {
    ...V3RemoteConversationLeaseSchema.properties,
    command: Type.String({ minLength: 1, maxLength: 100_000 }),
    target: Type.String({ minLength: 1, maxLength: 32_768 }),
    risk: Type.Union([Type.Literal('read'), Type.Literal('write'), Type.Literal('execute')]),
    request_hash: Type.String({ pattern: '^[a-f0-9]{64}$' }),
    policy_versions: Type.Array(Type.Object({ id: UuidSchema, version: Type.Integer({ minimum: 1 }) }), {
      minItems: 1,
    }),
  },
  { additionalProperties: false },
);

export const V3RemoteToolApprovalStatusInputSchema = Type.Object(
  {
    ...V3RemoteConversationLeaseSchema.properties,
    approval_id: UuidSchema,
  },
  { additionalProperties: false },
);

export const V3DesktopMachineSchema = Type.Object(
  {
    id: UuidSchema,
    deviceName: Type.String({ minLength: 1, maxLength: 255 }),
    clientVersion: Type.String({ minLength: 1, maxLength: 100 }),
    platform: Type.Union([Type.Literal('win32'), Type.Literal('darwin'), Type.Literal('linux')]),
    architecture: Type.String({ minLength: 1, maxLength: 32 }),
    registeredAt: DateTimeSchema,
    lastSeenAt: DateTimeSchema,
    lastPollAt: NullableDateTimeSchema,
    pollCount: Type.Integer({ minimum: 0, maximum: Number.MAX_SAFE_INTEGER }),
    version: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
  },
  { additionalProperties: false },
);
export type V3DesktopMachine = Static<typeof V3DesktopMachineSchema>;

export const V3DesktopMachineInventorySchema = Type.Object(
  {
    items: Type.Array(
      Type.Object(
        {
          ...V3DesktopMachineSchema.properties,
          wakerCount: Type.Integer({ minimum: 0 }),
          online: Type.Boolean(),
        },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);
export type V3DesktopMachineInventory = Static<typeof V3DesktopMachineInventorySchema>;

const V3NetworkDiagnosticStatusSchema = Type.Union([Type.Literal('reachable'), Type.Literal('unavailable')]);
const networkDiagnosticCheck = (id: 'gateway' | 'registration' | 'work-return') =>
  Type.Object(
    {
      id: Type.Literal(id),
      status: V3NetworkDiagnosticStatusSchema,
      durationMs: Type.Optional(Type.Integer({ minimum: 0, maximum: 650_000 })),
      details: Type.Array(Type.String({ minLength: 1, maxLength: 2_000 }), {
        maxItems: 20,
      }),
    },
    { additionalProperties: false },
  );

export const V3NetworkDiagnosticsSchema = Type.Object(
  {
    machineId: NullableUuidSchema,
    machine: Type.Union([V3DesktopMachineSchema, Type.Null()]),
    checkedAt: DateTimeSchema,
    checks: Type.Tuple([
      networkDiagnosticCheck('gateway'),
      networkDiagnosticCheck('registration'),
      networkDiagnosticCheck('work-return'),
    ]),
  },
  { additionalProperties: false },
);
export type V3NetworkDiagnostics = Static<typeof V3NetworkDiagnosticsSchema>;

/** TypeBox coverage for the named component schemas in the V3 OpenAPI contract. */
export const V3_OPENAPI_SCHEMA_COVERAGE = {
  Approval: V3ApprovalSchema,
  ApprovalWorkItem: V3ApprovalWorkItemSchema,
  AiGatewayVirtualKeyClaimResponse: V3AiGatewayVirtualKeyClaimResponseSchema,
  AiGatewayVirtualKeyInput: V3AiGatewayVirtualKeyInputSchema,
  AiGatewayVirtualKeyStatus: V3AiGatewayVirtualKeyStatusSchema,
  Automation: V3AutomationSchema,
  AutomationDefinition: V3AutomationDefinitionSchema,
  AutomationDispatchInput: V3AutomationDispatchInputSchema,
  AutomationDispatchResult: V3AutomationDispatchResultSchema,
  AutomationInvocation: V3AutomationInvocationSchema,
  AutomationLifecycleInput: V3AutomationLifecycleInputSchema,
  AutomationScheduleTrigger: V3AutomationScheduleTriggerSchema,
  AutomationTrigger: V3AutomationTriggerSchema,
  AutomationTriggerId: V3AutomationTriggerIdSchema,
  AutomationVersion: V3AutomationVersionSchema,
  AvatarObject: V3AvatarObjectSchema,
  Bootstrap: V3BootstrapSchema,
  Conversation: V3ConversationSchema,
  ConversationAttachment: V3ConversationAttachmentSchema,
  CreateAutomation: V3CreateAutomationSchema,
  CreateExport: V3CreateExportSchema,
  CreateGroup: V3CreateGroupSchema,
  GroupSkill: V3GroupSkillSchema,
  InstallGroupSkills: V3InstallGroupSkillsSchema,
  RemoveGroupSkill: V3RemoveGroupSkillSchema,
  CreateImChannel: V3CreateImChannelSchema,
  CreateImPairing: V3CreateImPairingSchema,
  CreateManualImPairing: V3CreateManualImPairingSchema,
  CreateKnowledgeBase: V3CreateKnowledgeBaseSchema,
  CreateKnowledgeSchedule: V3CreateKnowledgeScheduleSchema,
  CreateKnowledgeUrlMaterial: V3CreateKnowledgeUrlMaterialSchema,
  CreateConnector: V3CreateConnectorSchema,
  CreateWakerConnector: V3CreateWakerConnectorSchema,
  CreateRoleTemplate: V3CreateRoleTemplateSchema,
  UpdateRoleTemplate: V3UpdateRoleTemplateSchema,
  RoleSkillVersion: V3RoleSkillVersionSchema,
  GenerateRoleDocumentsInput: V3GenerateRoleDocumentsInputSchema,
  RoleDocuments: V3RoleDocumentsSchema,
  CreateWaker: V3CreateWakerSchema,
  CreateWorkflow: V3CreateWorkflowSchema,
  Event: V3EventSchema,
  EventPage: V3EventPageSchema,
  ExportJob: V3ExportJobSchema,
  ImChannel: V3ImChannelSchema,
  ImChannelDiagnostic: V3ImChannelDiagnosticSchema,
  ImChannelLifecycleInput: V3ImChannelLifecycleInputSchema,
  ImQrAuthPollInput: V3ImQrAuthPollInputSchema,
  ImQrAuthPollResult: V3ImQrAuthPollResultSchema,
  ImQrAuthSession: V3ImQrAuthSessionSchema,
  ImQrAuthStartInput: V3ImQrAuthStartInputSchema,
  ImConversation: V3ImConversationSchema,
  ImPairingLifecycleInput: V3ImPairingLifecycleInputSchema,
  ImPairingRequest: V3ImPairingRequestSchema,
  KnowledgeBase: V3KnowledgeBaseSchema,
  KnowledgeFolder: V3KnowledgeFolderSchema,
  KnowledgeBinding: V3KnowledgeBindingSchema,
  KnowledgeBindingInput: V3KnowledgeBindingInputSchema,
  KnowledgeMaterial: V3KnowledgeMaterialSchema,
  KnowledgeMaterialContent: V3KnowledgeMaterialContentSchema,
  KnowledgeCard: V3KnowledgeCardSchema,
  KnowledgeCollaborator: V3KnowledgeCollaboratorSchema,
  KnowledgeSchedule: V3KnowledgeScheduleSchema,
  KnowledgeScheduleRun: V3KnowledgeScheduleRunSchema,
  KnowledgeSettings: V3KnowledgeSettingsSchema,
  InviteKnowledgeCollaborator: V3InviteKnowledgeCollaboratorSchema,
  CompileKnowledgeBase: V3CompileKnowledgeBaseSchema,
  CreateKnowledgeFolder: V3CreateKnowledgeFolderSchema,
  RenameKnowledgeFolder: V3RenameKnowledgeFolderSchema,
  RenameKnowledgeMaterial: V3RenameKnowledgeMaterialSchema,
  DeleteKnowledgeSelection: V3DeleteKnowledgeSelectionSchema,
  RenameKnowledgeBase: V3RenameKnowledgeBaseSchema,
  UpdateKnowledgeSchedule: V3UpdateKnowledgeScheduleSchema,
  UpdateKnowledgeSettings: V3UpdateKnowledgeSettingsSchema,
  Connector: V3ConnectorSchema,
  UpdateConnector: V3UpdateConnectorSchema,
  ConnectorDiagnostic: V3ConnectorDiagnosticSchema,
  ConnectorLifecycleInput: V3ConnectorLifecycleInputSchema,
  ConnectorToolSelectionInput: V3ConnectorToolSelectionInputSchema,
  Problem: V3ProblemSchema,
  PermissionPolicyVersion: V3PermissionPolicyVersionSchema,
  RestoreWakerDocument: V3RestoreWakerDocumentSchema,
  ResolveImPairingRequest: V3ResolveImPairingRequestSchema,
  UpdateImPairing: V3UpdateImPairingSchema,
  SkillInstallation: V3SkillInstallationSchema,
  SkillMarketplaceDetail: V3SkillMarketplaceDetailSchema,
  SkillMarketplaceItem: V3SkillMarketplaceItemSchema,
  SkillMarketplacePage: V3SkillMarketplacePageSchema,
  SkillVersion: V3SkillVersionSchema,
  SkillComparison: V3SkillComparisonSchema,
  SkillLifecycleInput: V3SkillLifecycleInputSchema,
  Run: V3RunSchema,
  RoleTemplate: V3RoleTemplateSchema,
  Task: V3TaskSchema,
  RenameTask: V3RenameTaskSchema,
  HideTask: V3HideTaskSchema,
  PinTask: V3PinTaskSchema,
  TaskPage: V3TaskPageSchema,
  TaskStateCounts: V3TaskStateCountsSchema,
  UpdateAutomation: V3UpdateAutomationSchema,
  UpdateImChannel: V3UpdateImChannelSchema,
  UpdateWorkflow: V3UpdateWorkflowSchema,
  UpdateWorkflowTriggers: V3UpdateWorkflowTriggersSchema,
  UpdateWakerDocument: V3UpdateWakerDocumentSchema,
  UpdatePermissionPolicy: V3UpdatePermissionPolicySchema,
  WakerBuiltinCapabilities: V3WakerBuiltinCapabilitiesSchema,
  Waker: V3WakerSchema,
  WakerConfigurationVersion: V3WakerConfigurationVersionSchema,
  WakerDocumentComparison: V3DocumentComparisonSchema,
  WakerDocumentVersion: V3WakerDocumentVersionSchema,
  WakerEffectiveSnapshot: V3WakerEffectiveSnapshotSchema,
  Workflow: V3WorkflowSchema,
  WorkflowInputField: V3WorkflowInputFieldSchema,
  WorkflowLifecycleInput: V3WorkflowLifecycleInputSchema,
  WorkflowNode: V3WorkflowNodeSchema,
  WorkflowNodeExecution: V3WorkflowNodeExecutionSchema,
  WorkflowResolveInput: V3ResolveWorkflowInputSchema,
  WorkflowRollbackInput: V3WorkflowRollbackInputSchema,
  WorkflowRun: V3WorkflowRunSchema,
  WorkflowRunEvent: V3WorkflowRunEventSchema,
  WorkflowRunInput: V3WorkflowRunInputSchema,
  WorkflowTriggerConfiguration: V3WorkflowTriggerConfigurationSchema,
  CreateWorkflowAutomation: V3CreateWorkflowAutomationSchema,
  UpdateWorkflowAutomation: V3UpdateWorkflowAutomationSchema,
  DeleteWorkflowAutomation: V3DeleteWorkflowAutomationSchema,
  WorkflowAutomation: V3WorkflowAutomationSchema,
  WorkflowAutomationDispatchInput: V3WorkflowAutomationDispatchInputSchema,
  WorkflowTriggerDispatchInput: V3WorkflowTriggerDispatchInputSchema,
  WorkflowVersion: V3WorkflowVersionSchema,
  CreateProject: V3CreateProjectSchema,
  DesktopMachine: V3DesktopMachineSchema,
  DesktopMachineRegistrationInput: V3DesktopMachineRegistrationInputSchema,
  NetworkDiagnostics: V3NetworkDiagnosticsSchema,
  Project: V3ProjectSchema,
  ProjectPreparation: V3ProjectPreparationSchema,
  ProjectSource: V3ProjectSourceSchema,
  ProjectSourceInput: V3ProjectSourceInputSchema,
  UpdateProject: V3UpdateProjectSchema,
  WorkspaceReference: V3WorkspaceReferenceSchema,
} as const;
