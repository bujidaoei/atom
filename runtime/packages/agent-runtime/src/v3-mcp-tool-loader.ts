import type { V3RequestContext, V3SkillConnectorRepository } from '../../product-contracts/src/v3-ports.ts';
import type { SqlitePluginRegistryRepository } from '../../data-access/src/v3/plugin-registry-repository.ts';
import type { ToolDefinition } from './pi-runtime-types.ts';
import { connectV3McpConnector, type V3McpConnection, type V3McpToolSet } from './v3-mcp-connector.ts';
import { connectVerifiedPluginMcp } from './plugin-mcp-runtime.ts';

export async function loadV3BoundConnectorTools(
  repository: Pick<V3SkillConnectorRepository, 'listBoundConnectorConfigurations'>,
  secrets: { resolve(reference: string): Promise<string> },
  context: V3RequestContext,
  versionIds: readonly string[],
  options: {
    allowStdio: boolean;
    cwd?: string;
    plugins?: {
      repository: Pick<SqlitePluginRegistryRepository, 'resolveBound' | 'listConnectorOwners'>;
      storage: { get(objectKey: string): Promise<Uint8Array> };
      wakerId: string;
      revisionIds: readonly string[];
      root: string;
    };
  },
): Promise<V3McpToolSet> {
  if (!versionIds.length) return { tools: [], async close() {} };
  const records = await repository.listBoundConnectorConfigurations(context, versionIds);
  const pluginRuntime = options.plugins;
  const owners = pluginRuntime
    ? await pluginRuntime.repository.listConnectorOwners(
        context,
        records.map((record) => record.connectorId),
      )
    : [];
  // Uninstall archives connectors and removes ownership in one transaction. Read
  // bindings again after ownership so that concurrent removal cannot downgrade
  // a previously loaded plugin connector into an ordinary workspace command.
  const activeRecords = pluginRuntime
    ? await repository.listBoundConnectorConfigurations(context, versionIds)
    : records;
  const byVersion = new Map(activeRecords.map((record) => [record.versionId, record]));
  const packages =
    pluginRuntime && owners.length
      ? await pluginRuntime.repository.resolveBound(context, pluginRuntime.wakerId, pluginRuntime.revisionIds)
      : [];
  const packageByInstallation = new Map(packages.map((item) => [item.installation.installationId, item]));
  const ownerByConnector = new Map(owners.map((owner) => [owner.connectorId, owner]));
  const connections: V3McpConnection[] = [];
  const tools: ToolDefinition[] = [];
  try {
    for (const versionId of versionIds) {
      const binding = byVersion.get(versionId);
      if (!binding) throw new Error(`Bound Connector version not found: ${versionId}`);
      if (!binding.selectedTools.length) {
        throw new Error(`Bound Connector version has no selected tools: ${versionId}`);
      }
      const resolved = Object.fromEntries(
        await Promise.all(
          Object.entries(binding.secretRefs).map(async ([name, reference]) => [
            name,
            await secrets.resolve(reference),
          ]),
        ),
      );
      const owner = ownerByConnector.get(binding.connectorId);
      let connection: V3McpConnection;
      if (owner) {
        const ownedPackage = packageByInstallation.get(owner.installationId);
        if (!pluginRuntime || owner.wakerId !== pluginRuntime.wakerId || !ownedPackage)
          throw new Error('Plugin connector binding is unavailable');
        connection = await connectVerifiedPluginMcp({
          storage: pluginRuntime.storage,
          package: ownedPackage.package,
          packageId: ownedPackage.installation.packageId,
          root: pluginRuntime.root,
          serverName: owner.serverName,
          binding,
          variables: resolved,
          allowStdio: options.allowStdio,
        });
      } else {
        connection = await connectV3McpConnector(binding, {
          ...(binding.transport === 'stdio' ? { environment: resolved } : { headers: resolved }),
          allowStdio: options.allowStdio,
          ...(options.cwd ? { cwd: options.cwd } : {}),
        });
      }
      connections.push(connection);
      tools.push(...connection.createSelectedTools(binding.selectedTools));
    }
    const names = new Set<string>();
    for (const tool of tools) {
      if (names.has(tool.name)) throw new Error(`Bound MCP tool name collision: ${tool.name}`);
      names.add(tool.name);
    }
    return {
      tools,
      async close() {
        await Promise.allSettled(connections.map((connection) => connection.close()));
      },
    };
  } catch (cause) {
    await Promise.allSettled(connections.map((connection) => connection.close()));
    throw cause;
  }
}
