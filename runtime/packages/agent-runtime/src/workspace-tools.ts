import { createHash } from 'node:crypto';
import type { BigIntStats } from 'node:fs';
import { lstat, open, realpath } from 'node:fs/promises';
import { isAbsolute, relative, resolve } from 'node:path';

import { Type } from 'typebox';

import type { AgentRunReadableAttachment } from '../../product-contracts/src/index.ts';
import type { ToolDefinition } from './pi-runtime-types.ts';
import {
  createSandboxExecTool,
  guardSandboxOperation,
  type SandboxExecToolOptions,
} from './sandbox-tool.ts';
import { executeGuardedWorkspaceFile, runWorkspaceFileOperation } from './workspace-file-operation.ts';

const GlobParameters = Type.Object(
  {
    pattern: Type.String({ minLength: 1, maxLength: 1_000 }),
    maxResults: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
  },
  { additionalProperties: false },
);

const GrepParameters = Type.Object(
  {
    pattern: Type.String({ minLength: 1, maxLength: 2_000 }),
    path: Type.Optional(Type.String({ minLength: 1, maxLength: 1_000 })),
    glob: Type.Optional(Type.String({ minLength: 1, maxLength: 1_000 })),
    caseSensitive: Type.Optional(Type.Boolean()),
    maxResults: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
  },
  { additionalProperties: false },
);

const ReadFileParameters = Type.Object(
  {
    path: Type.String({ minLength: 1, maxLength: 2_000 }),
    startLine: Type.Optional(Type.Integer({ minimum: 1, maximum: 10_000_000 })),
    maxLines: Type.Optional(Type.Integer({ minimum: 1, maximum: 5_000 })),
    offset: Type.Optional(Type.Integer({ minimum: 1, maximum: 10_000_000 })),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 5_000 })),
  },
  { additionalProperties: false },
);

function normalizeRelativeWorkspacePath(value: string, kind: string): string {
  if (!value || value.includes('\0')) {
    throw new Error(`${kind} must be a non-empty relative workspace path.`);
  }
  const normalized = value.replaceAll('\\', '/');
  if (
    normalized.startsWith('/') ||
    /^[a-z]:\//iu.test(normalized) ||
    normalized.split('/').some((segment) => segment === '..')
  ) {
    throw new Error(`${kind} must be a relative workspace path without parent traversal.`);
  }
  return normalized;
}

function workspacePathInput(workspace: string, value: string, kind: string): string {
  if (!isAbsolute(value)) return normalizeRelativeWorkspacePath(value, kind);
  const distance = relative(resolve(workspace), resolve(value));
  if (distance === '') return '.';
  return normalizeRelativeWorkspacePath(distance, kind);
}

function sandboxRelativeFile(workspacePath: string, absolutePath: string): string {
  const distance = relative(resolve(workspacePath), resolve(absolutePath));
  if (!distance || distance.startsWith('..') || isAbsolute(distance)) {
    throw new Error('Write path must stay inside the assigned workspace.');
  }
  return distance.replaceAll('\\', '/');
}

function attachmentPathKey(path: string): string {
  const absolute = resolve(path);
  return process.platform === 'win32' ? absolute.toLocaleLowerCase('en-US') : absolute;
}

function sameFileIdentity(left: BigIntStats, right: BigIntStats): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.nlink === right.nlink &&
    left.size === right.size &&
    left.mtimeNs === right.mtimeNs &&
    left.ctimeNs === right.ctimeNs
  );
}

interface IntegrityBoundProductResource {
  path: string;
  mediaType: string;
  sizeBytes: number;
  sha256: string;
}

export interface ProductSkillDirectory {
  versionId?: string;
  pluginName?: string;
  /** Explicit package declarations; other bundled SKILL.md examples stay inactive. */
  skillPaths?: readonly string[];
  commandPaths?: readonly string[];
  agentPaths?: readonly string[];
  directoryPath: string;
  files: readonly IntegrityBoundProductResource[];
}

