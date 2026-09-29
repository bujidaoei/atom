import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { expect, it } from 'vitest';

import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

it.each(['selected-read', 'unselected-read', 'mutation'] as const)(
  'isolates native Pi drafting from interactive history and authority: %s',
  async (scenario) => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-review-isolation-'));
    const workspacePath = join(root, 'workspace');
    const directoryPath = join(root, 'selected-skill');
    const manifestPath = join(directoryPath, 'SKILL.md');
    const secretPath = join(workspacePath, 'unselected.txt');
    const manifest =
      '---\nname: review-fixture\ndescription: Selected synthetic method.\n---\nSELECTED-FULL-CONTENT';
    await mkdir(workspacePath, { recursive: true });
    await mkdir(directoryPath, { recursive: true });
    await writeFile(manifestPath, manifest);
    await writeFile(secretPath, 'UNSELECTED-CONTENT');
    await writeFile(join(workspacePath, 'AGENTS.md'), 'UNSELECTED-CONTEXT');
    const interactiveProvider = await startGatewayLoopback({ content: 'INTERACTIVE-RESULT' });
    const provider = await startGatewayLoopback({
      externalToolCall: {
        name: scenario === 'mutation' ? 'manage_skill' : 'read',
        arguments:
          scenario === 'mutation'
            ? { action: 'write_file', path: manifestPath, content: 'UNAUTHORIZED-CHANGE' }
            : { path: scenario === 'selected-read' ? manifestPath : secretPath },
        finalContent: 'DRAFT-ONLY-RESULT',
      },
    });
    const options = {
      aiGateway: {
        baseUrl: interactiveProvider.baseUrl,
        masterKey: 'loopback-test-credential',
        model: 'deepseek-chat',
        requestTimeoutMs: 5_000,
      },
      agentDir: join(root, 'agent'),
      sandbox: {
        create: async () => {
          throw new Error('draft must not create sandbox');
        },
        exec: async () => {
          throw new Error('draft must not execute commands');
        },
        destroy: async () => undefined,
      },
      approvals: {
        request: async (): Promise<'rejected'> => {
          throw new Error('draft must not request write approval');
        },
      },
      events: { emit: async () => undefined },
      enableTools: false,
    };
    const sessionPath = join(root, 'sessions', 'interactive.jsonl');
    try {
      await new ProductAgentRuntime(options).run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt: 'INTERACTIVE-HISTORY-NOT-SELECTED',
        workspacePath,
        sessionPath,
      });
      const originalSession = await readFile(sessionPath, 'utf8');
      const runtime = new ProductAgentRuntime({
        ...options,
        aiGateway: { ...options.aiGateway, baseUrl: provider.baseUrl },
        systemPrompt: 'Return a draft only. The host owns publication.',
        skillDirectories: [
          {
            directoryPath,
            files: [
              {
                path: manifestPath,
                sizeBytes: Buffer.byteLength(manifest),
                sha256: createHash('sha256').update(manifest).digest('hex'),
                mediaType: 'text/markdown',
              },
            ],
          },
        ],
      });
      const result = await runtime.run({
        runId: '22222222-2222-4222-8222-222222222222',
        prompt: 'SELECTED-CONVERSATION-SUMMARY',
        workspacePath,
        sessionPath: join(root, 'sessions', 'review.jsonl'),
      });
      expect(result.resultText).toBe('DRAFT-ONLY-RESULT');
      expect(provider.requests).toHaveLength(2);
      const first = JSON.parse(provider.requests[0]!.body) as {
        tools: Array<{ function: { name: string } }>;
      };
      expect(first.tools.map((tool) => tool.function.name)).toEqual(['read']);
      expect(provider.requests[0]!.body).not.toContain('SELECTED-FULL-CONTENT');
      const transcript = provider.requests.map(({ body }) => body).join('\n');
      expect(transcript).not.toContain('INTERACTIVE-HISTORY-NOT-SELECTED');
      expect(transcript).not.toContain('INTERACTIVE-RESULT');
      expect(transcript).not.toContain('UNSELECTED-CONTENT');
      expect(transcript).not.toContain('UNSELECTED-CONTEXT');
      const second = JSON.parse(provider.requests[1]!.body) as {
        messages: Array<{ role: string; content: unknown }>;
      };
      const toolResult = JSON.stringify(second.messages.filter(({ role }) => role === 'tool'));
      if (scenario === 'selected-read') expect(toolResult).toContain('SELECTED-FULL-CONTENT');
      else if (scenario === 'unselected-read')
        expect(toolResult).toContain('not an authorized product resource');
      else expect(toolResult).toMatch(/not found|not available|unknown tool/iu);
      expect(await readFile(manifestPath, 'utf8')).toBe(manifest);
      expect(await readFile(secretPath, 'utf8')).toBe('UNSELECTED-CONTENT');
      expect(await readFile(sessionPath, 'utf8')).toBe(originalSession);
    } finally {
      await Promise.all([provider.close(), interactiveProvider.close()]);
      await rm(root, { recursive: true, force: true });
    }
  },
);
