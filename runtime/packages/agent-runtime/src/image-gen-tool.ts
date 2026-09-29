import { randomBytes } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

import { Type } from 'typebox';

import type { ApprovalAdapter } from '../../product-contracts/src/index.ts';
import type { SessionArtifactSink } from './session-artifacts.ts';
import type { EnterpriseAiGatewayConfiguration } from './enterprise-ai-gateway.ts';
import type { ToolDefinition } from './pi-runtime-types.ts';
import type { ToolPolicyEvaluator, ToolPolicyEvidence } from './tool-policy.ts';

const MAX_GENERATED_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_IMAGE_RESPONSE_BYTES = 12 * 1024 * 1024;

const ImageGenParameters = Type.Object(
  {
    name: Type.Optional(Type.String({ minLength: 1, maxLength: 80 })),
    prompt: Type.String({ minLength: 1, maxLength: 4_000 }),
    size: Type.Optional(
      Type.Union([Type.Literal('1024x1024'), Type.Literal('1024x1536'), Type.Literal('1536x1024')]),
    ),
  },
  { additionalProperties: false },
);

export const PRIVATE_WAKER_IMAGE_GUIDANCE =
  'When the user asks to create, draw, design, or edit an image, call ImageGen. Do not claim an image was created unless ImageGen returned one.';

export const IMAGE_ARTIFACT_GUIDANCE =
  'After ImageGen saves an image, call `mcp__plugin_wake_mcp_adapter__present_files` with the saved file_path, a short title and a one-sentence description before your final response, so the user receives the image as an artifact. Do not embed the local file path in your reply.';

export interface ImageGenToolOptions {
  gateway: EnterpriseAiGatewayConfiguration;
  runId: string;
  workspacePath: string;
  approvals: ApprovalAdapter;
  policy?: ToolPolicyEvaluator;
  onPolicyDecision?: (evidence: ToolPolicyEvidence) => Promise<void>;
  fetchImplementation?: typeof fetch;
  artifacts?: SessionArtifactSink;
  now?: () => number;
}

const IMAGE_EXTENSIONS: Readonly<Record<string, string>> = {
  'image/png': '.png',
  'image/jpeg': '.jpg',
  'image/webp': '.webp',
  'image/gif': '.gif',
};

export function generatedImageFileStem(name: string | undefined, prompt: string): string {
  const source = (name ?? prompt)
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_-]+/gu, '-')
    .replace(/^-+|-+$/gu, '')
    .slice(0, name ? 60 : 32)
    .replace(/-+$/gu, '');
  return source || 'image';
}

