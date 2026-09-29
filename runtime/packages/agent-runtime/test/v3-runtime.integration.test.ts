import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import type { SandboxClient } from '../../product-contracts/src/index.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';
import {
  v3SkillReferenceSource,
  v3SkillReferenceToken,
} from '../../product-contracts/src/v3-skill-reference.ts';

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe('V3 Pi/DeepSeek Runtime', () => {
  it('runs the real Pi runtime against the deterministic DeepSeek protocol and preserves usage/correlation', async () => {
    const provider = await startGatewayLoopback({ content: 'nonce RUNTIME-V3-001' });
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-runtime-'));
    roots.push(root);
    const emitted: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const unusedSandbox: SandboxClient = {
      create: async () => {
        throw new Error('sandbox must not be created for a chat-only run');
      },
      exec: async () => {
        throw new Error('sandbox must not be executed for a chat-only run');
      },
      destroy: async () => undefined,
    };
    try {
      const runtime = new ProductAgentRuntime({
        aiGateway: {
          baseUrl: provider.baseUrl,
          masterKey: 'loopback-test-credential',
          model: 'deepseek-chat',
          requestTimeoutMs: 5_000,
        },
        agentDir: join(root, 'agent'),
        sandbox: unusedSandbox,
        approvals: {
          request: async () => {
            throw new Error('approval must not be requested for a chat-only run');
          },
        },
        events: {
          async emit(type, payload) {
            emitted.push({ type, payload });
          },
        },
        enableTools: false,
      });
      const result = await runtime.run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt: 'Return the nonce exactly.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'sessions', 'session.jsonl'),
      });

      expect(result.resultText).toContain('RUNTIME-V3-001');
      expect(result.usage).toMatchObject({ inputTokens: 7, outputTokens: 5, totalTokens: 12 });
      expect(result.providerCorrelationId).toMatch(/^loopback-[a-f0-9]{16}$/u);
      expect(emitted.map(({ type }) => type)).toEqual(
        expect.arrayContaining([
          'model.requested',
          'run.started',
          'message.delta',
          'usage.updated',
          'message.completed',
        ]),
      );
      expect(emitted.findIndex(({ type }) => type === 'model.requested')).toBeLessThan(
        emitted.findIndex(({ type }) => type === 'run.started'),
      );
      expect(emitted.findIndex(({ type }) => type === 'usage.updated')).toBeLessThan(
        emitted.findIndex(({ type }) => type === 'message.completed'),
      );
      expect(provider.requests).toHaveLength(1);
      expect(provider.requests[0]).toMatchObject({ method: 'POST', path: '/chat/completions' });
      expect(provider.requests[0]?.body).toContain('Return the nonce exactly.');
      const followupPath = join(root, 'sessions', 'followup.jsonl');
      const followup = await runtime.run({
        runId: '22222222-2222-4222-8222-222222222222',
        prompt: 'Recall the nonce from the previous turn.',
        workspacePath: join(root, 'workspace'),
        sessionPath: followupPath,
        parentSessionPath: join(root, 'sessions', 'session.jsonl'),
        recovery: true,
      });
      expect(provider.requests).toHaveLength(2);
      const followupBody = JSON.parse(provider.requests[1]!.body) as {
        messages: Array<{ role: string; content: unknown }>;
      };
      expect(followupBody.messages).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            role: 'user',
            content: [{ type: 'text', text: 'Return the nonce exactly.' }],
          }),
          expect.objectContaining({ role: 'assistant', content: expect.stringContaining('RUNTIME-V3-001') }),
          expect.objectContaining({
            role: 'user',
            content: [{ type: 'text', text: 'Recall the nonce from the previous turn.' }],
          }),
        ]),
      );
      expect(followup.usage).toMatchObject({ inputTokens: 7, outputTokens: 5, totalTokens: 12 });
      const recovered = await runtime.run({
        runId: '22222222-2222-4222-8222-222222222222',
        prompt: 'Recall the nonce from the previous turn.',
        workspacePath: join(root, 'workspace'),
        sessionPath: followupPath,
        recovery: true,
      });
      expect(provider.requests).toHaveLength(2);
      expect(recovered.usage).toMatchObject({ inputTokens: 7, outputTokens: 5, totalTokens: 12 });
    } finally {
      await provider.close();
    }
  });

  it('registers personal/group Skills through Pi with first-name precedence and companion-file metadata', async () => {
    const provider = await startGatewayLoopback({ content: 'PI-SKILL-DISCOVERY-OK' });
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-runtime-skill-'));
    roots.push(root);
    const projectedEvents: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const directoryPath = join(root, 'materialized-skills', 'assistant');
    const manifestPath = join(directoryPath, 'SKILL.md');
    const referencePath = join(directoryPath, 'references', 'guide.md');
    const manifest = Buffer.from(
      '---\nname: runtime-skill\ndescription: Runtime Skill discovery nonce.\n---\nRead references/guide.md.',
    );
    const reference = Buffer.from('RUNTIME-SKILL-COMPANION-OK');
    await mkdir(join(directoryPath, 'references'), { recursive: true });
    await writeFile(manifestPath, manifest);
    await writeFile(referencePath, reference);
    const groupDirectory = join(root, 'materialized-skills', 'group');
    const groupManifestPath = join(groupDirectory, 'SKILL.md');
    const groupManifest = Buffer.from(
      '---\nname: runtime-skill\ndescription: Group duplicate.\n---\nGroup instructions.',
    );
    await mkdir(groupDirectory, { recursive: true });
    await writeFile(groupManifestPath, groupManifest);
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
          throw new Error('sandbox must not be created for a Skill discovery run');
        },
        exec: async () => {
          throw new Error('sandbox must not be executed for a Skill discovery run');
        },
        destroy: async () => undefined,
      },
      approvals: { request: async () => 'rejected' },
      events: {
        emit: async (type, payload) => {
          projectedEvents.push({ type, payload });
        },
      },
      enableTools: false,
      skillDirectories: [
        {
          versionId: 'bound-skill-version',
          directoryPath,
          files: [
            {
              path: manifestPath,
              sizeBytes: manifest.byteLength,
              sha256: createHash('sha256').update(manifest).digest('hex'),
              mediaType: 'text/markdown',
            },
            {
              path: referencePath,
              sizeBytes: reference.byteLength,
              sha256: createHash('sha256').update(reference).digest('hex'),
              mediaType: 'text/markdown',
            },
          ],
        },
        {
          directoryPath: groupDirectory,
          files: [
            {
              path: groupManifestPath,
              sizeBytes: groupManifest.byteLength,
              sha256: createHash('sha256').update(groupManifest).digest('hex'),
              mediaType: 'text/markdown',
            },
          ],
        },
      ],
    });

    try {
      await runtime.run({
        runId: '10101010-1010-4010-8010-101010101010',
        prompt:
          '[[capability:%5B%22skill%22%2C%22%5B%5C%22skill%5C%22%2C%5C%22bound-skill-version%5C%22%5D%22%2C%22Display%20Name%22%5D]] Return the discovery nonce.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'sessions', 'skill.jsonl'),
      });
      const requestBody = provider.requests[0]?.body ?? '';
      const request = JSON.parse(requestBody) as {
        messages: Array<{ content: unknown; role: string }>;
      };
      const systemPrompt = request.messages.find(({ role }) => role === 'system')?.content;
      expect(systemPrompt).toEqual(expect.any(String));
      expect(systemPrompt).toContain('<available_skills>');
      expect(systemPrompt).toContain('<name>runtime-skill</name>');
      expect(systemPrompt).toContain('<description>Runtime Skill discovery nonce.</description>');
      expect(systemPrompt).toContain(manifestPath);
      expect(systemPrompt).not.toContain(groupManifestPath);
      expect(systemPrompt).not.toContain('Group duplicate.');
      expect(systemPrompt).not.toContain('RUNTIME-SKILL-COMPANION-OK');
      const projection = projectedEvents.find((event) => event.payload.skillReferences);
      expect(projection).toEqual({
        type: 'run.session',
        payload: {
          sessionId: expect.any(String),
          skillReferences: [{ sourceId: '["skill","bound-skill-version"]', name: 'runtime-skill' }],
        },
      });
      expect(JSON.stringify(projection)).not.toContain(directoryPath);
    } finally {
      await provider.close();
    }
  });

  it('resumes the exact persisted PI session file and applies the injected Waker system contract', async () => {
    const provider = await startGatewayLoopback({ content: 'member result' });
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-runtime-resume-'));
    roots.push(root);
    const sessionPath = join(root, 'sessions', 'member-role-run.jsonl');
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
          throw new Error('sandbox must not be created for a chat-only run');
        },
        exec: async () => {
          throw new Error('sandbox must not be executed for a chat-only run');
        },
        destroy: async () => undefined,
      },
      approvals: {
        request: async () => {
          throw new Error('approval must not be requested for a chat-only run');
        },
      },
      events: { emit: async () => undefined },
      enableTools: false,
      systemPrompt: 'You are the 产品 Waker. Obey PLAN-V1 and submit EVIDENCE-CONTRACT-V1.',
    });

    try {
      const first = await runtime.run({
        runId: '11111111-1111-4111-8111-111111111111',
        prompt: 'FIRST-ROLE-TURN',
        workspacePath: join(root, 'workspace'),
        sessionPath,
      });
      await runtime.run({
        runId: '22222222-2222-4222-8222-222222222222',
        prompt: 'SECOND-ROLE-TURN',
        workspacePath: join(root, 'workspace'),
        sessionPath,
      });

      expect(first.sessionFile).toBe(sessionPath);
      expect(provider.requests).toHaveLength(2);
      expect(provider.requests[0]?.body).toContain('You are the 产品 Waker');
      expect(provider.requests[1]?.body).toContain('FIRST-ROLE-TURN');
      expect(provider.requests[1]?.body).toContain('member result');
      expect(provider.requests[1]?.body).toContain('SECOND-ROLE-TURN');
    } finally {
      await provider.close();
    }
  });

  it('recovers a persisted completed PI turn without requesting the model twice', async () => {
    const provider = await startGatewayLoopback({ content: 'completed before commit' });
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-runtime-completed-recovery-'));
    roots.push(root);
    const sessionPath = join(root, 'sessions', 'completed-before-commit.jsonl');
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
          throw new Error('sandbox must not be created for a chat-only run');
        },
        exec: async () => {
          throw new Error('sandbox must not be executed for a chat-only run');
        },
        destroy: async () => undefined,
      },
      approvals: { request: async () => 'rejected' },
      events: { emit: async () => undefined },
      enableTools: false,
    });

    try {
      const first = await runtime.run({
        runId: '33333333-3333-4333-8333-333333333333',
        prompt: 'FINISH-BEFORE-DATABASE-COMMIT',
        workspacePath: join(root, 'workspace'),
        sessionPath,
      });
      const recovered = await runtime.run({
        runId: '33333333-3333-4333-8333-333333333333',
        prompt: 'FINISH-BEFORE-DATABASE-COMMIT',
        workspacePath: join(root, 'workspace'),
        sessionPath,
        recovery: true,
      });

      expect(recovered).toEqual(first);
      expect(provider.requests).toHaveLength(1);
    } finally {
      await provider.close();
    }
  });

  it('starts a reclaimed new Run in a shared conversation session instead of recovering the previous reply', async () => {
    const provider = await startGatewayLoopback({
      response: ({ requestNumber }) => ({
        content: requestNumber === 1 ? 'previous reply' : 'new run reply',
      }),
    });
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-runtime-completed-recovery-'));
    roots.push(root);
    const sessionPath = join(root, 'sessions', 'completed-before-commit.jsonl');
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
          throw new Error('sandbox must not be created for a chat-only run');
        },
        exec: async () => {
          throw new Error('sandbox must not be executed for a chat-only run');
        },
        destroy: async () => undefined,
      },
      approvals: { request: async () => 'rejected' },
      events: { emit: async () => undefined },
      enableTools: false,
    });

    try {
      const first = await runtime.run({
        runId: '33333333-3333-4333-8333-333333333333',
        prompt: 'FINISH-BEFORE-DATABASE-COMMIT',
        workspacePath: join(root, 'workspace'),
        sessionPath,
      });
      const recovered = await runtime.run({
        runId: '55555555-5555-4555-8555-555555555555',
        prompt: 'NEW-RUN-RECLAIMED-BEFORE-START',
        workspacePath: join(root, 'workspace'),
        sessionPath,
        recovery: true,
      });

      expect(first.resultText).toBe('previous reply');
      expect(recovered.resultText).toBe('new run reply');
      expect(provider.requests).toHaveLength(2);
      expect(provider.requests[1]?.body).toContain('FINISH-BEFORE-DATABASE-COMMIT');
      expect(provider.requests[1]?.body).toContain('NEW-RUN-RECLAIMED-BEFORE-START');
      const replay = await runtime.run({
        runId: '55555555-5555-4555-8555-555555555555',
        prompt: 'NEW-RUN-RECLAIMED-BEFORE-START',
        workspacePath: join(root, 'workspace'),
        sessionPath,
        recovery: true,
      });
      expect(replay).toEqual(recovered);
      expect(provider.requests).toHaveLength(2);
      const olderReplay = await runtime.run({
        runId: '33333333-3333-4333-8333-333333333333',
        prompt: 'FINISH-BEFORE-DATABASE-COMMIT',
        workspacePath: join(root, 'workspace'),
        sessionPath,
        recovery: true,
      });
      expect(olderReplay).toEqual(first);
      expect(provider.requests).toHaveLength(2);
    } finally {
      await provider.close();
    }
  });

  it('continues an interrupted PI turn from the same session instead of replaying it as a new task', async () => {
    const assistantToken = v3SkillReferenceToken('not-user-selected', 'Assistant quoted example');
    const provider = await startGatewayLoopback({
      response: ({ requestNumber }) => ({
        content:
          requestNumber === 1 ? `partial before interruption ${assistantToken}` : 'continued after restart',
      }),
    });
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-runtime-partial-recovery-'));
    roots.push(root);
    const sessionPath = join(root, 'sessions', 'interrupted.jsonl');
    const directoryPath = join(root, 'skills', 'recovery');
    const manifestPath = join(directoryPath, 'SKILL.md');
    const manifest = Buffer.from(
      '---\nname: recovery-skill\ndescription: Recovery source authority.\n---\nKeep the original request.',
    );
    await mkdir(directoryPath, { recursive: true });
    await writeFile(manifestPath, manifest);
    const source = v3SkillReferenceSource('recovery-version');
    const originalPrompt = `Language: Chinese\n${v3SkillReferenceToken(source, 'Display Label')} ORIGINAL-UNFINISHED-REQUEST`;
    const projections: Record<string, unknown>[] = [];
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
          throw new Error('sandbox must not be created for a chat-only run');
        },
        exec: async () => {
          throw new Error('sandbox must not be executed for a chat-only run');
        },
        destroy: async () => undefined,
      },
      approvals: { request: async () => 'rejected' },
      events: {
        emit: async (_type, payload) => {
          if (payload.skillReferences) projections.push(payload);
        },
      },
      enableTools: false,
      skillDirectories: [
        {
          versionId: 'recovery-version',
          directoryPath,
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

    try {
      await runtime.run({
        runId: '44444444-4444-4444-8444-444444444444',
        prompt: originalPrompt,
        workspacePath: join(root, 'workspace'),
        sessionPath,
      });
      const entries = (await readFile(sessionPath, 'utf8'))
        .trimEnd()
        .split('\n')
        .map((line) => JSON.parse(line) as Record<string, unknown>);
      const finalMessage = [...entries]
        .reverse()
        .find(
          (entry) => entry.type === 'message' && (entry.message as { role?: string })?.role === 'assistant',
        );
      if (!finalMessage) throw new Error('PI assistant message fixture was not persisted');
      (finalMessage.message as { stopReason: string }).stopReason = 'aborted';
      await writeFile(sessionPath, `${entries.map((entry) => JSON.stringify(entry)).join('\n')}\n`, 'utf8');

      const recovered = await runtime.run({
        runId: '44444444-4444-4444-8444-444444444444',
        prompt: originalPrompt,
        workspacePath: join(root, 'workspace'),
        sessionPath,
        recovery: true,
      });

      expect(recovered.resultText).toBe('continued after restart');
      expect(recovered.usage).toMatchObject({ inputTokens: 14, outputTokens: 10, totalTokens: 24 });
      expect(provider.requests).toHaveLength(2);
      expect(provider.requests[1]?.body).toContain('ORIGINAL-UNFINISHED-REQUEST');
      expect(provider.requests[1]?.body).toContain('partial before interruption');
      expect(provider.requests[1]?.body).toContain('Continue the unfinished request');
      const resumedRequest = JSON.parse(provider.requests[1]?.body ?? '{}') as {
        messages?: Array<{ role?: string; content?: unknown }>;
      };
      const finalUserMessage = [...(resumedRequest.messages ?? [])]
        .reverse()
        .find((message) => message.role === 'user');
      expect(JSON.stringify(finalUserMessage?.content)).toContain('ORIGINAL-UNFINISHED-REQUEST');
      expect(JSON.stringify(finalUserMessage?.content)).not.toContain('First verify the current state');
      expect(JSON.stringify(finalUserMessage?.content)).toContain('Language: Chinese');
      expect(JSON.stringify(finalUserMessage?.content)).toContain(
        '/recovery-skill ORIGINAL-UNFINISHED-REQUEST',
      );
      expect(JSON.stringify(finalUserMessage?.content)).toContain(assistantToken);
      expect(projections).toHaveLength(2);
      expect(projections[1]?.skillReferences).toEqual([{ sourceId: source, name: 'recovery-skill' }]);
    } finally {
      await provider.close();
    }
  });

  it('rejects a real provider-protocol authentication error instead of returning an assistant result', async () => {
    const provider = await startGatewayLoopback({ status: 401 });
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-runtime-provider-auth-'));
    roots.push(root);
    const emitted: string[] = [];
    const runtime = new ProductAgentRuntime({
      aiGateway: {
        baseUrl: provider.baseUrl,
        masterKey: 'invalid-loopback-credential',
        model: 'deepseek-chat',
        requestTimeoutMs: 5_000,
      },
      agentDir: join(root, 'agent'),
      sandbox: {
        create: async () => {
          throw new Error('sandbox must not be created for a chat-only run');
        },
        exec: async () => {
          throw new Error('sandbox must not be executed for a chat-only run');
        },
        destroy: async () => undefined,
      },
      approvals: { request: async () => 'rejected' },
      events: { emit: async (type) => void emitted.push(type) },
      enableTools: false,
    });

    try {
      await expect(
        runtime.run({
          runId: '55555555-5555-4555-8555-555555555555',
          prompt: 'THIS-MUST-NOT-COMPLETE',
          workspacePath: join(root, 'workspace'),
          sessionPath: join(root, 'sessions', 'provider-auth.jsonl'),
        }),
      ).rejects.toThrow(/401|configured failure/iu);
      expect(emitted).not.toContain('message.completed');
    } finally {
      await provider.close();
    }
  });
});
