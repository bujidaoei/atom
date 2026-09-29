import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { expect, it } from 'vitest';

import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

// Opt-in public package fixture, never inferred from a user's home directory.
const packageRoot = process.env.WORKDUDE_TEST_FRONTEND_PLUGIN_ROOT;
it.runIf(Boolean(packageRoot))(
  'loads the installed public plugin Skill through the production native Pi loop',
  async () => {
    const directoryPath = join(packageRoot!, 'skills', 'frontend-design');
    const manifestPath = join(directoryPath, 'SKILL.md');
    const manifest = await readFile(manifestPath);
    const metadata = JSON.parse(
      await readFile(join(packageRoot!, '.qoder-plugin', 'plugin.json'), 'utf8'),
    ) as { name: string; version: string };
    expect(metadata).toMatchObject({ name: 'frontend-design', version: '1.0.0' });
    const root = await mkdtemp(join(tmpdir(), 'workdude-plugin-native-'));
    const provider = await startGatewayLoopback({
      externalToolCall: {
        name: 'read',
        arguments: { path: manifestPath },
        finalContent: 'PLUGIN-SKILL-READ-COMPLETE',
      },
    });
    try {
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: provider.baseUrl,
          masterKey: 'loopback-test-credential',
          model: 'deepseek-chat',
          requestTimeoutMs: 5_000,
        },
        agentDir: join(root, 'agent'),
        sandbox: {
          create: async () => {
            throw new Error('plugin read must not create a sandbox');
          },
          exec: async () => {
            throw new Error('plugin read must not execute commands');
          },
          destroy: async () => undefined,
        },
        approvals: { request: async () => 'rejected' },
        events: { emit: async () => undefined },
        enableTools: false,
        skillDirectories: [
          {
            directoryPath,
            pluginName: metadata.name,
            files: [
              {
                path: manifestPath,
                sizeBytes: manifest.byteLength,
                sha256: createHash('sha256').update(manifest).digest('hex'),
                mediaType: 'text/markdown',
              },
            ],
          },
        ],
      });
      const result = await runtime.run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt:
          '/skill:frontend-design:frontend-design Inspect this Skill for a synthetic reading-log design. Do not execute commands or write files.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'session.jsonl'),
      });
      expect(result.resultText).toBe('PLUGIN-SKILL-READ-COMPLETE');
      expect(provider.requests).toHaveLength(2);
      const first = JSON.parse(provider.requests[0]!.body) as {
        messages: Array<{ role: string; content: unknown }>;
        tools: Array<{ function: { name: string } }>;
      };
      expect(JSON.stringify(first.messages)).toContain('<name>frontend-design:frontend-design</name>');
      expect(first.tools.map(({ function: tool }) => tool.name)).toEqual(['read']);
      const second = JSON.parse(provider.requests[1]!.body) as {
        messages: Array<{ role: string; content: unknown }>;
      };
      const toolResult = second.messages.find(({ role }) => role === 'tool');
      expect(toolResult).toBeDefined();
      expect(toolResult!.content).toContain(manifest.toString('utf8'));
      expect(await readFile(manifestPath)).toEqual(manifest);
    } finally {
      await provider.close();
      await rm(root, { recursive: true, force: true });
    }
  },
);
