import { mkdtemp, mkdir, writeFile, rm, realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { expect, it } from 'vitest';
import { parsePluginMcpDeclarations } from '../../data-access/src/v3/plugin-mcp-declarations.ts';
import { resolvePluginMcpLaunch } from '../src/plugin-mcp-launch.ts';
import { connectV3McpConnector } from '../src/v3-mcp-connector.ts';

const declaration = (fields: Record<string, unknown>) =>
  parsePluginMcpDeclarations(Buffer.from(JSON.stringify({ mcpServers: { fixture: fields } })))[0]!;

it.runIf(process.platform === 'win32')(
  'starts a shipped Windows wrapper under a path containing spaces through the MCP SDK',
  async () => {
    const root = await mkdtemp(join(tmpdir(), 'plugin launch windows '));
    let connection: Awaited<ReturnType<typeof connectV3McpConnector>> | undefined;
    try {
      await mkdir(join(root, 'bin'));
      await writeFile(join(root, 'bin', 'server'), '#!/bin/sh\nexit 1\n');
      const server = join(process.cwd(), 'tests', 'fixtures', 'mcp-stdio-server.mjs');
      await writeFile(
        join(root, 'bin', 'server.cmd'),
        `@echo off\r\n"${process.execPath}" "${server}" %*\r\n`,
      );
      const launch = await resolvePluginMcpLaunch(declaration({ command: './bin/server', cwd: '.' }), root);
      connection = await connectV3McpConnector(
        {
          versionId: 'a1111111-1111-4111-8111-111111111111',
          connectorId: 'a2222222-2222-4222-8222-222222222222',
          name: 'Windows package wrapper',
          transport: 'stdio',
          command: launch.command,
          arguments: launch.arguments,
          url: null,
          timeoutSeconds: 10,
          selectedTools: ['echo'],
          secretRefs: {},
        },
        { allowStdio: true, cwd: launch.cwd, environment: { TEST_TOKEN: 'fixture-only' } },
      );
      const tool = connection.createSelectedTools(['echo'])[0]!;
      const result = await tool.execute(
        'wrapper-proof',
        { text: 'actual-stdio' },
        undefined,
        undefined,
        {} as never,
      );
      expect(result.content).toEqual([{ type: 'text', text: 'echo:actual-stdio;secret:fixture-only' }]);
    } finally {
      await connection?.close();
      await rm(root, { recursive: true, force: true });
    }
  },
);

it('resolves only shipped relative commands and explicit variables at the host', async () => {
  const root = await mkdtemp(join(tmpdir(), 'plugin-launch-'));
  try {
    await mkdir(join(root, 'bin'));
    await writeFile(join(root, 'bin', 'server'), '#!/bin/sh\n');
    await writeFile(join(root, 'bin', 'server.cmd'), '@echo off\r\n');
    const input = declaration({
      command: './bin/server',
      cwd: '.',
      args: ['${PLUGIN_ROOT}/catalog.json'],
      env: { TOKEN: '${TEST_TOKEN}' },
    });
    const resolved = await resolvePluginMcpLaunch(input, root, { TEST_TOKEN: 'explicit-secret' }, 'win32');
    expect(resolved.command).toBe(await realpath(join(root, 'bin', 'server.cmd')));
    expect(resolved.cwd).toBe(await realpath(root));
    expect(resolved.arguments).toEqual([`${await realpath(root)}/catalog.json`]);
    expect(resolved.environment).toEqual({ TOKEN: 'explicit-secret' });
    expect(
      (await resolvePluginMcpLaunch(input, root, { TEST_TOKEN: 'explicit-secret' }, 'linux')).command,
    ).toBe(await realpath(join(root, 'bin', 'server')));
    await expect(resolvePluginMcpLaunch(input, root)).rejects.toThrow(
      'Plugin MCP variable is required: TEST_TOKEN',
    );
    expect(input.command).toBe('./bin/server');
    expect(input.environment.TOKEN).toBe('${TEST_TOKEN}');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it('rejects external cwd and executable substitution; keeps argument text out of shell syntax', async () => {
  const root = await mkdtemp(join(tmpdir(), 'plugin-launch-'));
  try {
    await expect(resolvePluginMcpLaunch(declaration({ command: 'node', cwd: '..' }), root)).rejects.toThrow(
      'escapes its package',
    );
    await expect(
      resolvePluginMcpLaunch(declaration({ command: '${RUNNER}' }), root, { RUNNER: 'node' }),
    ).rejects.toThrow('command cannot contain variables');
    await expect(resolvePluginMcpLaunch(declaration({ command: '../node' }), root)).rejects.toThrow(
      'bare or package-relative',
    );
    const args = ['a b', 'x&y', '$(touch never)', '"quoted"'];
    expect((await resolvePluginMcpLaunch(declaration({ command: 'node', args }), root)).arguments).toEqual(
      args,
    );
    await expect(
      resolvePluginMcpLaunch(declaration({ command: 'node', args: ['${TOKEN:-fallback}'] }), root),
    ).rejects.toThrow('Unsupported plugin MCP variable expression');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
