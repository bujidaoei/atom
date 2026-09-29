import { Type, type Static } from 'typebox';
import { V3ConnectorDiagnosticSchema } from './v3.ts';

const id = Type.String({
  pattern: '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
});
const key = Type.String({ minLength: 1, maxLength: 200 });
export const InstallMarketPluginRequestSchema = Type.Object(
  {
    wakerId: id,
    marketId: Type.String({ pattern: '^[A-Za-z0-9_-]{3,120}$' }),
    expectedConfigurationVersionId: id,
    idempotencyKey: key,
  },
  { additionalProperties: false },
);
export type InstallMarketPluginRequest = Static<typeof InstallMarketPluginRequestSchema>;

export const SetPluginEnabledRequestSchema = Type.Object(
  {
    installationId: id,
    enabled: Type.Boolean(),
    expectedRevisionId: id,
    expectedConfigurationVersionId: id,
    idempotencyKey: key,
  },
  { additionalProperties: false },
);
export type SetPluginEnabledRequest = Static<typeof SetPluginEnabledRequestSchema>;

export const UninstallPluginRequestSchema = Type.Object(
  {
    installationId: id,
    expectedRevisionId: id,
    expectedConfigurationVersionId: id,
    idempotencyKey: key,
  },
  { additionalProperties: false },
);
export type UninstallPluginRequest = Static<typeof UninstallPluginRequestSchema>;
export type RetryPluginRequest = UninstallPluginRequest;

export const PluginInstallationRevisionSchema = Type.Object(
  {
    id,
    installationId: id,
    wakerId: id,
    packageId: id,
    number: Type.Integer({ minimum: 1 }),
    enabled: Type.Boolean(),
    ready: Type.Boolean(),
    pendingPhase: Type.Union([Type.Literal('connectors'), Type.Null()]),
  },
  { additionalProperties: false },
);
export type PluginInstallationRevision = Static<typeof PluginInstallationRevisionSchema>;

export const PluginPresentationSchema = Type.Object(
  {
    displayName: Type.String({ minLength: 1, maxLength: 160 }),
    localizedName: Type.Union([Type.String({ maxLength: 160 }), Type.Null()]),
    description: Type.String({ maxLength: 20000 }),
    localizedDescription: Type.Union([Type.String({ maxLength: 20000 }), Type.Null()]),
    author: Type.String({ maxLength: 200 }),
    iconUrl: Type.Union([Type.String({ maxLength: 2000 }), Type.Null()]),
  },
  { additionalProperties: false },
);
export type PluginPresentation = Static<typeof PluginPresentationSchema>;

export const InstalledPluginSchema = Type.Object(
  {
    resourceId: id,
    marketId: Type.String({ minLength: 1 }),
    canonicalId: Type.String({ minLength: 1 }),
    pluginName: Type.String({ minLength: 1 }),
    displayName: Type.String({ minLength: 1 }),
    version: Type.String({ minLength: 1 }),
    source: Type.Union([Type.Literal('marketplace'), Type.Literal('custom')]),
    presentation: Type.Union([PluginPresentationSchema, Type.Null()]),
    installations: Type.Array(PluginInstallationRevisionSchema),
    connectorChecks: Type.Array(
      Type.Object(
        {
          installationId: id,
          connectorId: id,
          serverName: Type.String({ minLength: 1, maxLength: 160 }),
          status: V3ConnectorDiagnosticSchema.properties.status,
          checkedAt: V3ConnectorDiagnosticSchema.properties.checkedAt,
        },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);
export const InstalledPluginsSchema = Type.Array(InstalledPluginSchema);
export type InstalledPlugin = Static<typeof InstalledPluginSchema>;

export const PluginCatalogInputSchema = Type.Object(
  {
    page: Type.Integer({ minimum: 1 }),
    pageSize: Type.Integer({ minimum: 1, maximum: 20 }),
    category: Type.Optional(Type.String({ maxLength: 120 })),
    keyword: Type.Optional(Type.String({ maxLength: 200 })),
    featured: Type.Optional(Type.Boolean()),
  },
  { additionalProperties: false },
);
export type PluginCatalogInput = Static<typeof PluginCatalogInputSchema>;
export const PluginCatalogPageSchema = Type.Object(
  {
    items: Type.Array(
      Type.Object(
        {
          marketId: Type.String({ minLength: 1 }),
          pluginName: Type.String({ minLength: 1 }),
          presentation: PluginPresentationSchema,
          category: Type.String(),
          installCount: Type.Integer({ minimum: 0 }),
          recommended: Type.Boolean(),
        },
        { additionalProperties: false },
      ),
    ),
    categories: Type.Array(
      Type.Object(
        { code: Type.String(), label: Type.String(), count: Type.Integer({ minimum: 0 }) },
        { additionalProperties: false },
      ),
    ),
    page: Type.Integer({ minimum: 1 }),
    pageSize: Type.Integer({ minimum: 1, maximum: 20 }),
    total: Type.Integer({ minimum: 0 }),
    lastPage: Type.Integer({ minimum: 1 }),
  },
  { additionalProperties: false },
);
export type PluginCatalogPage = Static<typeof PluginCatalogPageSchema>;

const PluginConstituentSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 160 }),
    description: Type.String({ maxLength: 20_000 }),
    markdown: Type.Optional(Type.String({ maxLength: 100_000 })),
  },
  { additionalProperties: false },
);
export const PluginMarketCompositionSchema = Type.Object(
  {
    version: Type.Union([Type.String({ minLength: 1, maxLength: 80 }), Type.Null()]),
    category: Type.String({ maxLength: 120 }),
    installCount: Type.Union([Type.Integer({ minimum: 0 }), Type.Null()]),
    skills: Type.Array(PluginConstituentSchema, { maxItems: 100 }),
    commands: Type.Array(PluginConstituentSchema, { maxItems: 100 }),
    connectors: Type.Array(PluginConstituentSchema, { maxItems: 100 }),
    readme: Type.Union([Type.String({ maxLength: 100_000 }), Type.Null()]),
  },
  { additionalProperties: false },
);
export type PluginMarketComposition = Static<typeof PluginMarketCompositionSchema>;
