import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';
import type { ProductSkillDirectory } from '../src/workspace-tools.ts';

it.each(['alpha', 'beta', 'duplicate', 'invalid'] as const)(
  'resolves native plugin-qualified identities without replacing same-name ordinary Skills: %s',
  async (mode) => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-plugin-qualified-'));
    const destroy = vi.fn(async () => undefined);
    const provider = await startGatewayLoopback({ content: 'QUALIFIED-COMPLETE' });
    try {
      const skillDirectories: ProductSkillDirectory[] = [];
      const originals: string[] = [];
      for (const owner of ['ordinary', 'alpha', 'beta']) {
        const directoryPath = join(root, owner, 'shared');
        const path = join(directoryPath, 'SKILL.md');
        const content = `---\nname: shared\ndescription: ${owner} synthetic description.\n---\n${owner.toUpperCase()}-PRIVATE-BODY\n`;
        await mkdir(directoryPath, { recursive: true });
        await writeFile(path, content);
        originals.push(content);
        skillDirectories.push({
          directoryPath,
          ...(owner === 'ordinary'
            ? {}
            : { pluginName: mode === 'duplicate' ? 'same' : mode === 'invalid' ? 'bad:name' : owner }),
          files: [
            {
              path,
              sizeBytes: Buffer.byteLength(content),
              sha256: createHash('sha256').update(content).digest('hex'),
              mediaType: 'text/markdown',
            },
          ],
        });
      }
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: provider.baseUrl,
          masterKey: 'loopback-test-credential',
          model: 'deepseek-chat',
          requestTimeoutMs: 5_000,
        },
        agentDir: join(root, 'agent'),
        enableTools: mode === 'duplicate',
        skillDirectories,
        sandbox: {
          create: async () => {
            return 'qualified-test-sandbox';
          },
          exec: async () => {
            throw new Error('no exec');
          },
          destroy,
        },
        approvals: { request: async () => 'rejected' },
        events: { emit: async () => undefined },
      });
      const run = runtime.run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt: `/skill:${mode}:shared ARGUMENT-KEPT`,
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'session.jsonl'),
      });
      if (mode === 'duplicate' || mode === 'invalid') {
        await expect(run).rejects.toThrow(
          mode === 'duplicate' ? /qualified identity is duplicated/iu : /namespace is invalid/iu,
        );
        expect(provider.requests).toHaveLength(0);
        if (mode === 'duplicate') expect(destroy).toHaveBeenCalledExactlyOnceWith('qualified-test-sandbox');
      } else {
        expect((await run).resultText).toBe('QUALIFIED-COMPLETE');
        expect(provider.requests).toHaveLength(1);
        const body = provider.requests[0]!.body;
        for (const name of ['shared', 'alpha:shared', 'beta:shared'])
          expect(body).toContain(`<name>${name}</name>`);
        expect(body).toContain(`${mode.toUpperCase()}-PRIVATE-BODY`);
        expect(body).not.toContain(`${mode === 'alpha' ? 'BETA' : 'ALPHA'}-PRIVATE-BODY`);
        expect(body).not.toContain('ORDINARY-PRIVATE-BODY');
        expect(body).toContain('ARGUMENT-KEPT');
      }
      for (const [index, directory] of skillDirectories.entries())
        expect(await readFile(directory.files[0]!.path, 'utf8')).toBe(originals[index]);
    } finally {
      await provider.close();
      await rm(root, { recursive: true, force: true });
    }
  },
);