export async function readIntegrityBoundResource(resource: IntegrityBoundProductResource): Promise<Buffer> {
  const target = resolve(resource.path);
  const pathBefore = await lstat(target, { bigint: true });
  if (pathBefore.isSymbolicLink() || !pathBefore.isFile() || pathBefore.nlink !== 1n) {
    throw new Error('Authorized product resource must be a plain file.');
  }
  if (pathBefore.size !== BigInt(resource.sizeBytes)) {
    throw new Error('Authorized product resource size mismatch.');
  }
  const realPathBefore = await realpath(target);
  const handle = await open(target, 'r');
  try {
    const handleBefore = await handle.stat({ bigint: true });
    if (!sameFileIdentity(pathBefore, handleBefore)) {
      throw new Error('Authorized product resource identity changed before reading.');
    }
    const bytes = Buffer.allocUnsafe(resource.sizeBytes);
    let offset = 0;
    while (offset < bytes.byteLength) {
      const { bytesRead } = await handle.read(bytes, offset, bytes.byteLength - offset, offset);
      if (bytesRead === 0) throw new Error('Authorized product resource size mismatch.');
      offset += bytesRead;
    }
    const handleAfter = await handle.stat({ bigint: true });
    const pathAfter = await lstat(target, { bigint: true });
    const realPathAfter = await realpath(target);
    if (
      realPathAfter !== realPathBefore ||
      !sameFileIdentity(handleBefore, handleAfter) ||
      !sameFileIdentity(handleAfter, pathAfter)
    ) {
      throw new Error('Authorized product resource identity changed while reading.');
    }
    if (bytes.byteLength !== resource.sizeBytes) {
      throw new Error('Authorized product resource size mismatch.');
    }
    if (createHash('sha256').update(bytes).digest('hex') !== resource.sha256) {
      throw new Error('Authorized product resource checksum mismatch.');
    }
    return bytes;
  } finally {
    await handle.close();
  }
}

export type PiReadToolDefinitionFactory = (
  cwd: string,
  options: {
    autoResizeImages?: boolean;
    operations: {
      readFile(path: string): Promise<Buffer>;
      access(path: string): Promise<void>;
      detectImageMimeType?(path: string): Promise<string | null | undefined>;
    };
  },
) => ToolDefinition;

