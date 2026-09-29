import { stat } from 'node:fs/promises';
import { inspect } from 'node:util';

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  startGatewayLoopback,
  type GatewayLoopbackOptions,
  type LoopbackServerFixture,
} from '../../../tests/fixtures/v3/providers.ts';
import type { EnterpriseAiGatewayConfiguration } from '../src/enterprise-ai-gateway.ts';
import { ProductAgentRuntime } from '../src/product-agent-runtime.ts';
import { generateV3RoleDocuments } from '../src/v3-role-document-generation.ts';

// Controlled loopback receipts exercise the pinned Pi runtime, not a live model provider.
const credential = 'controlled-role-key';
const providerSecret = 'controlled-provider-error-secret';
const input = { name: '产品分析师', description: '分析用户反馈，给出有依据的改进建议。' };
const documents = {
  identityMd: '# 身份\n产品分析师。',
  personaMd: '# 沟通风格\n清楚、客观，并区分事实与假设。',
  bibleMd: '# 工作流程\n1. 核验资料\n2. 形成结论\n3. 给出行动建议',
};
const fields = ['identityMd', 'personaMd', 'bibleMd'] as const;
const providers: LoopbackServerFixture[] = [];

async function controlledGateway(options: GatewayLoopbackOptions = {}) {
  const provider = await startGatewayLoopback({ content: JSON.stringify(documents), ...options });
  providers.push(provider);
  const configuration: EnterpriseAiGatewayConfiguration = {
    baseUrl: provider.baseUrl,
    masterKey: credential,
    model: 'controlled-role-model',
    authorizedModels: ['controlled-role-model'],
    requestTimeoutMs: 15_000,
    requestHeaders: { 'x-workdude-role-test': 'controlled-loopback' },
  };
  return { provider, configuration };
}

async function expectSafeFailure(operation: Promise<unknown>): Promise<Error> {
  const error = await operation.then(
    () => {
      throw new Error('Generation unexpectedly succeeded');
    },
    (cause: unknown) => cause,
  );
  expect(error).toBeInstanceOf(Error);
  const visibleError = inspect(error, { depth: 8 });
  expect(visibleError).not.toContain(credential);
  expect(visibleError).not.toContain(providerSecret);
  return error as Error;
}

function blockedResponse() {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  return {
    release,
    response: async () => {
      await pending;
      return { content: JSON.stringify(documents) };
    },
  };
}

afterEach(async () => {
  vi.restoreAllMocks();
  await Promise.all(providers.splice(0).map((provider) => provider.close()));
});

