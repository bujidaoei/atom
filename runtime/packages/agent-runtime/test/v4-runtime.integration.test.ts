import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { startEnterpriseGatewayLoopback } from '../../../tests/fixtures/v4/enterprise-ai-gateway.ts';
import type {
  AgentRunRequest,
  RunEventType,
  SandboxClient,
  SandboxExecRequest,
} from '../../product-contracts/src/index.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';
import { createV3KnowledgeTools } from '../src/v3-knowledge-tools.ts';
import type { ToolDefinition } from '../src/pi-runtime-types.ts';
import type { V3RequestContext } from '../../product-contracts/src/v3-ports.ts';

const roots: string[] = [];
const gateways: Array<{ close(): Promise<void> }> = [];

afterEach(async () => {
  await Promise.all(gateways.splice(0).map((gateway) => gateway.close()));
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function createRuntime(options: {
  gateway: Awaited<ReturnType<typeof startEnterpriseGatewayLoopback>>;
  enableTools?: boolean;
  externalTools?: ToolDefinition[];
  onEvent?: (type: RunEventType) => void;
  events?: Array<{ type: RunEventType; payload: Record<string, unknown> }>;
}) {
  const root = await mkdtemp(join(tmpdir(), 'workdude-v4-runtime-'));
  roots.push(root);
  const events = options.events ?? [];
  const writtenFiles: Array<{ path: string; content: string }> = [];
  return {
    root,
    runtime: new ProductAgentRuntime({
      aiGateway: {
        baseUrl: `${options.gateway.baseUrl}/v1`,
        masterKey: options.gateway.apiKey,
        model: 'gateway-model-a',
        requestTimeoutMs: 5_000,
      },
      agentDir: join(root, 'agent'),
      sandbox: {
        create: async () => 'sandbox-v4',
        exec: async (_sandboxId: string, request: SandboxExecRequest) => ({
          toolCallId: request.toolCallId,
          exitCode: 0,
          stdout: '/workspace\n',
          stderr: '',
          timedOut: false,
          truncated: false,
        }),
        writeFile: async (
          _sandboxId: string,
          request: { toolCallId: string; path: string; content: string },
        ) => {
          const path = join(root, 'workspace', request.path);
          await mkdir(dirname(path), { recursive: true });
          await writeFile(path, request.content, 'utf8');
          writtenFiles.push({ path: request.path, content: request.content });
          return { bytesWritten: Buffer.byteLength(request.content) };
        },
        destroy: async () => undefined,
      } as unknown as SandboxClient,
      approvals: { request: async () => 'approved' },
      events: {
        emit: async (type, payload) => {
          events.push({ type, payload });
          options.onEvent?.(type);
        },
      },
      enableTools: options.enableTools ?? false,
      ...(options.externalTools ? { externalTools: options.externalTools } : {}),
    }),
    events,
    writtenFiles,
  };
}

describe('V4 ProductAgentRuntime gateway integration', () => {
  it('executes knowledge retrieval through native Pi and preserves source metadata in the tool event', async () => {
    const bytes = Buffer.from('Synthetic source\nEMAIL-HTML-0925');
    const gateway = await startEnterpriseGatewayLoopback({
      toolCall: {
        name: 'mcp__plugin_knowledge__retrieve_knowledge_content',
        arguments: { notebookId: 'base', query: 'EMAIL' },
      },
      contentChunks: ['Knowledge lookup finished.'],
    });
    gateways.push(gateway);
    const tools = createV3KnowledgeTools({
      repository: {
        listBases: async () => ({ items: [], hasMore: false, nextCursor: null }),
        listBindings: async () => [],
        listCompiledKnowledge: async () => [
          {
            knowledgeBaseId: 'base',
            knowledgeBaseName: 'Synthetic knowledge',
            materialId: 'source',
            materialTitle: 'Test email',
            version: 1,
            objectKey: 'source',
            contentSha256: createHash('sha256').update(bytes).digest('hex'),
            characterCount: bytes.length,
          },
        ],
      },
      storage: { get: async () => bytes },
      context: {} as V3RequestContext,
      bindingVersionIds: ['binding'],
      assertActive() {},
    });
    const { root, runtime, events } = await createRuntime({ gateway, externalTools: tools });
    const result = await runtime.run({
      runId: crypto.randomUUID(),
      prompt: 'Look up EMAIL in the bound knowledge base.',
      workspacePath: join(root, 'workspace'),
      sessionPath: join(root, 'sessions', 'knowledge.jsonl'),
      model: 'gateway-model-a',
    });
    expect(result.resultText).toBe('Knowledge lookup finished.');
    expect(events).toContainEqual(
      expect.objectContaining({
        type: 'tool.completed',
        payload: expect.objectContaining({
          toolName: 'mcp__plugin_knowledge__retrieve_knowledge_content',
          result: expect.objectContaining({
            details: expect.objectContaining({
              sourceLinks: [expect.objectContaining({ sourceId: 'source', lineStart: 1, lineEnd: 2 })],
            }),
          }),
        }),
      }),
    );
    const requests = gateway.requests.filter((request) => request.url.endsWith('/chat/completions'));
    expect(requests.at(-1)?.body).toContain('EMAIL-HTML-0925');
  });
  it('streams reasoning and text with provider-neutral identity, usage, and correlation', async () => {
    const gateway = await startEnterpriseGatewayLoopback({
      reasoningChunks: ['verify ', 'constraints'],
      contentChunks: ['real ', 'gateway ', 'answer'],
      chunkDelayMs: 60,
    });
    gateways.push(gateway);
    const { root, runtime, events } = await createRuntime({ gateway });

    const result = await runtime.run({
      runId: crypto.randomUUID(),
      prompt: 'Return the gateway answer.',
      workspacePath: join(root, 'workspace'),
      sessionPath: join(root, 'sessions', 'stream.jsonl'),
    });

    expect(result).toMatchObject({
      resultText: 'real gateway answer',
      usage: { inputTokens: 7, outputTokens: 5, totalTokens: 12 },
      providerCorrelationId: expect.stringMatching(/^gateway-/u),
    });
    const sessionHeader = JSON.parse(
      (await readFile(join(root, 'sessions', 'stream.jsonl'), 'utf8')).split('\n')[0]!,
    );
    expect(events[0]).toEqual({ type: 'run.session', payload: { sessionId: sessionHeader.id } });
    expect(events[1]).toEqual({
      type: 'model.requested',
      payload: { provider: 'enterprise-gateway', model: 'gateway-model-a' },
    });
    expect(events.filter(({ type }) => type === 'thinking.delta')).not.toHaveLength(0);
    expect(events.filter(({ type }) => type === 'message.delta').length).toBeGreaterThan(1);
    expect(gateway.requests.at(-1)).toMatchObject({
      url: '/v1/chat/completions',
      authorization: `Bearer ${gateway.apiKey}`,
    });
  });

  it('sanitizes Pi response IDs for live and recovered Runs without changing SSE content', async () => {
    const responseId = 'Bearer sk-pi-response-secret-123456789 token=pi-response-token-123456789';
    const reasoning = 'Reasoning remains exact: token=reasoning-content-123456789';
    const modelContent =
      'Model answer remains exact: Bearer sk-answer-content-123456789 token=answer-content-123456789';
    const gateway = await startEnterpriseGatewayLoopback({
      completionId: responseId,
      reasoningChunks: [reasoning],
      contentChunks: [modelContent],
    });
    gateways.push(gateway);
    const { root, runtime, events } = await createRuntime({ gateway });
    const sessionPath = join(root, 'sessions', 'credential-shaped-response-id.jsonl');
    const request = {
      runId: crypto.randomUUID(),
      prompt: 'Return content without rewriting it.',
      workspacePath: join(root, 'workspace'),
      sessionPath,
    };

    const first = await runtime.run(request);
    const recovered = await runtime.run({ ...request, recovery: true });

    expect(first).toMatchObject({
      resultText: modelContent,
      providerCorrelationId: 'Bearer [REDACTED] token=[REDACTED]',
    });
    expect(recovered).toEqual(first);
    expect(gateway.requests.filter(({ url }) => url === '/v1/chat/completions')).toHaveLength(1);
    expect(
      events
        .filter(({ type }) => type === 'thinking.delta')
        .map(({ payload }) => payload.delta)
        .join(''),
    ).toBe(reasoning);
    expect(
      events
        .filter(({ type }) => type === 'message.delta')
        .map(({ payload }) => payload.delta)
        .join(''),
    ).toBe(modelContent);
  });

  it('executes a gateway tool call and preserves tool events before the final answer', async () => {
    const gateway = await startEnterpriseGatewayLoopback({
      toolCall: { name: 'sandbox_exec', arguments: { command: 'pwd', timeoutMs: 10_000 } },
      contentChunks: ['tool complete'],
    });
    gateways.push(gateway);
    const { root, runtime, events } = await createRuntime({ gateway, enableTools: true });

    await expect(
      runtime.run({
        runId: crypto.randomUUID(),
        prompt: 'Run pwd.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'sessions', 'tool.jsonl'),
      }),
    ).resolves.toMatchObject({ resultText: 'tool complete' });
    const types = events.map(({ type }) => type);
    expect(types).toEqual(
      expect.arrayContaining(['tool.requested', 'tool.started', 'tool.completed', 'message.completed']),
    );
    expect(gateway.requests.filter(({ url }) => url === '/v1/chat/completions')).toHaveLength(2);
  });

  it('sends supported private attachments to Pi as image semantics instead of a path-only prompt', async () => {
    const gateway = await startEnterpriseGatewayLoopback({ contentChunks: ['image understood'] });
    gateways.push(gateway);
    const { root, runtime } = await createRuntime({ gateway });
    const imageData = (
      await readFile(
        join(process.cwd(), 'packages/features/src/v3/management/assets/official-roles/frontend.png'),
      )
    ).toString('base64');
    const request = {
      runId: crypto.randomUUID(),
      prompt: 'Classify the attached layout.',
      images: [{ data: imageData, mimeType: 'image/png' }],
      workspacePath: join(root, 'workspace'),
      sessionPath: join(root, 'sessions', 'image.jsonl'),
    } as AgentRunRequest & { images: Array<{ data: string; mimeType: string }> };

    await expect(runtime.run(request)).resolves.toMatchObject({ resultText: 'image understood' });
    const payload = JSON.parse(gateway.requests.find(({ url }) => url === '/v1/chat/completions')!.body) as {
      messages: Array<{ role: string; content: unknown }>;
    };
    const user = payload.messages.find(({ role }) => role === 'user');
    expect(user?.content).toEqual(
      expect.arrayContaining([
        {
          type: 'image_url',
          image_url: { url: `data:image/png;base64,${imageData}` },
        },
      ]),
    );
  });

  it('retains image input when a shared-session turn crashes after its boundary but before its user message', async () => {
    const gateway = await startEnterpriseGatewayLoopback({ contentChunks: ['image understood'] });
    gateways.push(gateway);
    let sessionEvents = 0;
    const { root, runtime } = await createRuntime({
      gateway,
      onEvent(type) {
        if (type === 'run.session' && ++sessionEvents === 2)
          throw new Error('simulated interruption before input');
      },
    });
    const workspacePath = join(root, 'workspace');
    const sessionPath = join(root, 'sessions', 'image-recovery.jsonl');
    await runtime.run({
      runId: crypto.randomUUID(),
      prompt: 'Initial text turn.',
      workspacePath,
      sessionPath,
    });
    const imageData = (
      await readFile(join(process.cwd(), 'tests/fixtures/v3/official-avatars/frontend.png'))
    ).toString('base64');
    const request: AgentRunRequest = {
      runId: crypto.randomUUID(),
      prompt: 'Describe this image.',
      images: [{ data: imageData, mimeType: 'image/png' }],
      workspacePath,
      sessionPath,
    };
    await expect(runtime.run(request)).rejects.toThrow('simulated interruption before input');
    expect(gateway.requests.filter(({ url }) => url === '/v1/chat/completions')).toHaveLength(1);
    await expect(runtime.run({ ...request, recovery: true })).resolves.toMatchObject({
      resultText: 'image understood',
    });
    const requests = gateway.requests.filter(({ url }) => url === '/v1/chat/completions');
    expect(requests).toHaveLength(2);
    const payload = JSON.parse(requests[1]!.body) as { messages: Array<{ role: string; content: unknown }> };
    const user = payload.messages.findLast(({ role }) => role === 'user');
    expect(user?.content).toEqual(
      expect.arrayContaining([
        { type: 'image_url', image_url: { url: `data:image/png;base64,${imageData}` } },
      ]),
    );
    // Once Pi has persisted the image input, recovery must reuse it, not add it again.
    const entries = (await readFile(sessionPath, 'utf8'))
      .trim()
      .split('\n')
      .map((line) => JSON.parse(line) as { type: string; message?: { role: string; stopReason?: string } });
    const lastAssistant = entries.findLast(
      (entry) => entry.type === 'message' && entry.message?.role === 'assistant',
    );
    if (!lastAssistant?.message) throw new Error('missing assistant fixture');
    lastAssistant.message.stopReason = 'aborted';
    await writeFile(sessionPath, entries.map((entry) => JSON.stringify(entry)).join('\n') + '\n');
    await runtime.run({ ...request, recovery: true });
    const resumed = JSON.parse(
      gateway.requests.filter(({ url }) => url === '/v1/chat/completions')[2]!.body,
    ) as { messages: Array<{ content: unknown }> };
    const imageParts = resumed.messages
      .flatMap(({ content }) => (Array.isArray(content) ? content : []))
      .filter((part: { type?: string }) => part.type === 'image_url');
    expect(imageParts).toHaveLength(1);
  });

  it('reuses Pi Read for an exact durable group image without enabling general workspace tools', async () => {
    const image = await readFile(
      join(
        process.cwd(),
        'packages',
        'features',
        'src',
        'v3',
        'management',
        'assets',
        'official-roles',
        'frontend.png',
      ),
    );
    const toolCall = { name: 'read', arguments: { path: 'REPLACED_BY_TEST' } };
    const gateway = await startEnterpriseGatewayLoopback({
      toolCall,
      contentChunks: ['group image understood'],
    });
    gateways.push(gateway);
    const { root, runtime, events } = await createRuntime({ gateway });
    const attachmentPath = join(
      root,
      'cloud-conversations',
      'conversation-01',
      'attachments',
      'frontend.png',
    );
    await mkdir(dirname(attachmentPath), { recursive: true });
    await writeFile(attachmentPath, image);
    toolCall.arguments.path = attachmentPath;

    await expect(
      runtime.run({
        runId: crypto.randomUUID(),
        prompt: `Inspect ${attachmentPath}.`,
        readableAttachments: [
          {
            path: attachmentPath,
            mediaType: 'image/png',
            sizeBytes: image.byteLength,
            sha256: createHash('sha256').update(image).digest('hex'),
          },
        ],
        workspacePath: join(root, 'cloud-conversations', 'conversation-01', 'workers', 'member-01'),
        sessionPath: join(root, 'sessions', 'group-image.jsonl'),
      }),
    ).resolves.toMatchObject({ resultText: 'group image understood' });
    expect(events.map(({ type }) => type).filter((type) => type.startsWith('tool.'))).toEqual([
      'tool.requested',
      'tool.started',
      'tool.completed',
    ]);
    expect(gateway.requests.at(-1)?.body).toContain('data:image/png;base64,');
  });

  it('reuses the Pi Write tool through the sandbox file adapter and retains ordered evidence', async () => {
    const gateway = await startEnterpriseGatewayLoopback({
      toolCall: {
        name: 'write',
        arguments: {
          path: 'attachment-tool-proof.md',
          content: 'RIGHT_DRAWER\nATTACHMENT-TOOL-19830-20260825\n',
        },
      },
      contentChunks: ['attachment-tool-proof.md\nATTACHMENT-TOOL-19830-20260825'],
    });
    gateways.push(gateway);
    const { root, runtime, events, writtenFiles } = await createRuntime({ gateway, enableTools: true });

    await expect(
      runtime.run({
        runId: crypto.randomUUID(),
        prompt: 'Create the requested proof file with Write.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'sessions', 'write.jsonl'),
      }),
    ).resolves.toMatchObject({
      resultText: 'attachment-tool-proof.md\nATTACHMENT-TOOL-19830-20260825',
    });
    expect(writtenFiles).toEqual([
      {
        path: 'attachment-tool-proof.md',
        content: 'RIGHT_DRAWER\nATTACHMENT-TOOL-19830-20260825\n',
      },
    ]);
    await expect(readFile(join(root, 'workspace', 'attachment-tool-proof.md'), 'utf8')).resolves.toBe(
      'RIGHT_DRAWER\nATTACHMENT-TOOL-19830-20260825\n',
    );
    const ordered = events
      .filter(({ type }) => ['tool.requested', 'tool.started', 'tool.completed'].includes(type))
      .map(({ type }) => type);
    expect(ordered).toEqual(['tool.requested', 'tool.started', 'tool.completed']);
    expect(events.find(({ type }) => type === 'tool.completed')?.payload).toMatchObject({
      toolName: 'write',
      result: expect.anything(),
    });
  });

  it('propagates external cancellation without a completed message', async () => {
    const gateway = await startEnterpriseGatewayLoopback({ delayMs: 250 });
    gateways.push(gateway);
    const { root, runtime, events } = await createRuntime({ gateway });
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 25);

    await expect(
      runtime.run({
        runId: crypto.randomUUID(),
        prompt: 'Wait for cancellation.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'sessions', 'cancel.jsonl'),
        signal: controller.signal,
      }),
    ).rejects.toThrow(/abort|cancel/iu);
    expect(events.map(({ type }) => type)).not.toContain('message.completed');
  });

  it('rejects a truncated stream instead of manufacturing completion', async () => {
    const gateway = await startEnterpriseGatewayLoopback({ truncateStream: true });
    gateways.push(gateway);
    const { root, runtime, events } = await createRuntime({ gateway });

    await expect(
      runtime.run({
        runId: crypto.randomUUID(),
        prompt: 'This stream will truncate.',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'sessions', 'truncated.jsonl'),
      }),
    ).rejects.toThrow(/stream|connection|terminated|fetch/iu);
    expect(events.map(({ type }) => type)).not.toContain('message.completed');
  });
});