async function generatedImageBytes(
  image: GeneratedImagePart,
  fetchImplementation: typeof fetch,
  signal: AbortSignal,
): Promise<Buffer> {
  if (image.data) return Buffer.from(image.data, 'base64');
  const response = await fetchImplementation(image.url!, { redirect: 'error', signal });
  if (!response.ok) {
    await response.body?.cancel().catch(() => undefined);
    throw new Error(`Generated image download failed with HTTP ${response.status}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.byteLength < 1 || bytes.byteLength > MAX_GENERATED_IMAGE_BYTES) {
    throw new Error('AI gateway image generation returned an image of an unsupported size');
  }
  return bytes;
}

/** Pi tool-result content part carrying one generated image (inline base64 or HTTPS URL). */
export type GeneratedImagePart = {
  type: 'image';
  mimeType: string;
  data?: string;
  url?: string;
};

export function imageGenerationModels(payload: unknown): string[] {
  if (!payload || typeof payload !== 'object' || !Array.isArray((payload as { data?: unknown }).data))
    return [];
  return (payload as { data: unknown[] }).data.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const record = item as { id?: unknown; mode?: unknown; model_info?: { mode?: unknown } };
    const mode = typeof record.mode === 'string' ? record.mode : record.model_info?.mode;
    if (mode !== 'image_generation' || typeof record.id !== 'string' || !record.id.trim()) return [];
    return [record.id];
  });
}

export function selectImageGenerationModel(models: readonly string[], preferred: string): string {
  if (models.includes(preferred)) return preferred;
  const selected = models[0];
  if (!selected) throw new Error('AI gateway has no image generation model');
  return selected;
}

export function generatedImagesFromGatewayPayload(payload: unknown): GeneratedImagePart[] {
  if (!payload || typeof payload !== 'object' || !Array.isArray((payload as { data?: unknown }).data)) {
    throw new Error('AI gateway image generation returned no image');
  }
  const images = (payload as { data: unknown[] }).data.flatMap((item): GeneratedImagePart[] => {
    if (!item || typeof item !== 'object') return [];
    const record = item as { b64_json?: unknown; url?: unknown };
    if (typeof record.b64_json === 'string') {
      const data = record.b64_json.replace(/\s/gu, '');
      if (!/^[A-Za-z0-9+/=]+$/u.test(data)) return [];
      const bytes = Buffer.from(data, 'base64');
      if (bytes.byteLength < 1 || bytes.byteLength > MAX_GENERATED_IMAGE_BYTES) {
        throw new Error('AI gateway image generation returned an image of an unsupported size');
      }
      return [{ type: 'image' as const, mimeType: imageMimeType(bytes), data }];
    }
    if (typeof record.url === 'string' && record.url.startsWith('https://') && record.url.length <= 2_000) {
      return [{ type: 'image' as const, mimeType: 'image/png', url: record.url }];
    }
    return [];
  });
  if (!images.length) throw new Error('AI gateway image generation returned no image');
  return images;
}

function imageMimeType(bytes: Buffer): string {
  if (bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    return 'image/png';
  }
  if (bytes.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]))) return 'image/jpeg';
  if (
    bytes.subarray(0, 4).toString('ascii') === 'RIFF' &&
    bytes.subarray(8, 12).toString('ascii') === 'WEBP'
  ) {
    return 'image/webp';
  }
  if (
    bytes.subarray(0, 6).toString('ascii') === 'GIF87a' ||
    bytes.subarray(0, 6).toString('ascii') === 'GIF89a'
  ) {
    return 'image/gif';
  }
  return 'image/png';
}

async function readBoundedJson(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('AI gateway image generation returned an empty body');
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const next = await reader.read();
    if (next.done) break;
    total += next.value.byteLength;
    if (total > MAX_IMAGE_RESPONSE_BYTES) {
      await reader.cancel().catch(() => undefined);
      throw new Error('AI gateway image generation response exceeded 12 MiB');
    }
    chunks.push(next.value);
  }
  const body = Buffer.concat(chunks).toString('utf8');
  if (!body) throw new Error('AI gateway image generation returned an empty body');
  try {
    return JSON.parse(body) as unknown;
  } catch {
    throw new Error('AI gateway image generation returned malformed JSON');
  }
}

export function createImageGenTool(options: ImageGenToolOptions): ToolDefinition<typeof ImageGenParameters> {
  const fetchImplementation = options.fetchImplementation ?? fetch;
  return {
    name: 'ImageGen',
    label: '生成图片',
    description:
      '创建或编辑图片。用户要求生成、绘制、设计或修改图片时调用。只根据本工具返回的图片作答，不要声称未实际生成的图片已经完成。',
    promptSnippet: '用 ImageGen 创建或编辑图片',
    promptGuidelines: options.artifacts
      ? [PRIVATE_WAKER_IMAGE_GUIDANCE, IMAGE_ARTIFACT_GUIDANCE]
      : [PRIVATE_WAKER_IMAGE_GUIDANCE],
    parameters: ImageGenParameters,
    executionMode: 'sequential',
    async execute(toolCallId, params, signal) {
      signal?.throwIfAborted();
      const policyInput = {
        tool: 'ImageGen',
        operation: 'execute' as const,
        target: options.workspacePath,
        command: params.prompt,
      };
      const policyEvidence = options.policy?.evaluateEvidence?.(policyInput);
      const policyDecision = options.policy
        ? (policyEvidence?.decision ?? options.policy.evaluate(policyInput))
        : 'allow';
      if (policyEvidence) await options.onPolicyDecision?.(policyEvidence);
      if (policyDecision === 'deny') {
        return {
          content: [{ type: 'text' as const, text: '权限策略禁止生成图片。' }],
          details: { approved: false, policyDecision },
          isError: true,
        };
      }
      if (policyDecision === 'ask') {
        const decision = await options.approvals.request({
          runId: options.runId,
          toolCallId,
          command: params.prompt,
          target: options.workspacePath,
          risk: 'execute',
          ...(policyEvidence
            ? {
                requestHash: policyEvidence.requestHash,
                ruleIds: policyEvidence.ruleIds,
                policyVersions: policyEvidence.policyVersions,
              }
            : {}),
        });
        if (decision !== 'approved') {
          return {
            content: [{ type: 'text' as const, text: '用户拒绝了图片生成。' }],
            details: { approved: false, policyDecision },
            isError: true,
          };
        }
      }
      const timeout = AbortSignal.timeout(options.gateway.requestTimeoutMs);
      const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
      const headers = {
        authorization: `Bearer ${options.gateway.masterKey}`,
        'content-type': 'application/json',
      };
      const catalog = await fetchImplementation(`${options.gateway.baseUrl}/models`, {
        method: 'GET',
        redirect: 'error',
        headers,
        signal: requestSignal,
      });
      if (!catalog.ok) {
        await catalog.body?.cancel().catch(() => undefined);
        throw new Error(`AI gateway image model discovery failed with HTTP ${catalog.status}`);
      }
      const model = selectImageGenerationModel(
        imageGenerationModels(await readBoundedJson(catalog)),
        options.gateway.model,
      );
      const response = await fetchImplementation(`${options.gateway.baseUrl}/images/generations`, {
        method: 'POST',
        redirect: 'error',
        headers,
        body: JSON.stringify({
          model,
          prompt: params.prompt,
          n: 1,
          size: params.size ?? '1024x1024',
          response_format: 'b64_json',
        }),
        signal: requestSignal,
      });
      if (!response.ok) {
        await response.body?.cancel().catch(() => undefined);
        throw new Error(`AI gateway image generation failed with HTTP ${response.status}`);
      }
      const images = generatedImagesFromGatewayPayload(await readBoundedJson(response));
      const directory = join(options.workspacePath, 'vibe_images');
      await mkdir(directory, { recursive: true });
      const stem = generatedImageFileStem(params.name, params.prompt);
      const savedPaths: string[] = [];
      for (const image of images) {
        const bytes = await generatedImageBytes(image, fetchImplementation, requestSignal);
        const mimeType = imageMimeType(bytes);
        const fileName = `${stem}_${(options.now ?? Date.now)()}_${randomBytes(4).toString('hex')}${IMAGE_EXTENSIONS[mimeType] ?? '.png'}`;
        const path = join(directory, fileName);
        await writeFile(path, bytes, { flag: 'wx' });
        savedPaths.push(path);
        await options.artifacts?.recordProcessFile({
          absolutePath: path,
          relativePath: `vibe_images/${fileName}`,
          mediaType: mimeType,
          artifactType: 'media',
          title: fileName,
          description: null,
          toolName: 'ImageGen',
        });
      }
      return {
        content: [
          {
            type: 'text' as const,
            text: savedPaths.map((path) => `Image generated successfully. Saved to: ${path}`).join('\n'),
          },
        ],
        details: {
          filePath: savedPaths[0],
          filePaths: savedPaths,
          ...(options.artifacts ? {} : { imageCount: images.length, images }),
        },
      };
    },
  };
}
