import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { zipSync } from 'fflate';
import { expect, it } from 'vitest';
import { inspectMarketPluginPackage } from '../../data-access/src/v3/plugin-package.ts';
import { defaultWakerBuiltinCapabilities } from '../../product-contracts/src/v3.ts';
import type { RemotePluginResources } from '../../product-contracts/src/remote-plugin-resources.ts';
import { materializeRemotePluginResources } from '../src/remote-plugin-resources.ts';

it('delivers standalone markdown and archive companions, preserving integrity across host restarts', async () => {
  const root = await mkdtemp(join(tmpdir(), 'remote-skills-test-'));
  const markdown =
    '---\nname: standalone\ndescription: Test standalone delivery.\n---\nRead references/proof.txt.';
  const digest = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex');
  const archive = zipSync({
    'SKILL.md': Buffer.from(markdown),
    'references/proof.txt': Buffer.from('REMOTE-SKILL-COMPANION'),
  });
  const record = {
    versionId: randomUUID(),
    name: 'standalone',
    markdown,
    contentSha256: digest(markdown),
    source: 'markdown' as const,
    packageSha256: digest(markdown),
    inventory: ['SKILL.md'],
    builtinPackageId: null,
    fileName: 'SKILL.md',
    objectKey: null,
    sizeBytes: Buffer.byteLength(markdown),
    mediaType: 'text/markdown',
  };
  const resources: RemotePluginResources = {
    wakerId: randomUUID(),
    capabilities: defaultWakerBuiltinCapabilities(),
    systemPrompt: 'Bound knowledge: REMOTE-KNOWLEDGE',
    packages: [],
    connectors: [],
    owners: [],
    secrets: {},
    skills: [
      { record, bytes: null },
      {
        record: {
          ...record,
          versionId: randomUUID(),
          source: 'archive',
          packageSha256: digest(archive),
          inventory: ['SKILL.md', 'references/', 'references/proof.txt'],
          fileName: 'proof.zip',
          objectKey: 'proof.zip',
          sizeBytes: archive.byteLength,
          mediaType: 'application/zip',
        },
        bytes: Buffer.from(archive).toString('base64'),
      },
    ],
  };
  const input = { wakerId: resources.wakerId, root, workspacePath: root };
  try {
    const first = await materializeRemotePluginResources(resources, input);
    expect(first.systemPrompt).toBe('Bound knowledge: REMOTE-KNOWLEDGE');
    expect(first.skillDirectories).toHaveLength(2);
    expect(
      await readFile(join(first.skillDirectories[1]!.directoryPath, 'references/proof.txt'), 'utf8'),
    ).toBe('REMOTE-SKILL-COMPANION');
    await first.close();
    const second = await materializeRemotePluginResources(resources, input);
    expect(second.skillDirectories).toEqual(first.skillDirectories);
    await second.close();
    const tampered = structuredClone(resources);
    tampered.skills[0]!.record.markdown += 'tampered';
    await expect(materializeRemotePluginResources(tampered, input)).rejects.toThrow('integrity');
    const damagedArchive = structuredClone(resources);
    damagedArchive.skills[1]!.bytes = Buffer.from('invalid').toString('base64');
    await expect(materializeRemotePluginResources(damagedArchive, input)).rejects.toThrow('integrity');
    const duplicate = structuredClone(resources);
    duplicate.skills.push(duplicate.skills[0]!);
    await expect(materializeRemotePluginResources(duplicate, input)).rejects.toThrow('collision');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it('projects verified remote skills and a real MCP process, rejects foreign/tampered resources, and closes it', async () => {
  const root = await mkdtemp(join(tmpdir(), 'remote-plugin-test-'));
  const wakerId = randomUUID();
  const installationId = randomUUID();
  const connectorId = randomUUID();
  const archive = zipSync({
    '.qoder-plugin/plugin.json': Buffer.from(
      JSON.stringify({
        name: 'remote-proof',
        version: '1.0.0',
        skills: './skills/',
        mcpServers: './mcp.json',
      }),
    ),
    'skills/proof/SKILL.md': Buffer.from(
      '---\nname: proof\ndescription: Test resource delivery.\n---\nUse the echo tool.',
    ),
    'mcp.json': Buffer.from(
      JSON.stringify({ mcpServers: { proof: { command: 'node', args: ['${PLUGIN_ROOT}/server.mjs'] } } }),
    ),
    'server.mjs': await readFile(join(process.cwd(), 'tests/fixtures/mcp-stdio-server.mjs')),
  });
  const pkg = (
    await inspectMarketPluginPackage(archive, {
      marketId: 'remote-proof',
      canonicalId: 'remote-proof@marketplace',
      pluginName: 'remote-proof',
      version: '1.0.0',
      objectKey: 'fixture.zip',
      sha256: createHash('sha256').update(archive).digest('hex'),
    })
  ).package;
  delete pkg.presentation;
  const resources: RemotePluginResources = {
    wakerId,
    capabilities: defaultWakerBuiltinCapabilities(),
    systemPrompt: 'Bound plugin context',
    secrets: {},
    skills: [],
    packages: [
      {
        installation: {
          id: randomUUID(),
          installationId,
          wakerId,
          packageId: randomUUID(),
          number: 1,
          enabled: true,
          ready: true,
          pendingPhase: null,
        },
        package: pkg,
        bytes: Buffer.from(archive).toString('base64'),
      },
    ],
    owners: [{ installationId, connectorId, wakerId, serverName: 'proof' }],
    connectors: [
      {
        versionId: randomUUID(),
        connectorId,
        name: 'proof',
        transport: 'stdio',
        command: 'node',
        arguments: [],
        url: null,
        timeoutSeconds: 5,
        selectedTools: ['echo'],
        secretRefs: {},
      },
    ],
  };
  let loaded: Awaited<ReturnType<typeof materializeRemotePluginResources>> | undefined;
  try {
    const input = { wakerId, root, workspacePath: root };
    await expect(
      materializeRemotePluginResources(resources, { ...input, wakerId: randomUUID() }),
    ).rejects.toThrow('invalid');
    const tampered = structuredClone(resources);
    tampered.packages[0]!.package.sha256 = '0'.repeat(64);
    await expect(materializeRemotePluginResources(tampered, input)).rejects.toThrow('digest');
    loaded = await materializeRemotePluginResources(resources, input);
    expect(loaded.skillDirectories[0]?.pluginName).toBe('remote-proof');
    expect(await readFile(loaded.skillDirectories[0]!.skillPaths![0]!, 'utf8')).toContain(
      'Use the echo tool.',
    );
    expect(loaded.externalTools).toHaveLength(1);
    const result = await loaded.externalTools[0]!.execute(
      'proof-call',
      { text: 'REMOTE-PLUGIN-PROOF' },
      new AbortController().signal,
    );
    expect(JSON.stringify(result)).toContain('REMOTE-PLUGIN-PROOF');
    await loaded.close();
    await expect(
      loaded.externalTools[0]!.execute('closed-call', { text: 'closed' }, new AbortController().signal),
    ).rejects.toThrow();
  } finally {
    await loaded?.close();
    await rm(root, { recursive: true, force: true });
  }
});