describe('V3 role document generation through actual Pi / controlled loopback', () => {
  it.each(['json', 'fenced-json'])(
    'returns three trimmed documents from %s through Pi with tools absent',
    async (format) => {
      const padded = Object.fromEntries(fields.map((field) => [field, ` \n${documents[field]}\n `]));
      const json = JSON.stringify(padded);
      const { provider, configuration } = await controlledGateway({
        content: format === 'json' ? json : `\`\`\`json\n${json}\n\`\`\``,
      });
      const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');

      expect(await generateV3RoleDocuments(configuration, input)).toEqual(documents);

      expect(run).toHaveBeenCalledTimes(1);
      expect(provider.fixture).toBe(true);
      expect(provider.requests).toHaveLength(1);
      expect(provider.requests[0]).toMatchObject({
        method: 'POST',
        path: '/chat/completions',
        headers: {
          authorization: `Bearer ${credential}`,
          'x-workdude-role-test': 'controlled-loopback',
        },
      });
      const body = JSON.parse(provider.requests[0]!.body) as {
        model: string;
        stream: boolean;
        tools?: unknown[];
        messages: Array<{ role: string; content: unknown }>;
      };
      expect(body.model).toBe(configuration.model);
      expect(body.stream).toBe(true);
      expect(body.tools ?? []).toEqual([]);
      expect(body.messages.some(({ role }) => role === 'tool')).toBe(false);
      const userContent = JSON.stringify(body.messages.filter(({ role }) => role === 'user'));
      expect(userContent).toContain(input.name);
      expect(userContent).toContain(input.description);
      expect(JSON.stringify(body)).not.toContain(credential);

      const request = run.mock.calls[0]![0];
      await expect(stat(request.sessionPath)).rejects.toMatchObject({ code: 'ENOENT' });
      await expect(stat(request.workspacePath)).rejects.toMatchObject({ code: 'ENOENT' });
    },
  );

  it.each(
    fields.flatMap((field) =>
      ['missing', 'empty', 'non-string', 'oversize'].map((kind) => ({ field, kind })),
    ),
  )('rejects $kind $field instead of fabricating a role document', async ({ field, kind }) => {
    const output: Record<string, unknown> = { ...documents };
    if (kind === 'missing') delete output[field];
    if (kind === 'empty') output[field] = ' \n\t ';
    if (kind === 'non-string') output[field] = { text: documents[field] };
    if (kind === 'oversize') output[field] = '文'.repeat(100_001);
    const { provider, configuration } = await controlledGateway({ content: JSON.stringify(output) });
    const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');

    await expectSafeFailure(generateV3RoleDocuments(configuration, input));

    expect(provider.requests).toHaveLength(1);
    const request = run.mock.calls[0]![0];
    await expect(stat(request.sessionPath)).rejects.toMatchObject({ code: 'ENOENT' });
    await expect(stat(request.workspacePath)).rejects.toMatchObject({ code: 'ENOENT' });
  });

  it.each([
    { label: 'non-JSON', content: providerSecret },
    { label: 'null', content: 'null' },
    { label: 'array', content: JSON.stringify([documents]) },
    { label: 'extra field', content: JSON.stringify({ ...documents, secret: providerSecret }) },
    { label: 'surrounding prose', content: `Here is the result:\n${JSON.stringify(documents)}` },
  ])('rejects $label without echoing model output', async ({ content }) => {
    const { provider, configuration } = await controlledGateway({ content });

    await expectSafeFailure(generateV3RoleDocuments(configuration, input));

    expect(provider.requests).toHaveLength(1);
  });

  it('accepts the document and role-input limits with a responsibility description', async () => {
    const output = { ...documents, bibleMd: '文'.repeat(100_000) };
    const { provider, configuration } = await controlledGateway({ content: JSON.stringify(output) });

    expect(
      await generateV3RoleDocuments(configuration, { name: '名'.repeat(20), description: input.description }),
    ).toEqual(output);
    expect(
      await generateV3RoleDocuments(configuration, { name: input.name, description: '责'.repeat(2_000) }),
    ).toEqual(output);
    expect(await generateV3RoleDocuments(configuration, { ...input, name: ` ${input.name} ` })).toEqual(
      output,
    );

    expect(provider.requests).toHaveLength(3);
  });

  it.each([
    { name: '  ', description: input.description },
    { name: '名'.repeat(21), description: input.description },
    { name: input.name, description: '责'.repeat(2_001) },
    { name: input.name, description: '' },
    { name: input.name, description: ' \n\t ' },
  ])('rejects invalid author input before invoking Pi or the provider', async (invalidInput) => {
    const { provider, configuration } = await controlledGateway();
    const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');

    await expectSafeFailure(generateV3RoleDocuments(configuration, invalidInput));

    expect(run).not.toHaveBeenCalled();
    expect(provider.requests).toHaveLength(0);
  });

  it.each([
    { label: 'empty catalog', authorizedModels: [] },
    { label: 'array catalog', authorizedModels: ['another-model'] },
    { label: 'set catalog', authorizedModels: new Set(['another-model']) },
  ])(
    'rejects an unauthorized configured model before Pi/provider invocation ($label)',
    async ({ authorizedModels }) => {
      const { provider, configuration } = await controlledGateway();
      const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');

      await expectSafeFailure(generateV3RoleDocuments({ ...configuration, authorizedModels }, input));

      expect(run).not.toHaveBeenCalled();
      expect(provider.requests).toHaveLength(0);
    },
  );

  it('returns a safe error for a real provider-protocol authentication failure', async () => {
    const { provider, configuration } = await controlledGateway({ status: 401 });
    const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');

    const error = await expectSafeFailure(generateV3RoleDocuments(configuration, input));

    expect(inspect(error, { depth: 8 })).not.toContain('configured failure');
    expect(provider.requests).toHaveLength(1);
    await expect(stat(run.mock.calls[0]![0].sessionPath)).rejects.toMatchObject({ code: 'ENOENT' });
  });

  it('rejects an already cancelled generation without contacting Pi or the provider', async () => {
    const { provider, configuration } = await controlledGateway();
    const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');
    const controller = new AbortController();
    controller.abort();

    const error = await expectSafeFailure(generateV3RoleDocuments(configuration, input, controller.signal));

    expect(error.name).toBe('AbortError');
    expect(run).not.toHaveBeenCalled();
    expect(provider.requests).toHaveLength(0);
  });

  it('does not expose a controlled upstream error body or its nested cause', async () => {
    const { provider, configuration } = await controlledGateway({
      response: () => {
        throw new Error(`${providerSecret}: ${credential}`);
      },
    });

    await expectSafeFailure(generateV3RoleDocuments({ ...configuration, requestTimeoutMs: 1_000 }, input));

    expect(provider.requests.length).toBeGreaterThan(0);
  });

  it('propagates cancellation to the actual running Pi request and removes its temporary session', async () => {
    const blocked = blockedResponse();
    const { provider, configuration } = await controlledGateway({ response: blocked.response });
    const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');
    const controller = new AbortController();
    const failure = expectSafeFailure(generateV3RoleDocuments(configuration, input, controller.signal));
    try {
      await vi.waitFor(() => expect(provider.requests).toHaveLength(1));
      controller.abort();
      const error = await failure;

      expect(error.name).toBe('AbortError');
      const request = run.mock.calls[0]![0];
      expect(request.signal?.aborted).toBe(true);
      await expect(stat(request.sessionPath)).rejects.toMatchObject({ code: 'ENOENT' });
      await expect(stat(request.workspacePath)).rejects.toMatchObject({ code: 'ENOENT' });
      expect(provider.requests).toHaveLength(1);
    } finally {
      controller.abort();
      blocked.release();
    }
  });

  it('bounds generation by the configured timeout and aborts Pi before returning a safe failure', async () => {
    const blocked = blockedResponse();
    const { provider, configuration } = await controlledGateway({ response: blocked.response });
    const run = vi.spyOn(ProductAgentRuntime.prototype, 'run');
    const controller = new AbortController();
    const started = performance.now();
    const failure = expectSafeFailure(
      generateV3RoleDocuments({ ...configuration, requestTimeoutMs: 500 }, input, controller.signal),
    );
    try {
      await vi.waitFor(() => expect(provider.requests).toHaveLength(1));
      await failure;

      expect(performance.now() - started).toBeLessThan(3_000);
      const request = run.mock.calls[0]![0];
      expect(request.signal?.aborted).toBe(true);
      await expect(stat(request.sessionPath)).rejects.toMatchObject({ code: 'ENOENT' });
      await expect(stat(request.workspacePath)).rejects.toMatchObject({ code: 'ENOENT' });
      expect(provider.requests).toHaveLength(1);
    } finally {
      controller.abort();
      blocked.release();
    }
  });
});
