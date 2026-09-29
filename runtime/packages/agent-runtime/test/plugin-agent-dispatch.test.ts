import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Type } from 'typebox';
import { expect, it } from 'vitest';
import { startGatewayLoopback } from '../../../tests/fixtures/v3/providers.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';
import { pluginAgentTools } from '../src/plugin-agent-tool.ts';
import type { ToolDefinition } from '../src/pi-runtime-types.ts';
import { projectRunActivity } from '../../features/src/v3/conversations/run-activity.ts';

const tool = (name: string): ToolDefinition => ({
  name,
  label: name,
  description: name,
  parameters: Type.Object({}),
  execute: async () => ({ content: [{ type: 'text', text: 'DOCUMENT-EVIDENCE' }] }),
});

it('intersects both declarations with parent tools and preserves explicit empty scope', () => {
  const tools = ['read', 'sandbox_exec', 'mcp__docs__query', 'other'].map(tool);
  expect(
    pluginAgentTools({ tools: ['Read', 'mcp__docs__*'], allowedTools: ['mcp__docs__query'] }, tools).map(
      (t) => t.name,
    ),
  ).toEqual(['mcp__docs__query']);
  expect(pluginAgentTools({ tools: [] }, tools)).toEqual([]);
  expect(pluginAgentTools({ allowedTools: ['unknown'] }, tools)).toEqual([]);
  expect(pluginAgentTools({ tools: ['Bash'] }, tools).map((t) => t.name)).toEqual(['sandbox_exec']);
});

it('dispatches a verified plugin Agent from the production parent Pi loop and returns its real tool result', async () => {
  const root = await mkdtemp(join(tmpdir(), 'workdude-plugin-dispatch-'));
  const agentPath = join(root, 'docs.md');
  const bytes = Buffer.from(
    '---\nname: docs-researcher\ndescription: Fetch docs.\ntools: query_docs\nmodel: sonnet\n---\nUse query_docs to look up documentation.',
  );
  await writeFile(agentPath, bytes);
  let tamperOnRequest = false;
  const gateway = await startGatewayLoopback({
    toolCallUsage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
    response: async ({ messages }) => {
      if (tamperOnRequest) {
        tamperOnRequest = false;
        await writeFile(agentPath, Buffer.alloc(bytes.length, 32));
      }
      const child = messages.some(
        (message) => message.role === 'user' && JSON.stringify(message.content).includes('CHILD_TASK'),
      );
      return child
        ? { content: 'CHILD-DOC-RESULT', externalToolCall: { name: 'query_docs', arguments: {} } }
        : {
            content: 'PARENT-FINAL-RESULT',
            externalToolCall: {
              name: 'plugin_agent',
              arguments: { agent: 'docs:docs-researcher', task: 'CHILD_TASK' },
            },
          };
    },
  });
  const events: Array<{ type: string; payload: Record<string, unknown> }> = [];
  let calls = 0;
  const query = tool('query_docs');
  const runtime = new ProductAgentRuntime({
    aiGateway: {
      baseUrl: gateway.baseUrl,
      masterKey: 'synthetic-key',
      model: 'authorized-model',
      requestTimeoutMs: 5000,
    },
    agentDir: join(root, 'agent'),
    enableTools: false,
    sandbox: {
      create: async () => {
        throw new Error('unexpected sandbox');
      },
      exec: async () => {
        throw new Error('unexpected command');
      },
      destroy: async () => undefined,
    },
    approvals: { request: async () => 'rejected' },
    events: {
      emit: async (type, payload) => {
        events.push({ type, payload });
      },
    },
    externalTools: [
      {
        ...query,
        execute: async (...args) => {
          calls++;
          return query.execute(...args);
        },
      },
    ],
    skillDirectories: [
      {
        pluginName: 'docs',
        directoryPath: root,
        agentPaths: [agentPath],
        files: [
          {
            path: agentPath,
            sizeBytes: bytes.length,
            sha256: createHash('sha256').update(bytes).digest('hex'),
            mediaType: 'text/markdown',
          },
        ],
      },
    ],
  });
  try {
    const result = await runtime.run({
      runId: '11111111-1111-4111-8111-111111111111',
      prompt: 'PARENT_TASK',
      workspacePath: join(root, 'workspace'),
      sessionPath: join(root, 'parent.jsonl'),
    });
    expect(result.resultText).toBe('PARENT-FINAL-RESULT');
    expect(result.usage).toMatchObject({ inputTokens: 20, outputTokens: 14, totalTokens: 34 });
    expect(calls).toBe(1);
    const payloads = gateway.requests.map((request) => JSON.parse(request.body));
    expect(payloads).toHaveLength(4);
    expect(payloads.every((payload) => payload.model === 'authorized-model')).toBe(true);
    expect(payloads[1].tools.map((t: { function: { name: string } }) => t.function.name)).toEqual([
      'query_docs',
    ]);
    expect(JSON.stringify(payloads[2].messages)).toContain('DOCUMENT-EVIDENCE');
    expect(JSON.stringify(payloads[3].messages)).toContain('CHILD-DOC-RESULT');
    expect(
      events.some(
        (event) => event.type === 'tool.updated' && JSON.stringify(event.payload).includes('query_docs'),
      ),
    ).toBe(true);
    expect(events.filter((event) => event.type === 'usage.updated').at(-1)?.payload.usage).toMatchObject({
      totalTokens: 34,
    });
    const activity = projectRunActivity(
      events.map((event, index) => ({
        ...event,
        id: String(index),
        sequence: index + 1,
        runId: 'parent',
        workspaceId: 'test',
        correlationId: 'test',
        occurredAt: '2026-09-24T00:00:00Z',
      })),
    );
    const childActivity = activity.tools.find((tool) => tool.name === 'plugin_agent')?.pluginAgent;
    expect(childActivity?.status).toBe('completed');
    expect(childActivity?.text).toBe('CHILD-DOC-RESULT');
    expect(childActivity?.tools.map((tool) => [tool.name, tool.state])).toEqual([
      ['query_docs', 'completed'],
    ]);
    const recovered = await runtime.run({
      runId: '11111111-1111-4111-8111-111111111111',
      prompt: 'PARENT_TASK',
      workspacePath: join(root, 'workspace'),
      sessionPath: join(root, 'parent.jsonl'),
      recovery: true,
    });
    expect(recovered).toEqual(result);
    expect(calls).toBe(1);
    expect(gateway.requests).toHaveLength(4);
    expect(await readFile(agentPath)).toEqual(bytes);
    await writeFile(agentPath, Buffer.alloc(bytes.length, 32));
    await expect(
      runtime.run({
        runId: '22222222-2222-4222-8222-222222222222',
        prompt: 'PARENT_TASK',
        workspacePath: join(root, 'workspace'),
        sessionPath: join(root, 'tampered.jsonl'),
      }),
    ).rejects.toThrow('checksum mismatch');
    expect(gateway.requests).toHaveLength(4);
    await writeFile(agentPath, bytes);
    tamperOnRequest = true;
    await runtime.run({
      runId: '33333333-3333-4333-8333-333333333333',
      prompt: 'PARENT_TASK',
      workspacePath: join(root, 'workspace'),
      sessionPath: join(root, 'changed-after-discovery.jsonl'),
    });
    expect(calls).toBe(1);
    expect(gateway.requests).toHaveLength(6);
    expect(gateway.requests[5]!.body).toContain('checksum mismatch');
  } finally {
    await gateway.close();
    await rm(root, { recursive: true, force: true });
  }
});
