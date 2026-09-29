import { Type, type Static } from 'typebox';
import { PluginPresentationSchema } from './v5-plugins.ts';

export const ConnectorCatalogInputSchema = Type.Object(
  {
    page: Type.Integer({ minimum: 1 }),
    pageSize: Type.Integer({ minimum: 1, maximum: 20 }),
    category: Type.Optional(Type.String({ maxLength: 120 })),
    keyword: Type.Optional(Type.String({ maxLength: 200 })),
  },
  { additionalProperties: false },
);
export type ConnectorCatalogInput = Static<typeof ConnectorCatalogInputSchema>;

export const ConnectorCatalogPageSchema = Type.Object(
  {
    items: Type.Array(
      Type.Object(
        {
          marketId: Type.String({ minLength: 1 }),
          connectorName: Type.String({ minLength: 1 }),
          presentation: PluginPresentationSchema,
          category: Type.String(),
          installCount: Type.Integer({ minimum: 0 }),
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
export type ConnectorCatalogPage = Static<typeof ConnectorCatalogPageSchema>;

export const ConnectorMarketServerSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 160 }),
    url: Type.Union([Type.String({ format: 'uri', maxLength: 2000 }), Type.Null()]),
    protocol: Type.Union([Type.Literal('stdio'), Type.Literal('sse'), Type.Literal('streamable_http')]),
    authType: Type.String({ maxLength: 40 }),
    enabled: Type.Boolean(),
  },
  { additionalProperties: false },
);
export type ConnectorMarketServer = Static<typeof ConnectorMarketServerSchema>;

export const ConnectorMarketDetailSchema = Type.Object(
  {
    marketId: Type.String({ minLength: 1 }),
    connectorName: Type.String({ minLength: 1 }),
    presentation: PluginPresentationSchema,
    category: Type.String({ maxLength: 120 }),
    version: Type.String({ maxLength: 80 }),
    servers: Type.Array(ConnectorMarketServerSchema, { maxItems: 20 }),
  },
  { additionalProperties: false },
);
export type ConnectorMarketDetail = Static<typeof ConnectorMarketDetailSchema>;
