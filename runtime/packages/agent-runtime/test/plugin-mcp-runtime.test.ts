import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { zipSync } from 'fflate';
import { expect, it } from 'vitest';
import { inspectMarketPluginPackage } from '../../data-access/src/v3/plugin-package.ts';
import { connectVerifiedPluginMcp } from '../src/plugin-mcp-runtime.ts';
import { pluginAgentTools } from '../src/plugin-agent-tool.ts';
import { loadV3BoundConnectorTools } from '../src/v3-mcp-tool-loader.ts';
import {
  createV3LocalWakerGroupStore,
  SqliteWakerGroupRepository,
} from '../../data-access/src/v3/sqlite-waker-group-repository.ts';
import { SqliteSkillConnectorRepository } from '../../data-access/src/v3/skill-connector-repository.ts';
import { SqlitePluginRegistryRepository } from '../../data-access/src/v3/plugin-registry-repository.ts';
import { SqliteV3WorkspaceSecretVault } from '../../data-access/src/v3/workspace-secret-vault.ts';
import { canonicalRequestHash } from '../../data-access/src/v3/repository-core.ts';
import { connectManagedV3McpConnector } from '../src/v3-managed-mcp-connector.ts';
import { readyV3ConnectorDiagnostic } from '../src/v3-connector-diagnostic.ts';

async function fixture(root: string, disabled = false) {
  const archive = zipSync({
    '.qoder-plugin/plugin.json': Buffer.from(
      JSON.stringify({ name: 'runtime-fixture', version: '1.0.0', mcpServers: './mcp.json' }),
    ),
    'mcp.json': Buffer.from(
      JSON.stringify({
        mcpServers: {
          fixture: {
            command: 'node',
            args: ['${PLUGIN_ROOT}/server.mjs'],
            cwd: '.',
            env: { TEST_TOKEN: '${FIXTURE_TOKEN}' },
            disabled,
          },
        },
      }),
    ),
    'server.mjs': await readFile(join(process.cwd(), 'tests/fixtures/mcp-stdio-server.mjs')),
  });
  const source = (
    await inspectMarketPluginPackage(archive, {
      marketId: 'runtime-fixture',
      canonicalId: 'runtime-fixture@marketplace',
      pluginName: 'runtime-fixture',
      version: '1.0.0',
      objectKey: 'verified/fixture.zip',
      sha256: createHash('sha256').update(archive).digest('hex'),
    })
  ).package;
  return {
    archive,
    input: {
      storage: {
        async get(key: string) {
          expect(key).toBe(source.objectKey);
          return archive;
        },
      },
      package: source,
      packageId: randomUUID(),
      root,
      serverName: 'fixture',
      binding: { versionId: randomUUID(), connectorId: randomUUID(), selectedTools: ['echo'] },
      variables: { FIXTURE_TOKEN: 'fixture-only' },
      allowStdio: true,
    },
  };
}

