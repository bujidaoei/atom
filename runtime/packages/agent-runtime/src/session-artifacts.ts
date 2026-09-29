import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { access, copyFile, mkdir, realpath, stat } from 'node:fs/promises';
import { basename, extname, isAbsolute, join, parse, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Type } from 'typebox';

import type { ToolDefinition } from './pi-runtime-types.ts';

export const PRESENT_FILES_TOOL_NAME = 'mcp__plugin_wake_mcp_adapter__present_files';

export const SESSION_ARTIFACTS_OUTPUT_STYLE = [
  '# Session artifacts',
  '',
  'Only when `present_files` is available and the current session permits its user-delivery channel: when you create files the user should see, including reports, presentations, PDFs, images, archives, openable HTML, or other deliverables, call the `present_files` MCP tool before your final response.',
  '',
  'When your answer delivers code changes in the current worktree and that tool is permitted, also call `present_files` before the final response so the current worktree diff is registered.',
  '',
  'Use `files[].file_path` for explicit file paths. The tool will copy allowed files into the active `_output` directory when needed and includes the current worktree diff by default.',
  '',
  'If a higher-priority scenario protocol defines a canonical participant transport or says `present_files` is unavailable, follow that protocol and do not call `present_files`. In a managed Conversation Run, use canonical Conversation Message attachments instead.',
  '',
].join('\n');

export type SessionArtifactType = 'presentation' | 'document' | 'media' | 'archive' | 'other';

const MIME_TYPES: Readonly<Record<string, string>> = {
  '.ppt': 'application/vnd.ms-powerpoint',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.pps': 'application/vnd.ms-powerpoint',
  '.ppsx': 'application/vnd.openxmlformats-officedocument.presentationml.slideshow',
  '.pdf': 'application/pdf',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.odt': 'application/vnd.oasis.opendocument.text',
  '.rtf': 'application/rtf',
  '.md': 'text/markdown',
  '.txt': 'text/plain',
  '.html': 'text/html',
  '.htm': 'text/html',
  '.epub': 'application/epub+zip',
  '.xls': 'application/vnd.ms-excel',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
  '.csv': 'text/csv',
  '.tsv': 'text/tab-separated-values',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.bmp': 'image/bmp',
  '.ico': 'image/x-icon',
  '.tiff': 'image/tiff',
  '.heic': 'image/heic',
  '.svg': 'image/svg+xml',
  '.drawio': 'application/xml',
  '.mmd': 'text/plain',
  '.mermaid': 'text/plain',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.m4a': 'audio/mp4',
  '.ogg': 'audio/ogg',
  '.opus': 'audio/ogg',
  '.mp4': 'video/mp4',
  '.mov': 'video/quicktime',
  '.webm': 'video/webm',
  '.zip': 'application/zip',
  '.tar': 'application/x-tar',
  '.gz': 'application/gzip',
  '.tgz': 'application/gzip',
  '.diff': 'text/x-diff',
  '.patch': 'text/x-diff',
};

const FILE_TYPES: Readonly<Record<string, SessionArtifactType>> = {
  '.ppt': 'presentation',
  '.pptx': 'presentation',
  '.pps': 'presentation',
  '.ppsx': 'presentation',
  '.pdf': 'document',
  '.doc': 'document',
  '.docx': 'document',
  '.odt': 'document',
  '.rtf': 'document',
  '.md': 'document',
  '.txt': 'document',
  '.html': 'document',
  '.htm': 'document',
  '.epub': 'document',
  '.xls': 'document',
  '.xlsx': 'document',
  '.ods': 'document',
  '.csv': 'document',
  '.tsv': 'document',
  '.png': 'media',
  '.jpg': 'media',
  '.jpeg': 'media',
  '.gif': 'media',
  '.webp': 'media',
  '.bmp': 'media',
  '.ico': 'media',
  '.tiff': 'media',
  '.heic': 'media',
  '.svg': 'media',
  '.drawio': 'document',
  '.mmd': 'document',
  '.mermaid': 'document',
  '.mp3': 'media',
  '.wav': 'media',
  '.m4a': 'media',
  '.ogg': 'media',
  '.opus': 'media',
  '.mp4': 'media',
  '.mov': 'media',
  '.webm': 'media',
  '.zip': 'archive',
  '.tar': 'archive',
  '.gz': 'archive',
  '.tgz': 'archive',
};

export function sessionArtifactMediaType(path: string): string {
  return MIME_TYPES[extname(path).toLowerCase()] ?? 'application/octet-stream';
}

export function inferSessionArtifactType(path: string): SessionArtifactType {
  return FILE_TYPES[extname(path).toLowerCase()] ?? 'other';
}

