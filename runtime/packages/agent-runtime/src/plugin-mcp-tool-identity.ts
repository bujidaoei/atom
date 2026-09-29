import type { ToolDefinition } from './pi-runtime-types.ts';

interface PluginMcpToolIdentity {
  pluginName: string;
  serverName: string;
  toolName: string;
}

// Internal provenance only. Nothing is accepted from a package's tool schema or
// description; records are attached after verified package/connector resolution.
// Weak keys avoid extending connection/tool lifetimes or sending metadata to Pi.
const identities = new WeakMap<ToolDefinition, Readonly<PluginMcpToolIdentity>>();

export function identifyVerifiedPluginMcpTool(tool: ToolDefinition, identity: PluginMcpToolIdentity): void {
  identities.set(tool, Object.freeze({ ...identity }));
}

export function verifiedPluginMcpToolNames(tool: ToolDefinition, agentPluginName?: string): string[] {
  const identity = identities.get(tool);
  if (!identity) return [];
  const { pluginName, serverName, toolName } = identity;
  return [
    `mcp__plugin_${pluginName}_${serverName}__${toolName}`,
    // Legacy package-local server selectors must not match a same-named server
    // from another plugin or a manually configured Connector.
    ...(agentPluginName === pluginName ? [`mcp__${serverName}__${toolName}`] : []),
  ];
}
