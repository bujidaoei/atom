import { stat } from 'node:fs/promises';
import { basename, isAbsolute, join, posix, relative, resolve } from 'node:path';

import type { ToolDefinition } from './pi-runtime-types.ts';
import {
  inferSessionArtifactType,
  sessionArtifactMediaType,
  type SessionArtifactSink,
} from './session-artifacts.ts';

/**
 * Official QoderWake `ToolChangeTrackerService` equivalent. The Pi gateway boundary
 * forbids extensions, so the product's own custom tool definitions are wrapped with
 * the same pre/post-tool-use semantics. Files a tool writes inside the Run
 * workspace become process files (`工作区文件`): Write/Edit by their `path`, and a
 * single `cp`/`mv` with exactly two positional paths through `sandbox_exec`.
 * ImageGen records its own output, so it is not tracked here.
 */

const PATH_TOOLS: Readonly<Record<string, string>> = { write: 'Write', edit: 'Edit' };
const SANDBOX_ROOT = '/workspace';

interface TrackedPath {
  absolutePath: string;
  toolName: string;
}

interface ToolCallEvent {
  toolName: string;
  toolCallId: string;
  input: Record<string, unknown>;
}

interface ToolResultEvent extends ToolCallEvent {
  isError: boolean;
  details?: unknown;
}

function inside(root: string, candidate: string): string | undefined {
  const distance = relative(root, candidate);
  if (!distance || distance.startsWith('..') || isAbsolute(distance)) return undefined;
  return distance.replaceAll('\\', '/');
}

function hostPath(workspacePath: string, value: string, sandboxed: boolean): string | undefined {
  const text = value.trim();
  if (!text || text.includes('\0')) return undefined;
  if (!sandboxed) return resolve(workspacePath, text);
  const normalized = posix.normalize(text.startsWith('/') ? text : posix.join(SANDBOX_ROOT, text));
  const fromRoot = posix.relative(SANDBOX_ROOT, normalized);
  if (!fromRoot || fromRoot.startsWith('..') || posix.isAbsolute(fromRoot)) return undefined;
  return join(workspacePath, ...fromRoot.split('/'));
}

/** Splits a simple shell command; returns undefined when quoting is unbalanced. */
function shellTokens(command: string): string[] | undefined {
  const tokens: string[] = [];
  let current = '';
  let quote: '"' | "'" | undefined;
  let started = false;
  for (const character of command) {
    if (quote) {
      if (character === quote) quote = undefined;
      else current += character;
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
      started = true;
    } else if (/\s/u.test(character)) {
      if (started) tokens.push(current);
      current = '';
      started = false;
    } else if (character === ';' || character === '|' || character === '&') {
      if (started) tokens.push(current);
      tokens.push(character);
      current = '';
      started = false;
    } else {
      current += character;
      started = true;
    }
  }
  if (quote) return undefined;
  if (started) tokens.push(current);
  return tokens;
}

async function isDirectory(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isDirectory();
  } catch {
    return false;
  }
}

async function copyOrMoveDestination(workspacePath: string, command: string): Promise<string | undefined> {
  const tokens = shellTokens(command);
  if (!tokens) return undefined;
  while (tokens.at(-1) === ';') tokens.pop();
  if (tokens.length < 3 || tokens.some((token) => token === '|' || token === ';' || token === '&')) {
    return undefined;
  }
  if (tokens[0] !== 'cp' && tokens[0] !== 'mv') return undefined;
  const positional = tokens.slice(1).filter((token) => token && !token.startsWith('-'));
  if (positional.length !== 2) return undefined;
  const source = hostPath(workspacePath, positional[0]!, true);
  const target = hostPath(workspacePath, positional[1]!, true);
  if (!source || !target) return undefined;
  return (await isDirectory(target)) ? join(target, basename(source)) : target;
}

async function trackedPath(workspacePath: string, event: ToolCallEvent): Promise<TrackedPath | undefined> {
  const pathTool = PATH_TOOLS[event.toolName];
  if (pathTool) {
    const value = event.input.path;
    const absolutePath = typeof value === 'string' ? hostPath(workspacePath, value, false) : undefined;
    return absolutePath ? { absolutePath, toolName: pathTool } : undefined;
  }
  if (event.toolName === 'sandbox_exec' && typeof event.input.command === 'string') {
    const absolutePath = await copyOrMoveDestination(workspacePath, event.input.command);
    return absolutePath ? { absolutePath, toolName: 'Bash' } : undefined;
  }
  return undefined;
}

function succeeded(event: ToolResultEvent): boolean {
  if (event.isError) return false;
  const details = event.details as { exitCode?: unknown; timedOut?: unknown } | undefined;
  if (event.toolName === 'sandbox_exec') return details?.exitCode === 0 && details.timedOut !== true;
  return true;
}

export function trackSessionFileChanges(
  tools: readonly ToolDefinition[],
  input: {
    workspacePath: string;
    sink: SessionArtifactSink;
    /** Workspace-relative directories owned by another recorder (the Group `shared/` mount). */
    ignoredDirectories?: readonly string[];
  },
): ToolDefinition[] {
  const workspacePath = resolve(input.workspacePath);
  const record = async (tracked: TrackedPath) => {
    const relativePath = inside(workspacePath, tracked.absolutePath);
    if (!relativePath) return;
    if (input.ignoredDirectories?.some((directory) => relativePath.startsWith(`${directory}/`))) return;
    try {
      if (!(await stat(tracked.absolutePath)).isFile()) return;
      await input.sink.recordProcessFile({
        absolutePath: tracked.absolutePath,
        relativePath,
        mediaType: sessionArtifactMediaType(tracked.absolutePath),
        artifactType: inferSessionArtifactType(tracked.absolutePath),
        title: basename(tracked.absolutePath),
        description: null,
        toolName: tracked.toolName,
      });
    } catch {
      // A file the tool reported but that vanished or cannot be published is not a change.
    }
  };
  return tools.map((tool) => {
    if (!PATH_TOOLS[tool.name] && tool.name !== 'sandbox_exec') return tool;
    return {
      ...tool,
      async execute(toolCallId, params, signal, onUpdate, context) {
        const call = { toolName: tool.name, toolCallId, input: (params ?? {}) as Record<string, unknown> };
        const tracked = await trackedPath(workspacePath, call);
        const result = await tool.execute(toolCallId, params, signal, onUpdate, context);
        if (
          tracked &&
          succeeded({
            ...call,
            isError: (result as { isError?: boolean }).isError === true,
            details: result.details,
          })
        ) {
          await record(tracked);
        }
        return result;
      },
    } as ToolDefinition;
  });
}