export interface SessionArtifactFile {
  absolutePath: string;
  relativePath: string;
  mediaType: string;
  artifactType: SessionArtifactType;
  title: string;
  description: string | null;
  toolName: string | null;
}

/** Host persistence for files a Run produced; implemented by the Cloud Worker and Desktop host. */
export interface SessionArtifactSink {
  conversationId: string;
  recordProcessFile(file: SessionArtifactFile): Promise<void>;
  presentFile(file: SessionArtifactFile): Promise<void>;
}

export function sessionArtifactOutputDir(workspacePath: string, conversationId: string): string {
  return join(workspacePath, conversationId, '_output');
}

function isPathInside(candidate: string, root: string): boolean {
  const path = relative(root, candidate);
  return path === '' || (!!path && !path.startsWith('..') && !isAbsolute(path));
}

function sha256File(path: string): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const hash = createHash('sha256');
    createReadStream(path)
      .on('data', (chunk) => hash.update(chunk))
      .on('error', reject)
      .on('end', () => resolvePromise(hash.digest('hex')));
  });
}

async function identicalTargetHash(source: string, target: string): Promise<string | undefined> {
  try {
    const [sourceStats, targetStats] = await Promise.all([stat(source), stat(target)]);
    if (!targetStats.isFile() || sourceStats.size !== targetStats.size) return undefined;
    const sourceHash = await sha256File(source);
    return sourceHash === (await sha256File(target)) ? sourceHash : undefined;
  } catch {
    return undefined;
  }
}

async function nonConflictingPath(outputDir: string, fileName: string): Promise<string> {
  const parsed = parse(fileName);
  let candidate = join(outputDir, fileName);
  for (let suffix = 2; ; suffix += 1) {
    try {
      await access(candidate);
      candidate = join(outputDir, `${parsed.name}-${suffix}${parsed.ext}`);
    } catch {
      return candidate;
    }
  }
}

export interface PresentedSessionFile {
  type: SessionArtifactType;
  title: string;
  outputPath: string;
  copied: boolean;
}

/** Copies an allowed workspace file into `_output` following the observed official rules. */
export async function presentSessionFile(input: {
  workspacePath: string;
  outputDir: string;
  filePath: string;
  title?: string | undefined;
  description?: string | undefined;
  artifactType?: SessionArtifactType | undefined;
}): Promise<{ presented: PresentedSessionFile; file: SessionArtifactFile }> {
  const trimmed = input.filePath.trim();
  if (!trimmed) throw new Error('file_path is required');
  await mkdir(input.outputDir, { recursive: true });
  const [realTargetDir, realOutputDir] = await Promise.all([
    realpath(input.workspacePath),
    realpath(input.outputDir),
  ]);
  const candidate = await realpath(isAbsolute(trimmed) ? trimmed : resolve(input.workspacePath, trimmed));
  if (!isPathInside(candidate, realTargetDir) && !isPathInside(candidate, realOutputDir)) {
    throw new Error(
      `file is outside the session target directory (allowed: targetDir=${realTargetDir}, outputDir=${realOutputDir}); please write the file inside one of these directories before calling present_files`,
    );
  }
  if (!(await stat(candidate)).isFile()) throw new Error('directories are not supported as artifacts');
  let outputPath = candidate;
  let copied = false;
  if (!isPathInside(candidate, realOutputDir)) {
    const direct = join(realOutputDir, basename(candidate));
    if (await identicalTargetHash(candidate, direct)) {
      outputPath = direct;
    } else {
      outputPath = await nonConflictingPath(realOutputDir, basename(candidate));
      await copyFile(candidate, outputPath);
    }
    copied = true;
  }
  const type = input.artifactType ?? inferSessionArtifactType(outputPath);
  const title = input.title?.trim() || basename(outputPath);
  const description = input.description?.trim() || null;
  return {
    presented: { type, title, outputPath, copied },
    file: {
      absolutePath: outputPath,
      relativePath: relative(realOutputDir, await realpath(outputPath)).replaceAll('\\', '/'),
      mediaType: sessionArtifactMediaType(outputPath),
      artifactType: type,
      title: title.slice(0, 255),
      description: description ? description.slice(0, 2_000) : null,
      toolName: null,
    },
  };
}

/** Extensions the official CLI auto-presents when the final reply links a local file. */
const LINKED_FILE_EXTENSIONS = new Set([
  '.md',
  '.markdown',
  '.pdf',
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.html',
  '.doc',
  '.docx',
  '.xls',
  '.xlsx',
  '.ppt',
  '.pptx',
]);

