import { join } from 'node:path';
import { Value } from 'typebox/value';
import { materializeBoundPlugins } from '../../data-access/src/v3/plugin-package.ts';
import { materializeV3BoundSkills } from '../../data-access/src/v3/skill-context.ts';
import {
  RemotePluginResourcesSchema,
  type RemotePluginResources,
} from '../../product-contracts/src/remote-plugin-resources.ts';
import type { V3RequestContext } from '../../product-contracts/src/v3-ports.ts';
import { loadV3BoundConnectorTools } from './v3-mcp-tool-loader.ts';
import { filterToolsByWakerBuiltinCapabilities } from './v3-builtin-capabilities.ts';
import type { ProductSkillDirectory } from './workspace-tools.ts';

/** Portable host projection; native Pi resources/tools remain the only executor.
 * Pi sdk.ts customTools/resourceLoader and existing verified package adapters supply
 * this capability. No Pi source changes or alternative agent loop are necessary.
 */
export async function materializeRemotePluginResources(
  value: unknown,
  input: {
    wakerId: string;
    root: string;
    workspacePath: string;
  },
) {
  if (!Value.Check(RemotePluginResourcesSchema, value) || value.wakerId !== input.wakerId)
    throw new Error('Remote plugin resources are invalid');
  const resources: RemotePluginResources = value;
  const context = {} as V3RequestContext; // All reads below are closed over this authorized payload.
  const byKey = new Map(resources.packages.map((item) => [item.package.objectKey, item]));
  if (byKey.size !== resources.packages.length) throw new Error('Remote plugin package collision');
  const storage = {
    async get(key: string) {
      const item = byKey.get(key);
      if (!item) throw new Error('Remote plugin package is unavailable');
      return new Uint8Array(Buffer.from(item.bytes, 'base64'));
    },
  };
  const repository = {
    async resolveBound() {
      return resources.packages;
    },
    async listConnectorOwners() {
      return resources.owners;
    },
  };
  const revisionIds = resources.packages.map((item) => item.installation.id);
  const root = join(input.root, input.wakerId);
  const skillBytes = new Map<string, string>();
  const skillIds = new Set<string>();
  for (const { record, bytes } of resources.skills) {
    if (skillIds.has(record.versionId)) throw new Error('Remote Skill version collision');
    skillIds.add(record.versionId);
    if (bytes !== null && record.objectKey) {
      if (skillBytes.has(record.objectKey)) throw new Error('Remote Skill package collision');
      skillBytes.set(record.objectKey, bytes);
    }
  }
  const standaloneSkills = await materializeV3BoundSkills(
    { listBoundSkillContent: async () => resources.skills.map((item) => item.record) },
    {
      get: async (key) => {
        const bytes = skillBytes.get(key);
        if (bytes === undefined) throw new Error('Remote Skill package is unavailable');
        return new Uint8Array(Buffer.from(bytes, 'base64'));
      },
    },
    context,
    [...skillIds],
    join(root, 'standalone-skills'),
  );
  const skillDirectories = await materializeBoundPlugins(
    repository,
    storage,
    context,
    input.wakerId,
    revisionIds,
    root,
  );
  const connected = await loadV3BoundConnectorTools(
    {
      async listBoundConnectorConfigurations() {
        return resources.connectors;
      },
    },
    {
      async resolve(reference) {
        if (!Object.hasOwn(resources.secrets, reference))
          throw new Error('Remote connector secret is unavailable');
        return resources.secrets[reference]!;
      },
    },
    context,
    resources.connectors.map((item) => item.versionId),
    {
      allowStdio: true,
      cwd: input.workspacePath,
      plugins: { repository, storage, wakerId: input.wakerId, revisionIds, root },
    },
  );
  const directories: ProductSkillDirectory[] = [...skillDirectories, ...standaloneSkills];
  return {
    systemPrompt: resources.systemPrompt,
    knowledgeEnabled: resources.capabilities.knowledge,
    skillDirectories: directories,
    externalTools: filterToolsByWakerBuiltinCapabilities(connected.tools, resources.capabilities),
    close: connected.close,
  };
}
