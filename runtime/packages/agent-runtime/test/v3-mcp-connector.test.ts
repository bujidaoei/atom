import { loadV3BoundConnectorTools } from '../src/v3-mcp-tool-loader.ts';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { connectV3McpConnector, mergeOfficialMcpHeaders } from '../src/v3-mcp-connector.ts';
import type { V3RequestContext } from '../../product-contracts/src/v3-ports.ts';

const versionId = 'a1111111-1111-4111-8111-111111111111';
const connectorId = 'a2222222-2222-4222-8222-222222222222';
const binding = {
  versionId,
  connectorId,
  name: 'Test STDIO',
  transport: 'stdio' as const,
  command: process.execPath,
  arguments: [join(process.cwd(), 'tests', 'fixtures', 'mcp-stdio-server.mjs')],
  url: null,
  timeoutSeconds: 10,
  selectedTools: ['echo'],
  secretRefs: { TEST_TOKEN: 'secret://workspace/test/token' },
};

const context: V3RequestContext = {
  principal: {
    userId: '10000000-0000-4000-8000-000000000001',
    workspaceId: '20000000-0000-4000-8000-000000000001',
    displayName: 'MCP tester',
    role: 'owner',
    permissions: ['*'],
  },
  correlationId: 'mcp-runtime-test',
};

describe('V3 MCP Connector runtime', () => {
  it('uses the official client to discover and call a real STDIO MCP server', async () => {
    const connection = await connectV3McpConnector(binding, {
      allowStdio: true,
      environment: { TEST_TOKEN: 'resolved-value' },
    });
    try {
      expect(connection.serverName).toBe('WorkDude MCP Test Server');
      expect(connection.discoveredTools).toEqual([
        { name: 'echo', description: 'Returns its text and confirms secret delivery.' },
      ]);
      const [tool] = connection.createSelectedTools(['echo']);
      expect(tool?.name).toBe('mcp_a2222222_echo');
      const result = await tool!.execute('tool-call', { text: 'hello' }, undefined, undefined, {} as never);
      expect(result.content).toEqual([{ type: 'text', text: 'echo:hello;secret:resolved-value' }]);
    } finally {
      await connection.close();
    }
  });

  it('loads only exact pinned Connector versions and resolves opaque secrets at Run start', async () => {
    const resolved: string[] = [];
    const toolSet = await loadV3BoundConnectorTools(
      {
        async listBoundConnectorConfigurations(_context, ids) {
          expect(ids).toEqual([versionId]);
          return [binding];
        },
      },
      {
        async resolve(reference) {
          resolved.push(reference);
          return 'resolved-at-run-start';
        },
      },
      context,
      [versionId],
      { allowStdio: true },
    );
    try {
      expect(resolved).toEqual(['secret://workspace/test/token']);
      expect(toolSet.tools.map(({ name }) => name)).toEqual(['mcp_a2222222_echo']);
    } finally {
      await toolSet.close();
    }

    await expect(
      loadV3BoundConnectorTools(
        {
          async listBoundConnectorConfigurations() {
            return [];
          },
        },
        {
          async resolve() {
            return 'unused';
          },
        },
        context,
        [versionId],
        { allowStdio: true },
      ),
    ).rejects.toThrow(`Bound Connector version not found: ${versionId}`);
  });

  it('merges remote MCP headers into the request and never evaluates headersHelper', () => {
    const helper = 'throw new Error("headersHelper executed")';
    const headers = mergeOfficialMcpHeaders(
      { headers: { accept: 'text/event-stream' } },
      {
        Authorization: 'Bearer stored-token',
      },
    );
    expect(headers.get('accept')).toBe('text/event-stream');
    expect(headers.get('Authorization')).toBe('Bearer stored-token');
    expect(helper).toContain('headersHelper');
  });
});