function localLinkPath(href: string, workspacePath: string): string | undefined {
  const target = href.trim().replace(/^<|>$/gu, '');
  if (/^file:/iu.test(target)) {
    try {
      const url = new URL(target);
      if (url.hostname && url.hostname.toLowerCase() !== 'localhost') return undefined;
      if (url.search || url.hash) return undefined;
      return fileURLToPath(url);
    } catch {
      return undefined;
    }
  }
  const windowsDrive = /^[a-z]:[\\/]/iu.test(target);
  if (
    !target ||
    target.includes('\0') ||
    target.includes('?') ||
    target.includes('#') ||
    target.startsWith('//') ||
    (!windowsDrive && /^[a-z][a-z\d+.-]*:/iu.test(target))
  ) {
    return undefined;
  }
  let decoded: string;
  try {
    decoded = decodeURIComponent(target);
  } catch {
    return undefined;
  }
  return isAbsolute(decoded) ? decoded : resolve(workspacePath, decoded);
}

/** Local file targets of Markdown links and images, in document order. */
export function markdownLocalFileTargets(markdown: string, workspacePath: string): string[] {
  const targets: string[] = [];
  for (const match of markdown.matchAll(/!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^)\s]+)(?:\s+"[^"\n]*")?\s*\)/gu)) {
    const path = localLinkPath(match[1]!, workspacePath);
    if (path && LINKED_FILE_EXTENSIONS.has(extname(path).toLowerCase()) && !targets.includes(path)) {
      targets.push(path);
    }
  }
  return targets;
}

/**
 * Official CLI behaviour: files the final reply links inside the session
 * workspace are delivered to the user as artifacts even without a
 * `present_files` call. Paths outside the workspace are ignored.
 */
export async function presentLinkedSessionFiles(input: {
  markdown: string;
  workspacePath: string;
  sink: SessionArtifactSink;
}): Promise<number> {
  const outputDir = sessionArtifactOutputDir(input.workspacePath, input.sink.conversationId);
  let delivered = 0;
  for (const filePath of markdownLocalFileTargets(input.markdown, input.workspacePath)) {
    try {
      const { file } = await presentSessionFile({ workspacePath: input.workspacePath, outputDir, filePath });
      await input.sink.presentFile(file);
      delivered += 1;
    } catch {
      continue;
    }
  }
  return delivered;
}

const PresentFilesParameters = Type.Object(
  {
    files: Type.Optional(
      Type.Array(
        Type.Object(
          {
            file_path: Type.String(),
            title: Type.Optional(Type.String()),
            description: Type.Optional(Type.String()),
            artifactType: Type.Optional(
              Type.Union([
                Type.Literal('presentation'),
                Type.Literal('document'),
                Type.Literal('media'),
                Type.Literal('archive'),
                Type.Literal('other'),
              ]),
            ),
          },
          { additionalProperties: false },
        ),
        { maxItems: 50 },
      ),
    ),
  },
  { additionalProperties: false },
);

export function createPresentFilesTool(options: {
  workspacePath: string;
  sink: SessionArtifactSink;
}): ToolDefinition<typeof PresentFilesParameters> {
  const outputDir = sessionArtifactOutputDir(options.workspacePath, options.sink.conversationId);
  return {
    name: PRESENT_FILES_TOOL_NAME,
    label: PRESENT_FILES_TOOL_NAME,
    description: [
      'Present files to the user after creating files the user should see.',
      'Use this before the final response when you created deliverable files, reports, presentations, PDFs, images, archives, openable HTML, or code changes.',
      'Files are copied into the active _output directory only for _output targets, and git targets register the current worktree changed-file list by default.',
    ].join(' '),
    parameters: PresentFilesParameters,
    executionMode: 'sequential',
    async execute(_toolCallId, params, signal) {
      signal?.throwIfAborted();
      const presented: PresentedSessionFile[] = [];
      const rejected: Array<{ path: string; reason: string }> = [];
      for (const requested of params.files ?? []) {
        signal?.throwIfAborted();
        try {
          const result = await presentSessionFile({
            workspacePath: options.workspacePath,
            outputDir,
            filePath: requested.file_path,
            title: requested.title,
            description: requested.description,
            artifactType: requested.artifactType,
          });
          await options.sink.presentFile(result.file);
          presented.push(result.presented);
        } catch (error) {
          rejected.push({
            path: requested.file_path,
            reason: error instanceof Error ? error.message : String(error),
          });
        }
      }
      const body = {
        success: rejected.length === 0,
        manifestUpdated: presented.length > 0,
        target: {
          mode: 'default_session',
          agentCwd: options.workspacePath,
          targetDir: options.workspacePath,
          outputDir,
        },
        outputDir,
        presented,
        fileChanges: { written: presented.length, truncated: false },
        codeChanges: { generated: false, reason: 'target is not a git repository' },
        rejected,
      };
      return {
        content: [{ type: 'text' as const, text: JSON.stringify(body, null, 2) }],
        details: body,
        ...(presented.length === 0 && rejected.length > 0 ? { isError: true } : {}),
      };
    },
  };
}
