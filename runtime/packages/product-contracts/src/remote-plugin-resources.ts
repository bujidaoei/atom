import { Type, type Static } from 'typebox';
import { PluginInstallationRevisionSchema } from './v5-plugins.ts';
import { V3WakerBuiltinCapabilitiesSchema } from './v3.ts';

const id = PluginInstallationRevisionSchema.properties.id;
const text = Type.String({ maxLength: 2000 });
const strings = Type.Record(Type.String(), Type.String({ maxLength: 65536 }), { maxProperties: 100 });
/** Private, lease-authorized host payload. Never persist resolved connector secrets. */
export const RemotePluginResourcesSchema = Type.Object(
  {
    wakerId: id,
    systemPrompt: Type.String({ maxLength: 4 * 1024 * 1024 }),
    capabilities: V3WakerBuiltinCapabilitiesSchema,
    skills: Type.Array(
      Type.Object(
        {
          record: Type.Object(
            {
              versionId: id,
              name: text,
              markdown: Type.String({ maxLength: 4 * 1024 * 1024 }),
              contentSha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
              source: Type.Union([Type.Literal('markdown'), Type.Literal('archive')]),
              packageSha256: Type.Union([Type.String({ pattern: '^[a-f0-9]{64}$' }), Type.Null()]),
              inventory: Type.Array(text, { maxItems: 10000 }),
              builtinPackageId: Type.Union([text, Type.Null()]),
              fileName: text,
              objectKey: Type.Union([text, Type.Null()]),
              sizeBytes: Type.Integer({ minimum: 0, maximum: 16 * 1024 * 1024 }),
              mediaType: text,
            },
            { additionalProperties: false },
          ),
          bytes: Type.Union([
            Type.String({ maxLength: 32 * 1024 * 1024, pattern: '^[A-Za-z0-9+/]*={0,2}$' }),
            Type.Null(),
          ]),
        },
        { additionalProperties: false },
      ),
      { maxItems: 100 },
    ),
    packages: Type.Array(
      Type.Object(
        {
          installation: PluginInstallationRevisionSchema,
          package: Type.Object(
            {
              marketId: text,
              canonicalId: text,
              pluginName: text,
              displayName: text,
              version: text,
              objectKey: text,
              sha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
              inventory: Type.Array(text, { maxItems: 10000 }),
            },
            { additionalProperties: false },
          ),
          bytes: Type.String({ maxLength: 32 * 1024 * 1024, pattern: '^[A-Za-z0-9+/]*={0,2}$' }),
        },
        { additionalProperties: false },
      ),
      { maxItems: 100 },
    ),
    connectors: Type.Array(
      Type.Object(
        {
          versionId: id,
          connectorId: id,
          name: text,
          transport: Type.Union([
            Type.Literal('stdio'),
            Type.Literal('sse'),
            Type.Literal('streamable_http'),
          ]),
          command: Type.Union([text, Type.Null()]),
          arguments: Type.Array(text, { maxItems: 100 }),
          url: Type.Union([text, Type.Null()]),
          timeoutSeconds: Type.Integer({ minimum: 1, maximum: 600 }),
          selectedTools: Type.Array(text, { maxItems: 1000 }),
          secretRefs: strings,
        },
        { additionalProperties: false },
      ),
      { maxItems: 100 },
    ),
    owners: Type.Array(
      Type.Object(
        {
          installationId: id,
          connectorId: id,
          serverName: text,
          wakerId: id,
        },
        { additionalProperties: false },
      ),
      { maxItems: 100 },
    ),
    secrets: strings,
  },
  { additionalProperties: false },
);
export type RemotePluginResources = Static<typeof RemotePluginResourcesSchema>;
export const REMOTE_PLUGIN_RESOURCE_MAX_BYTES = 32 * 1024 * 1024;