export function createProductPiReadTool(
  options: {
    workspacePath: string;
    attachments: readonly AgentRunReadableAttachment[] | (() => readonly AgentRunReadableAttachment[]);
    skillDirectories?: readonly ProductSkillDirectory[];
    workspace?: SandboxExecToolOptions;
    detectImageMimeType?: (bytes: Uint8Array) => string | null;
  },
  createReadToolDefinition: PiReadToolDefinitionFactory,
): ToolDefinition {
  const dynamicAttachments = typeof options.attachments === 'function' ? options.attachments : undefined;
  if (!dynamicAttachments && options.attachments.length > 20) {
    throw new Error('Readable conversation attachment selection is invalid.');
  }
  const resources = new Map<string, IntegrityBoundProductResource>();
  const register = (resource: IntegrityBoundProductResource, target = resources) => {
    if (
      !isAbsolute(resource.path) ||
      !resource.mediaType.trim() ||
      !Number.isSafeInteger(resource.sizeBytes) ||
      resource.sizeBytes < 0 ||
      resource.sizeBytes > 50 * 1024 * 1024 ||
      !/^[a-f0-9]{64}$/u.test(resource.sha256)
    ) {
      throw new Error('Readable product resource metadata is invalid.');
    }
    const key = attachmentPathKey(resource.path);
    if (target.has(key)) throw new Error('Readable product resource path is duplicated.');
    target.set(key, { ...resource, path: resolve(resource.path) });
  };
  for (const attachment of typeof options.attachments === 'function' ? [] : options.attachments) {
    register(attachment);
  }
  let skillFileCount = 0;
  for (const skill of options.skillDirectories ?? []) {
    if (
      !isAbsolute(skill.directoryPath) ||
      !skill.files.length ||
      skill.files.length > (skill.pluginName ? 10_000 : 2_000)
    ) {
      throw new Error('Readable Skill directory metadata is invalid.');
    }
    const root = resolve(skill.directoryPath);
    for (const file of skill.files) {
      const distance = relative(root, resolve(file.path));
      if (!distance || distance.startsWith('..') || isAbsolute(distance)) {
        throw new Error('Readable Skill file is outside its materialized directory.');
      }
      register(file);
      skillFileCount += 1;
      if (skillFileCount > 20_000) throw new Error('Readable Skill file count exceeds policy.');
    }
  }
  if (!resources.size && !dynamicAttachments && !options.workspace)
    throw new Error('Pi Read requires at least one authorized product resource.');
  const metadata = createReadToolDefinition(options.workspacePath, {
    autoResizeImages: false,
    operations: {
      access: async () => {
        throw new Error('Read operations require an active tool call.');
      },
      readFile: async () => {
        throw new Error('Read operations require an active tool call.');
      },
    },
  });
  return {
    ...metadata,
    executionMode: 'parallel',
    async execute(toolCallId, rawParams, signal, onUpdate, context) {
      signal?.throwIfAborted();
      const rawPath = (rawParams as { path?: unknown }).path;
      if (typeof rawPath !== 'string' || !rawPath || rawPath.includes('\0')) {
        throw new Error('Pi Read requires an authorized product resource path.');
      }
      const target = isAbsolute(rawPath) ? resolve(rawPath) : resolve(options.workspacePath, rawPath);
      const currentResources = dynamicAttachments ? new Map(resources) : resources;
      if (dynamicAttachments) {
        const attachments = dynamicAttachments();
        if (attachments.length + resources.size > 20_000)
          throw new Error('Readable product resource count exceeds policy.');
        for (const attachment of attachments) register(attachment, currentResources);
      }
      const resource = currentResources.get(attachmentPathKey(target));
      let readBytes: () => Promise<Buffer>;
      if (resource) {
        readBytes = () => readIntegrityBoundResource(resource);
      } else {
        const workspace = options.workspace;
        if (!workspace) throw new Error('Pi Read path is not an authorized product resource.');
        const path = sandboxRelativeFile(workspace.workspacePath, target);
        const blocked = await guardSandboxOperation(
          workspace,
          toolCallId,
          {
            tool: 'Read',
            operation: 'read',
            target,
            command: `read ${path}`,
            timeoutMs: 30_000,
            deniedMessage: '权限策略禁止读取该工作区文件。',
            rejectedMessage: '用户拒绝了该工作区文件读取。',
          },
          signal,
        );
        if (blocked) return blocked;
        readBytes = () => readSandboxFile(workspace, toolCallId, target, signal);
      }
      let verifiedBytes: Promise<Buffer> | undefined;
      const read = () => (verifiedBytes ??= readBytes());
      const definition = createReadToolDefinition(options.workspacePath, {
        autoResizeImages: false,
        operations: {
          access: async () => {
            await read();
          },
          readFile: async () => Buffer.from(await read()),
          detectImageMimeType: async () =>
            ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp'].includes(
              resource?.mediaType.trim().toLowerCase() ?? '',
            )
              ? resource!.mediaType.trim().toLowerCase()
              : resource
                ? undefined
                : options.detectImageMimeType?.(await read()),
        },
      });
      return definition.execute(toolCallId, rawParams, signal, onUpdate, context);
    },
  };
}

export type PiWriteToolDefinitionFactory = (
  cwd: string,
  options: {
    operations: {
      mkdir(path: string): Promise<void>;
      writeFile(path: string, content: string): Promise<void>;
    };
  },
) => ToolDefinition;

export function createPolicyBoundPiWriteTool(
  options: SandboxExecToolOptions,
  createWriteToolDefinition: PiWriteToolDefinitionFactory,
): ToolDefinition {
  const metadata = createWriteToolDefinition(options.workspacePath, {
    operations: {
      mkdir: async () => undefined,
      writeFile: async () => {
        throw new Error('Write operations require an active tool call.');
      },
    },
  });
  return {
    ...metadata,
    executionMode: 'sequential',
    async execute(toolCallId, rawParams, signal, onUpdate, context) {
      const params = rawParams as { path: string; content: string };
      const target = resolve(options.workspacePath, params.path);
      const relativePath = sandboxRelativeFile(options.workspacePath, target);
      const blocked = await guardSandboxOperation(
        options,
        toolCallId,
        {
          tool: 'Write',
          operation: 'write',
          target,
          command: `write ${relativePath}`,
          timeoutMs: 120_000,
          deniedMessage: '权限策略禁止写入该工作区文件。',
          rejectedMessage: '用户拒绝了该工作区文件写入。',
        },
        signal,
      );
      if (blocked) return blocked;
      const definition = createWriteToolDefinition(options.workspacePath, {
        operations: {
          mkdir: async () => undefined,
          writeFile: async (absolutePath, content) => {
            const sandboxPath = sandboxRelativeFile(options.workspacePath, absolutePath);
            await runWorkspaceFileOperation(options, toolCallId, { op: 'write', path: sandboxPath, content }, signal);
          },
        },
      });
      return definition.execute(toolCallId, rawParams, signal, onUpdate, context);
    },
  };
}

