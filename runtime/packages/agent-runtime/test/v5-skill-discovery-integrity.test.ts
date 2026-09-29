import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';

it.each(['changed', 'late-change', 'unlisted'] as const)(
  'bounds native Skill discovery to verified manifests: %s',
  async (mode) => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-discovery-integrity-'));
    const directoryPath = join(root, 'skills');
    const path =
      mode === 'unlisted' ? join(directoryPath, 'selected', 'SKILL.md') : join(directoryPath, 'SKILL.md');
    const content = '---\nname: signed-method\ndescription: Signed method.\n---\nORIGINAL-BODY\n';
    const destroy = vi.fn(async () => undefined);
    const provider = await startGatewayLoopback({ content: 'COMPLETE' });
    try {
      await mkdir(directoryPath, { recursive: true });
      if (mode === 'unlisted') await mkdir(join(directoryPath, 'selected'));
      await writeFile(path, mode === 'changed' ? content.replace('ORIGINAL', 'MODIFIED') : content);
      if (mode === 'unlisted') {
        await mkdir(join(directoryPath, 'extra'));
        await writeFile(
          join(directoryPath, 'extra', 'SKILL.md'),
          '---\nname: unsigned-method\ndescription: UNSIGNED-DISCOVERY-NONCE.\n---\nDo not load.\n',
        );
      }
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: provider.baseUrl,
          masterKey: 'loopback-test-credential',
          model: 'deepseek-chat',
          requestTimeoutMs: 5_000,
        },
        agentDir: join(root, 'agent'),
        enableTools: mode === 'changed',
        sandbox: {
          create: async () => {
            return 'integrity-test-sandbox';
          },
          exec: async () => {
            throw new Error('no exec');
          },
          destroy,
        },
        approvals: { request: async () => 'rejected' },
        events: {
          emit: async (type) => {
            if (mode === 'late-change' && type === 'model.requested')
              await writeFile(path, content.replace('ORIGINAL', 'MODIFIED'));
          },
        },
        skillDirectories: [
          {
            directoryPath,
            files: [
              {
                path,
                sizeBytes: Buffer.byteLength(content),
                sha256: createHash('sha256').update(content).digest('hex'),
                mediaType: 'text/markdown',
              },
            ],
          },
        ],
      });
      const run = runtime.run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt: '/skill:signed-method Return a result.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'session.jsonl'),
      });
      if (mode !== 'unlisted') {
        await expect(run).rejects.toThrow(/checksum mismatch/iu);
        expect(provider.requests).toHaveLength(0);
        if (mode === 'changed') expect(destroy).toHaveBeenCalledExactlyOnceWith('integrity-test-sandbox');
      } else {
        expect((await run).resultText).toBe('COMPLETE');
        expect(provider.requests).toHaveLength(1);
        expect(provider.requests[0]!.body).toContain('ORIGINAL-BODY');
        expect(provider.requests[0]!.body).not.toContain('UNSIGNED-DISCOVERY-NONCE');
      }
    } finally {
      await provider.close();
      await rm(root, { recursive: true, force: true });
    }
  },
);