it('loads an installed owned connector through task-pinned plugin provenance and encrypted variables', async () => {
  const root = await mkdtemp(join(tmpdir(), 'plugin-task-loader-'));
  const store = createV3LocalWakerGroupStore(join(root, 'test.db'));
  let toolSet: Awaited<ReturnType<typeof loadV3BoundConnectorTools>> | undefined;
  try {
    const request = {
      principal: {
        workspaceId: randomUUID(),
        userId: randomUUID(),
        displayName: 'Fixture',
        role: 'owner' as const,
        permissions: ['*'],
      },
      correlationId: randomUUID(),
    };
    const mutation = (input: unknown) => ({
      ...request,
      idempotency: { key: randomUUID(), requestHash: canonicalRequestHash(input) },
    });
    const wakers = new SqliteWakerGroupRepository(store);
    const registry = new SqlitePluginRegistryRepository(store);
    const resources = new SqliteSkillConnectorRepository(store);
    const vault = new SqliteV3WorkspaceSecretVault(store, request.principal.workspaceId, 'p'.repeat(32));
    const target = {
      name: 'Plugin task',
      roleName: 'Engineer',
      bio: 'Fixture',
      environment: 'local' as const,
      roleTemplateVersionId: '33000000-0000-4000-8000-000000000011',
    };
    const waker = await wakers.create(mutation(target), target);
    const current = () =>
      store.get<{ id: string; effective_snapshot: string }>(
        'SELECT c.id,c.effective_snapshot FROM v3_wakers w JOIN v3_waker_configuration_versions c ON c.id=w.current_configuration_version_id WHERE w.id=?',
        waker.id,
      )!;
    const { input } = await fixture(join(root, 'packages'));
    const installationInput = {
      package: input.package,
      ready: false,
      expectedConfigurationVersionId: current().id,
    };
    const installed = await registry.installMarket(mutation(installationInput), waker.id, installationInput);
    const connectorInput = {
      name: 'fixture',
      transport: 'stdio' as const,
      command: 'node',
      arguments: ['not-a-workspace-script.mjs'],
      timeoutSeconds: 10,
      secretRefs: { FIXTURE_TOKEN: await vault.put('fixture:token', 'fixture-only') },
      expectedConfigurationVersionId: current().id,
    };
    const connector = await resources.createPluginConnector(
      mutation(connectorInput),
      waker.id,
      connectorInput,
      { installationId: installed.installationId, expectedRevisionId: installed.id },
    );
    const managedOptions = {
      resources,
      plugins: registry,
      secrets: vault,
      storage: input.storage,
      pluginRoot: input.root,
      cwd: root,
      allowStdio: true,
    };
    await expect(
      connectManagedV3McpConnector(request, connector.id, {
        ...managedOptions,
        allowStdio: false,
      }),
    ).rejects.toThrow('STDIO MCP is disabled');
    await expect(
      connectManagedV3McpConnector(request, connector.id, {
        ...managedOptions,
        storage: { get: async () => new Uint8Array([0]) },
      }),
    ).rejects.toThrow();
    await expect(
      connectManagedV3McpConnector(
        {
          ...request,
          principal: { ...request.principal, workspaceId: randomUUID() },
        },
        connector.id,
        managedOptions,
      ),
    ).rejects.toThrow('Connector not found');
    const diagnosticConnection = await connectManagedV3McpConnector(request, connector.id, managedOptions);
    let actualDiagnostic;
    try {
      actualDiagnostic = readyV3ConnectorDiagnostic(diagnosticConnection, new Date().toISOString());
      expect(actualDiagnostic.tools.map((tool) => tool.name)).toEqual(['echo']);
    } finally {
      await diagnosticConnection.close();
    }
    const diagnosed = await resources.recordConnectorDiagnostic(
      mutation({ id: connector.id }),
      connector.id,
      actualDiagnostic,
    );
    const selection = {
      selectedTools: ['echo'],
      expectedVersion: diagnosed.version,
      expectedConfigurationVersionId: current().id,
    };
    const selected = await resources.updateConnectorTools(mutation(selection), connector.id, selection);
    expect(JSON.parse(current().effective_snapshot).resources.connectorToolSelectionVersionIds).toEqual([]);
    const completion = {
      expectedRevisionId: installed.id,
      expectedConfigurationVersionId: current().id,
      declaredServerNames: ['fixture'],
    };
    const completed = await registry.completeConnectors(
      mutation(completion),
      installed.installationId,
      completion,
    );
    const options = {
      allowStdio: true,
      cwd: root,
      plugins: {
        repository: registry,
        storage: input.storage,
        wakerId: waker.id,
        revisionIds: [completed.id],
        root: input.root,
      },
    };
    const versions = JSON.parse(current().effective_snapshot).resources
      .connectorToolSelectionVersionIds as string[];
    toolSet = await loadV3BoundConnectorTools(resources, vault, request, versions, options);
    const result = await toolSet.tools[0]!.execute(
      'task-bound',
      { text: 'owned-package' },
      undefined,
      undefined,
      {} as never,
    );
    expect(result.content).toEqual([{ type: 'text', text: 'echo:owned-package;secret:fixture-only' }]);
    await toolSet.close();
    toolSet = undefined;
    await expect(
      loadV3BoundConnectorTools(resources, vault, request, versions, {
        ...options,
        plugins: { ...options.plugins, revisionIds: [] },
      }),
    ).rejects.toThrow('Plugin connector binding is unavailable');
    await expect(
      loadV3BoundConnectorTools(resources, vault, request, versions, { ...options, allowStdio: false }),
    ).rejects.toThrow('STDIO MCP is disabled');
    const removal = { expectedRevisionId: completed.id, expectedConfigurationVersionId: current().id };
    await expect(
      loadV3BoundConnectorTools(resources, vault, request, versions, {
        ...options,
        plugins: {
          ...options.plugins,
          repository: {
            resolveBound: registry.resolveBound.bind(registry),
            async listConnectorOwners(context, connectorIds) {
              await registry.uninstall(mutation(removal), installed.installationId, removal);
              return registry.listConnectorOwners(context, connectorIds);
            },
          },
        },
      }),
    ).rejects.toThrow('Bound Connector version not found');
    await expect(connectManagedV3McpConnector(request, connector.id, managedOptions)).rejects.toThrow(
      'Connector not found',
    );
    await expect(
      loadV3BoundConnectorTools(resources, vault, request, [selected.currentVersionId], options),
    ).rejects.toThrow('Bound Connector version not found');
  } finally {
    await toolSet?.close();
    store.close();
    await rm(root, { recursive: true, force: true });
  }
});

