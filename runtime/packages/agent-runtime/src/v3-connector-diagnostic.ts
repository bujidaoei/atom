import { redactConnectorDiagnostic } from '../../product-contracts/src/provider-correlation.ts';
import type { V3ConnectorDiagnostic } from '../../product-contracts/src/v3.ts';
import type { V3McpConnection } from './v3-mcp-connector.ts';

export function readyV3ConnectorDiagnostic(
  connection: Pick<V3McpConnection, 'era' | 'serverName' | 'discoveredTools'>,
  checkedAt: string,
): V3ConnectorDiagnostic {
  return redactConnectorDiagnostic({
    status: 'ready',
    message: `${connection.serverName} connected using MCP ${connection.era}; ${connection.discoveredTools.length} tools discovered.`,
    tools: connection.discoveredTools,
    checkedAt,
  });
}

export function failedV3ConnectorDiagnostic(cause: unknown, checkedAt: string): V3ConnectorDiagnostic {
  return redactConnectorDiagnostic({
    status: 'degraded',
    message: cause instanceof Error ? cause.message : 'MCP diagnostic failed.',
    tools: [],
    checkedAt,
  });
}
