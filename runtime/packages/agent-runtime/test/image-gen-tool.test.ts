import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';

import type { SessionArtifactFile } from '../src/session-artifacts.ts';
import {
  createImageGenTool,
  generatedImagesFromGatewayPayload,
  selectImageGenerationModel,
} from '../src/image-gen-tool.ts';

const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00]);

it('reads a gateway image generation payload', () => {
  expect(
    generatedImagesFromGatewayPayload({
      data: [{ b64_json: png.toString('base64') }],
    }),
  ).toEqual([{ type: 'image', mimeType: 'image/png', data: png.toString('base64') }]);
});

it('uses a gateway image model instead of the chat model', () => {
  expect(selectImageGenerationModel(['gpt-image-2', 'qwen-image'], 'dashscope/deepseek-v4-pro')).toBe(
    'gpt-image-2',
  );
  expect(selectImageGenerationModel(['gpt-image-2', 'gateway-image'], 'gateway-image')).toBe('gateway-image');
});

it('calls the configured gateway, saves the image under vibe_images and records a process file', async () => {
  const workspacePath = await mkdtemp(join(tmpdir(), 'image-gen-'));
  const recorded: SessionArtifactFile[] = [];
  const requests: Array<{ url: string; authorization: string; body: unknown }> = [];
  const tool = createImageGenTool({
    artifacts: {
      conversationId: '22222222-2222-4222-8222-222222222222',
      recordProcessFile: async (file) => {
        recorded.push(file);
      },
      presentFile: async () => undefined,
    },
    now: () => 1_790_078_833_814,
    gateway: {
      baseUrl: 'https://gateway.example/v1',
      masterKey: 'test-key',
      model: 'gateway-chat',
      requestTimeoutMs: 5_000,
    },
    runId: '11111111-1111-4111-8111-111111111111',
    workspacePath,
    approvals: { request: async () => 'rejected' },
    fetchImplementation: async (input, init) => {
      const url = String(input);
      requests.push({
        url,
        authorization: new Headers(init?.headers).get('authorization') ?? '',
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      if (url.endsWith('/models')) {
        return new Response(
          JSON.stringify({
            data: [
              { id: 'gateway-chat', mode: 'chat' },
              { id: 'gateway-image', mode: 'image_generation' },
            ],
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ data: [{ b64_json: png.toString('base64') }] }), { status: 200 });
    },
  });

  const result = await tool.execute(
    'call-1',
    { name: 'cat-reading', prompt: '一只在书桌前看书的猫' },
    undefined,
  );

  expect(requests).toEqual([
    {
      url: 'https://gateway.example/v1/models',
      authorization: 'Bearer test-key',
      body: null,
    },
    {
      url: 'https://gateway.example/v1/images/generations',
      authorization: 'Bearer test-key',
      body: {
        model: 'gateway-image',
        prompt: '一只在书桌前看书的猫',
        n: 1,
        size: '1024x1024',
        response_format: 'b64_json',
      },
    },
  ]);
  const [file] = recorded;
  expect(file).toMatchObject({
    relativePath: expect.stringMatching(/^vibe_images\/cat-reading_1790078833814_[0-9a-f]{8}\.png$/u),
    mediaType: 'image/png',
    artifactType: 'media',
    toolName: 'ImageGen',
  });
  expect(await readFile(file!.absolutePath)).toEqual(png);
  expect(result.content).toEqual([
    { type: 'text', text: `Image generated successfully. Saved to: ${file!.absolutePath}` },
  ]);
  expect(result.details).toEqual({ filePath: file!.absolutePath, filePaths: [file!.absolutePath] });
  expect(JSON.stringify(result)).not.toContain(png.toString('base64'));
  await rm(workspacePath, { recursive: true, force: true });
});