it('executes a real MCP tool from verified archive bytes and refuses a changed materialized executable', async () => {
  const root = await mkdtemp(join(tmpdir(), 'verified plugin runtime '));
  let connection: Awaited<ReturnType<typeof connectVerifiedPluginMcp>> | undefined;
  try {
    const { input } = await fixture(root);
    connection = await connectVerifiedPluginMcp(input);
    const tool = connection.createSelectedTools(['echo'])[0]!;
    const legacy = { allowedTools: ['mcp__fixture__*'] };
    expect(pluginAgentTools(legacy, [tool], 'runtime-fixture')).toEqual([tool]);
    expect(pluginAgentTools(legacy, [tool], 'other-plugin')).toEqual([]);
    expect(pluginAgentTools(legacy, [{ ...tool }], 'runtime-fixture')).toEqual([]);
    expect(pluginAgentTools(legacy, [], 'runtime-fixture')).toEqual([]);
    expect(pluginAgentTools({ allowedTools: ['mcp__plugin_runtime-fixture_fixture__echo'] }, [tool])).toEqual(
      [tool],
    );
    expect(
      pluginAgentTools({ ...legacy, tools: ['mcp__fixture__different'] }, [tool], 'runtime-fixture'),
    ).toEqual([]);
    expect(pluginAgentTools({ ...legacy, tools: [] }, [tool], 'runtime-fixture')).toEqual([]);
    const result = await tool.execute(
      'verified-package',
      { text: 'from-archive' },
      undefined,
      undefined,
      {} as never,
    );
    expect(result.content).toEqual([{ type: 'text', text: 'echo:from-archive;secret:fixture-only' }]);
    await connection.close();
    connection = undefined;
    const path = join(root, input.packageId, input.package.sha256, 'server.mjs');
    await writeFile(path, 'throw new Error("tampered");');
    await expect(connectVerifiedPluginMcp(input)).rejects.toThrow(/integrity|size mismatch/);
  } finally {
    await connection?.close();
    await rm(root, { recursive: true, force: true });
  }
});

it('rejects corrupt archives, unknown or disabled declarations and missing explicit variables', async () => {
  const root = await mkdtemp(join(tmpdir(), 'verified-plugin-guards-'));
  try {
    const { input } = await fixture(root);
    await expect(
      connectVerifiedPluginMcp({
        ...input,
        storage: {
          async get() {
            return Buffer.from('corrupt');
          },
        },
      }),
    ).rejects.toThrow();
    await expect(connectVerifiedPluginMcp({ ...input, serverName: 'undeclared' })).rejects.toThrow(
      'declaration is missing',
    );
    await expect(connectVerifiedPluginMcp({ ...input, variables: {} })).rejects.toThrow(
      'variable is required: FIXTURE_TOKEN',
    );
    await expect(
      connectVerifiedPluginMcp({ ...input, package: { ...input.package, inventory: [] } }),
    ).rejects.toThrow('inventory changed');
    await expect(connectVerifiedPluginMcp((await fixture(root, true)).input)).rejects.toThrow(
      'declaration is disabled',
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