export type PiEditToolDefinitionFactory = (
  cwd: string,
  options: {
    operations: {
      readFile(path: string): Promise<Buffer>;
      writeFile(path: string, content: string): Promise<void>;
      access(path: string): Promise<void>;
    };
  },
) => ToolDefinition;

async function readSandboxFile(
  options: SandboxExecToolOptions,
  toolCallId: string,
  absolutePath: string,
  signal: AbortSignal | undefined,
): Promise<Buffer> {
  signal?.throwIfAborted();
  const relativePath = sandboxRelativeFile(options.workspacePath, absolutePath);
  const data = await runWorkspaceFileOperation(options, toolCallId, { op: 'read_bytes', path: relativePath }, signal);
  if (!('base64' in data)) throw new Error('Workspace read returned non-binary data.');
  return Buffer.from(data.base64, 'base64');
}

export function createPolicyBoundPiEditTool(
  options: SandboxExecToolOptions,
  createEditToolDefinition: PiEditToolDefinitionFactory,
): ToolDefinition {
  const inactive = async (): Promise<never> => {
    throw new Error('Edit operations require an active tool call.');
  };
  const metadata = createEditToolDefinition(options.workspacePath, {
    operations: { readFile: inactive, writeFile: inactive, access: inactive },
  });
  return {
    ...metadata,
    executionMode: 'sequential',
    async execute(toolCallId, rawParams, signal, onUpdate, context) {
      const params = rawParams as { path: string };
      const target = resolve(options.workspacePath, params.path);
      const relativePath = sandboxRelativeFile(options.workspacePath, target);
      const blocked = await guardSandboxOperation(
        options,
        toolCallId,
        {
          tool: 'Edit',
          operation: 'write',
          target,
          command: `edit ${relativePath}`,
          timeoutMs: 120_000,
          deniedMessage: '权限策略禁止编辑该工作区文件。',
          rejectedMessage: '用户拒绝了该工作区文件编辑。',
        },
        signal,
      );
      if (blocked) return blocked;
      const reads = new Map<string, Promise<Buffer>>();
      const readForEdit = (absolutePath: string) => {
        const key = sandboxRelativeFile(options.workspacePath, absolutePath);
        let reading = reads.get(key);
        if (!reading) {
          reading = readSandboxFile(options, toolCallId, absolutePath, signal);
          reads.set(key, reading);
        }
        return reading;
      };
      const definition = createEditToolDefinition(options.workspacePath, {
        operations: {
          access: async (absolutePath) => {
            await readForEdit(absolutePath);
          },
          readFile: readForEdit,
          writeFile: async (absolutePath, content) => {
            const sandboxPath = sandboxRelativeFile(options.workspacePath, absolutePath);
            const expected_sha256 = createHash('sha256').update(await readForEdit(absolutePath)).digest('hex');
            await runWorkspaceFileOperation(options, toolCallId, { op: 'write', path: sandboxPath, content, expected_sha256 }, signal);
          },
        },
      });
      return definition.execute(toolCallId, rawParams, signal, onUpdate, context);
    },
  };
}

function createGlobTool(options: SandboxExecToolOptions): ToolDefinition<typeof GlobParameters> {
  return {
    name: 'glob',
    label: 'Glob',
    description: '按路径模式查找分配工作区中的真实文件和目录。',
    promptSnippet: '用 Glob 模式查找工作区文件和目录',
    promptGuidelines: ['查找文件时优先使用 glob，不要通过猜测声称文件存在。'],
    parameters: GlobParameters,
    executionMode: 'parallel',
    async execute(toolCallId, params, signal) {
      const pattern = workspacePathInput(options.workspacePath, params.pattern, 'Glob pattern');
      const operation = { op: 'glob' as const, pattern, limit: params.maxResults ?? 200 };
      const command = `glob ${pattern}`;
      return executeGuardedWorkspaceFile(
        options,
        toolCallId,
        {
          tool: 'Glob',
          operation: 'read',
          target: resolve(options.workspacePath),
          command,
          timeoutMs: 30_000,
          deniedMessage: '权限策略禁止搜索工作区文件。',
          rejectedMessage: '用户拒绝了工作区文件搜索。',
        },
        operation,
        signal,
      );
    },
  };
}

