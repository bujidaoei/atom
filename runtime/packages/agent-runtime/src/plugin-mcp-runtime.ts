import { materializeVerifiedPluginPackage } from '../../data-access/src/v3/plugin-package.ts';
import type { MarketPluginPackage } from '../../data-access/src/v3/plugin-registry-model.ts';
import type { V3BoundConnectorConfiguration } from '../../data-access/src/v3/skill-connector-repository.ts';
import { resolvePluginMcpLaunch } from './plugin-mcp-launch.ts';
import { connectV3McpConnector } from './v3-mcp-connector.ts';
import { identifyVerifiedPluginMcpTool } from './plugin-mcp-tool-identity.ts';

/** Host-side adapter for a registry-authorized package/connector association.
 * Pi 0.86.1 external tools and the existing MCP client own execution/lifecycle.
 * No package path or declaration supplied by a public request is trusted here.
 */
export async function connectVerifiedPluginMcp(input: {
  storage: { get(objectKey: string): Promise<Uint8Array> };
  package: MarketPluginPackage;
  packageId: string;
  root: string;
  serverName: string;
  binding: Pick<V3BoundConnectorConfiguration, 'versionId' | 'connectorId' | 'selectedTools'>;
  variables?: Readonly<Record<string, string>>;
  allowStdio: boolean;
}) {
  const { inspected, directoryPath } = await materializeVerifiedPluginPackage(
    input.storage,
    input.package,
    input.packageId,
    input.root,
  );
  const declaration = inspected.connectors.find(({ name }) => name === input.serverName);
  if (!declaration) throw new Error('Plugin connector declaration is missing');
  if (declaration.disabled) throw new Error('Plugin connector declaration is disabled');
  const launch = await resolvePluginMcpLaunch(declaration, directoryPath, input.variables);
  const connection = await connectV3McpConnector(
    {
      ...input.binding,
      name: declaration.name,
      transport: declaration.transport,
      command: launch.command,
      arguments: launch.arguments,
      url: launch.url,
      timeoutSeconds: declaration.timeoutSeconds,
      secretRefs: {},
    },
    {
      allowStdio: input.allowStdio,
      cwd: launch.cwd,
      // Keep Python's automatic bytecode cache out of the verified package tree.
      environment: { PYTHONDONTWRITEBYTECODE: '1', ...launch.environment },
      headers: launch.headers,
    },
  );
  return {
    ...connection,
    createSelectedTools(selectedTools: readonly string[]) {
      const tools = connection.createSelectedTools(selectedTools);
      tools.forEach((tool, index) =>
        identifyVerifiedPluginMcpTool(tool, {
          pluginName: inspected.package.pluginName,
          serverName: declaration.name,
          toolName: selectedTools[index]!,
        }),
      );
      return tools;
    },
  };
}
