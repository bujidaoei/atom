import { mkdir } from 'node:fs/promises';
import type { V3RequestContext, V3SkillConnectorRepository } from '../../product-contracts/src/v3-ports.ts';
import type { SqlitePluginRegistryRepository } from '../../data-access/src/v3/plugin-registry-repository.ts';
import { connectVerifiedPluginMcp } from './plugin-mcp-runtime.ts';
import { connectV3McpConnector } from './v3-mcp-connector.ts';

/** Management-time connection; pending installations may be diagnosed before task binding. */
export async function connectManagedV3McpConnector(
  context: V3RequestContext,
  connectorId: string,
  options: {
    resources: Pick<V3SkillConnectorRepository, 'getConnector' | 'getConnectorSecretRefs'>;
    plugins: Pick<SqlitePluginRegistryRepository, 'list' | 'listConnectorOwners'>;
    storage: { get(key: string): Promise<Uint8Array> };
    secrets: { resolve(reference: string): Promise<string> };
    pluginRoot: string;
    cwd?: string;
    allowStdio: boolean;
  },
) {
  const owners = await options.plugins.listConnectorOwners(context, [connectorId]);
  // Resolve the active record after ownership, preventing an uninstall from
  // turning an archived plugin connector into a generic command fallback.
  const connector = await options.resources.getConnector(context, connectorId);
  if (!connector) throw new Error('Connector not found');
  const owner = owners.find((value) => value.connectorId === connectorId);
  const binding = {
    versionId: connector.currentVersionId,
    connectorId: connector.id,
    selectedTools: connector.selectedTools,
  };
  const refs = await options.resources.getConnectorSecretRefs(context, connectorId);
  const variables = Object.fromEntries(
    await Promise.all(
      Object.entries(refs).map(async ([name, reference]) => [name, await options.secrets.resolve(reference)]),
    ),
  );
  if (owner) {
    const rows = await options.plugins.list(context);
    const row = rows.find((value) =>
      value.installations.some((item) => item.installationId === owner.installationId),
    );
    const installation = row?.installations.find((value) => value.installationId === owner.installationId);
    if (
      !row ||
      !installation ||
      owner.wakerId !== connector.wakerId ||
      installation.wakerId !== connector.wakerId
    )
      throw new Error('Plugin connector binding is unavailable');
    return connectVerifiedPluginMcp({
      storage: options.storage,
      package: row.package,
      packageId: installation.packageId,
      root: options.pluginRoot,
      serverName: owner.serverName,
      binding,
      variables,
      allowStdio: options.allowStdio,
    });
  }
  if (options.cwd) await mkdir(options.cwd, { recursive: true });
  return connectV3McpConnector(
    {
      ...binding,
      name: connector.name,
      transport: connector.transport,
      command: connector.command,
      arguments: connector.arguments,
      url: connector.url,
      timeoutSeconds: connector.timeoutSeconds,
      secretRefs: refs,
    },
    {
      allowStdio: options.allowStdio,
      ...(options.cwd ? { cwd: options.cwd } : {}),
      ...(connector.transport === 'stdio' ? { environment: variables } : { headers: variables }),
    },
  );
}