function createGrepTool(options: SandboxExecToolOptions): ToolDefinition<typeof GrepParameters> {
  return {
    name: 'grep',
    label: 'Grep',
    description: '在工作区文本文件中执行真实正则搜索，并返回文件、行号和匹配内容。',
    promptSnippet: '在工作区文本文件中搜索内容',
    promptGuidelines: ['搜索文件内容时优先使用 grep，并使用返回的真实文件名和行号。'],
    parameters: GrepParameters,
    executionMode: 'parallel',
    async execute(toolCallId, params, signal) {
      const relativePath = workspacePathInput(options.workspacePath, params.path ?? '.', 'Grep path');
      const include = params.glob ? normalizeRelativeWorkspacePath(params.glob, 'Grep glob') : '';
      const operation = { op: 'grep' as const, pattern: params.pattern, path: relativePath,
        glob: include, case_sensitive: params.caseSensitive === true, limit: params.maxResults ?? 200 };
      const command = `grep ${params.pattern} ${relativePath}`;
      return executeGuardedWorkspaceFile(
        options,
        toolCallId,
        {
          tool: 'Grep',
          operation: 'read',
          target: resolve(options.workspacePath, relativePath),
          command,
          timeoutMs: 30_000,
          deniedMessage: '权限策略禁止搜索工作区内容。',
          rejectedMessage: '用户拒绝了工作区内容搜索。',
        },
        operation,
        signal,
      );
    },
  };
}

function createReadFileTool(
  options: SandboxExecToolOptions,
  resourceRead?: ToolDefinition,
): ToolDefinition<typeof ReadFileParameters> {
  return {
    name: 'read_file',
    label: 'Read',
    description: resourceRead
      ? '读取工作区内文本文件，或使用已授权技能、插件、附件的完整绝对路径读取其真实内容。其他外部路径禁止访问。'
      : '读取工作区内真实文本文件的指定行范围，禁止访问工作区外路径。',
    promptSnippet: '读取工作区内文本文件',
    promptGuidelines: ['读取文件时使用 read_file，并只引用工具真实返回的内容。'],
    parameters: ReadFileParameters,
    executionMode: 'parallel',
    async execute(toolCallId, params, signal, onUpdate, context) {
      if (params.startLine !== undefined && params.offset !== undefined && params.startLine !== params.offset ||
          params.maxLines !== undefined && params.limit !== undefined && params.maxLines !== params.limit) {
        throw new Error('Conflicting read ranges: use offset/limit or equivalent startLine/maxLines.');
      }
      const offset = params.offset ?? params.startLine;
      const limit = params.limit ?? params.maxLines;
      // Pi exposes absolute paths for verified installed resources. Reuse its
      // integrity-bound read adapter; arbitrary external paths remain denied.
      if (isAbsolute(params.path) && resourceRead) {
        return resourceRead.execute(
          toolCallId,
          {
            path: params.path,
            ...(offset === undefined ? {} : { offset }),
            ...(limit === undefined ? {} : { limit }),
          },
          signal,
          onUpdate,
          context,
        );
      }
      const relativePath = workspacePathInput(options.workspacePath, params.path, 'Read path');
      const operation = { op: 'read_lines' as const, path: relativePath, start: offset ?? 1, limit: limit ?? 2_000 };
      const command = `read ${relativePath}`;
      return executeGuardedWorkspaceFile(
        options,
        toolCallId,
        {
          tool: 'Read',
          operation: 'read',
          target: resolve(options.workspacePath, relativePath),
          command,
          timeoutMs: 30_000,
          deniedMessage: '权限策略禁止读取该工作区文件。',
          rejectedMessage: '用户拒绝了工作区文件读取。',
        },
        operation,
        signal,
      );
    },
  };
}

export function createWorkspaceTools(
  options: SandboxExecToolOptions,
  resourceRead?: ToolDefinition,
): ToolDefinition[] {
  return [
    createSandboxExecTool(options),
    createGlobTool(options),
    createGrepTool(options),
    createReadFileTool(options, resourceRead),
  ];
}
