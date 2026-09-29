import { describe, expect, it } from 'vitest';

import { parseCredentialFreeMcpConfigs } from '../src/waker-creation-mcp.ts';

const config = (server: unknown, name = 'example') => JSON.stringify({ mcpServers: { [name]: server } });

describe('credential-free MCP creation parser', () => {
  it('parses stdio and supported HTTP transport aliases without coercing values', () => {
    expect(
      parseCredentialFreeMcpConfigs([
        config({ command: 'npx', args: ['-y', '@example/server'], env: {}, timeout: 30 }),
        config({ url: 'https://example.test/events', type: 'sse' }, 'events'),
        config({ url: 'https://example.test/mcp', transport: 'streamable-http' }, 'http'),
        config({ url: 'https://example.test/mcp-underscore', type: 'streamable_http' }, 'http-underscore'),
      ]),
    ).toEqual([
      {
        name: 'example',
        transport: 'stdio',
        command: 'npx',
        arguments: ['-y', '@example/server'],
        timeoutSeconds: 30,
      },
      { name: 'events', transport: 'sse', url: 'https://example.test/events', timeoutSeconds: 60 },
      { name: 'http', transport: 'streamable_http', url: 'https://example.test/mcp', timeoutSeconds: 60 },
      {
        name: 'http-underscore',
        transport: 'streamable_http',
        url: 'https://example.test/mcp-underscore',
        timeoutSeconds: 60,
      },
    ]);
  });

  it('accepts blank optional credential fields', () => {
    const drafts = parseCredentialFreeMcpConfigs([
      config({
        command: 'node',
        args: [],
        env: {},
        headers: {},
        headersHelper: 'Describe how the dynamic header is generated',
      }),
    ]);
    expect(drafts[0]).toMatchObject({
      command: 'node',
      headersHelper: 'Describe how the dynamic header is generated',
    });
  });

  it.each([
    ['root', '{}'],
    ['empty config', JSON.stringify({ mcpServers: {} })],
    ['invalid server', config(null)],
    ['missing command or url', config({})],
    ['both command and url', config({ command: 'node', url: 'https://example.test/mcp' })],
    ['invalid args', config({ command: 'node', args: ['ok', 3] })],
    ['invalid timeout', config({ command: 'node', timeout: '60' })],
    ['invalid transport', config({ url: 'https://example.test/mcp', type: 'websocket' })],
    ['empty transport', config({ url: 'https://example.test/mcp', type: '' })],
    ['invalid URL', config({ url: 'file:///tmp/mcp' })],
    ['URL userinfo', config({ url: 'https://user:pass@example.test/mcp' })],
    ['URL credential query', config({ url: 'https://example.test/mcp?api_key=secret' })],
    ['environment credentials', config({ command: 'node', env: { TOKEN: 'secret' } })],
    [
      'header credentials',
      config({ url: 'https://example.test/mcp', headers: { Authorization: 'Bearer secret' } }),
    ],
    ['OAuth', config({ url: 'https://example.test/mcp', authType: 'oauth' })],
    ['unknown field', config({ url: 'https://example.test/mcp', selectedTools: ['tool'] })],
    ['HTTP args', config({ url: 'https://example.test/mcp', args: ['ignored'] })],
  ])('rejects %s before returning drafts', (_label, value) => {
    expect(() => parseCredentialFreeMcpConfigs([value])).toThrow();
  });

  it('rejects non-array, blank, malformed, and non-object roots', () => {
    expect(() => parseCredentialFreeMcpConfigs({})).toThrow(/array/u);
    expect(() => parseCredentialFreeMcpConfigs([''])).toThrow(/non-empty/u);
    expect(() => parseCredentialFreeMcpConfigs(['not-json'])).toThrow(/valid JSON/u);
    expect(() => parseCredentialFreeMcpConfigs(['[]'])).toThrow(/root/u);
  });

  it('rejects duplicate server names across imported documents', () => {
    expect(() =>
      parseCredentialFreeMcpConfigs([
        config({ url: 'https://one.example/mcp' }),
        config({ url: 'https://two.example/mcp' }),
      ]),
    ).toThrow(/Duplicate MCP server/u);
  });
});
