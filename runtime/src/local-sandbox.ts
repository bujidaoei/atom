import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, rm, writeFile, realpath, rename, lstat, open } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { localTextCommand } from './local-file-text.ts';

import type {
  SandboxClient,
  SandboxExecRequest,
  SandboxExecResult,
  SandboxFileRequest,
  SandboxFileResult,
  WorkspaceFileOperation,
} from '../packages/product-contracts/src/index.ts';

const MAX_STREAM_BYTES = 256 * 1024;
const DEFAULT_TIMEOUT_MS = 120_000;

/**
 * Explicitly non-isolated local development adapter. File operations are
 * structured and confined, but exec still runs with the host process authority.
 */
export class LocalSandboxClient implements SandboxClient {
  private readonly sandboxes = new Map<string, string>();
  private readonly fileQueues = new Map<string, Promise<void>>();

  constructor(
    private readonly options: {
      resolveWorkspace(runId: string, workspaceId: string): string;
      shell?: string;
      shellArgs?: readonly string[];
      env?: NodeJS.ProcessEnv;
    },
  ) {}

  async create(runId: string, workspaceId: string): Promise<string> {
    const workspacePath = resolve(this.options.resolveWorkspace(runId, workspaceId));
    await mkdir(workspacePath, { recursive: true });
    const sandboxId = randomUUID();
    this.sandboxes.set(sandboxId, workspacePath);
    return sandboxId;
  }

  async exec(
    sandboxId: string,
    request: SandboxExecRequest,
    signal?: AbortSignal,
  ): Promise<SandboxExecResult> {
    signal?.throwIfAborted();
    const cwd = this.requireWorkspace(sandboxId);
    const timeoutMs = clampTimeout(request.timeoutMs);
    const shell = this.options.shell ?? defaultShell();
    const shellArgs = this.options.shellArgs ?? defaultShellArgs();

    return await new Promise<SandboxExecResult>((resolvePromise, rejectPromise) => {
      const child = spawn(shell, [...shellArgs, request.command], {
        cwd,
        env: { ...process.env, ...(process.platform === 'win32' ? { ATOM_PYTHON_EXECUTABLE: 'python' } : {}), ...this.options.env, ATOM_WORKSPACE_ROOT: cwd },
        windowsHide: true,
        detached: process.platform !== 'win32',
      });

      const stdout = new StreamCollector();
      const stderr = new StreamCollector();
      let timedOut = false;
      let settled = false;
      const killTree = () => {
        if (!child.pid) return;
        if (process.platform === 'win32') {
          // MSYS forks can leave native PPIDs pointing at an exited shim.
          // Resolve the shell's POSIX process group via its Windows PID.
          const listing = spawn(shell, ['-c', 'ps -a'], { windowsHide: true });
          let processes = '';
          listing.stdout.on('data', chunk => { processes += chunk.toString(); });
          listing.on('error', () => child.kill('SIGKILL'));
          listing.on('close', () => {
            const row = processes.split('\n').map(line => line.trim().split(/\s+/)).find(fields => Number(fields[3]) === child.pid);
            const group = Number(row?.[2]);
            if (Number.isSafeInteger(group) && group > 1) {
              const killer = spawn(shell, ['-c', `kill -KILL -- -${group}`], { windowsHide: true, stdio: 'ignore' });
              killer.on('error', () => child.kill('SIGKILL'));
            } else child.kill('SIGKILL');
          });
        } else {
          try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
        }
      };

      const timer = setTimeout(() => {
        timedOut = true;
        killTree();
      }, timeoutMs);

      const onAbort = () => {
        killTree();
      };
      signal?.addEventListener('abort', onAbort, { once: true });
      if (signal?.aborted) onAbort();

      const finish = (result: SandboxExecResult) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
        resolvePromise(result);
      };

      child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk));
      child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk));

      child.on('error', (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
        rejectPromise(error);
      });

      child.on('close', (code) => {
        finish({
          exitCode: timedOut ? 124 : (code ?? 1),
          stdout: stdout.text(),
          stderr: stderr.text(),
          timedOut,
          truncated: stdout.truncated || stderr.truncated,
        });
      });
    });
  }

  async fileOperation(
    sandboxId: string,
    request: SandboxFileRequest,
    signal?: AbortSignal,
  ): Promise<SandboxFileResult> {
    const workspacePath = this.requireWorkspace(sandboxId);
    signal?.throwIfAborted();
    const previous = this.fileQueues.get(workspacePath) ?? Promise.resolve();
    let release!: () => void;
    const current = new Promise<void>(resolve => { release = resolve; });
    this.fileQueues.set(workspacePath, current);
    await previous;
    try {
      signal?.throwIfAborted();
      this.requireWorkspace(sandboxId);
      const operation = request.operation;
      if (operation.op === 'read_bytes') {
        const bytes = await this.readWorkspaceBytes(workspacePath, operation.path);
        signal?.throwIfAborted();
        return { toolCallId: request.toolCallId, data: { base64: bytes.toString('base64'), sha256: createHash('sha256').update(bytes).digest('hex') } };
      }
      if (operation.op === 'write') {
        const data = await this.writeWorkspaceFile(sandboxId, operation, signal);
        return { toolCallId: request.toolCallId, data };
      }
      if (!Number.isInteger(operation.limit) || operation.limit < 1 || operation.limit > (operation.op === 'read_lines' ? 5000 : 500)) {
        throw new Error('Invalid workspace result limit.');
      }
      if (operation.op === 'read_lines' && (!Number.isInteger(operation.start) || operation.start < 1 || operation.start > 10000000)) {
        throw new Error('Invalid workspace line range.');
      }
      const result = await this.exec(sandboxId, { toolCallId: request.toolCallId, command: localTextCommand(operation), timeoutMs: 30_000 }, signal);
      signal?.throwIfAborted();
      if (result.timedOut || result.truncated || result.exitCode !== 0) throw new Error(result.stderr.trim() || 'Local file operation failed or exceeded its limits.');
      return { toolCallId: request.toolCallId, data: { text: result.stdout.replace(/\r?\n$/u, '') } };
    } finally {
      release();
      if (this.fileQueues.get(workspacePath) === current) this.fileQueues.delete(workspacePath);
    }
  }

  private async readWorkspaceBytes(workspacePath: string, path: string): Promise<Buffer> {
    const target = confineToWorkspace(workspacePath, path);
    confineToWorkspace(await realpath(workspacePath), await realpath(target));
    const before = await lstat(target);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size > 8 * 1024 * 1024) throw new Error('Unsafe or oversized workspace file.');
    const handle = await open(target, 'r');
    try {
      const info = await handle.stat();
      if (info.dev !== before.dev || info.ino !== before.ino || info.size !== before.size) throw new Error('Workspace file changed during open.');
      const buffer = Buffer.alloc(before.size + 1);
      let length = 0;
      while (length < buffer.length) {
        const { bytesRead } = await handle.read(buffer, length, buffer.length - length, length);
        if (!bytesRead) break;
        length += bytesRead;
      }
      if (length !== before.size) throw new Error('Workspace file changed during read.');
      return buffer.subarray(0, length);
    } finally { await handle.close(); }
  }

  private async writeWorkspaceFile(
    sandboxId: string,
    request: Extract<WorkspaceFileOperation, { op: 'write' }>,
    signal?: AbortSignal,
  ) {
    const workspacePath = this.requireWorkspace(sandboxId);
    signal?.throwIfAborted();
    if (Buffer.byteLength(request.content) > 8 * 1024 * 1024) throw new Error('Workspace file exceeds 8 MiB.');
    const target = confineToWorkspace(workspacePath, request.path);
    // Resolve every existing ancestor before creating directories through it.
    let ancestor = dirname(target);
    while (!existsSync(ancestor)) ancestor = dirname(ancestor);
    confineToWorkspace(await realpath(workspacePath), await realpath(ancestor));
    const info = await lstat(target).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
      return undefined;
    });
    if (info && (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1)) throw new Error('Sandbox writes require plain files');
    if (request.expected_sha256 !== undefined) {
      const existing = await this.readWorkspaceBytes(workspacePath, request.path);
      if (createHash('sha256').update(existing).digest('hex') !== request.expected_sha256) throw new Error('Workspace file changed before conditional write.');
    }
    await mkdir(dirname(target), { recursive: true });
    const temporary = `${target}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, request.content, { encoding: 'utf8', flag: 'wx', signal });
      signal?.throwIfAborted();
      await rename(temporary, target);
    } finally {
      await rm(temporary, { force: true });
    }
    return { bytes_written: Buffer.byteLength(request.content), sha256: createHash('sha256').update(request.content).digest('hex') };
  }

  async destroy(sandboxId: string): Promise<void> {
    this.sandboxes.delete(sandboxId);
  }

  /** Removes a run workspace from disk. Not part of the port; used by run cleanup. */
  static async purge(workspacePath: string): Promise<void> {
    await rm(workspacePath, { recursive: true, force: true });
  }

  private requireWorkspace(sandboxId: string): string {
    const workspacePath = this.sandboxes.get(sandboxId);
    if (!workspacePath) throw new Error(`Unknown sandbox: ${sandboxId}`);
    return workspacePath;
  }
}

function confineToWorkspace(workspacePath: string, candidate: string): string {
  const target = isAbsolute(candidate) ? resolve(candidate) : resolve(join(workspacePath, candidate));
  const offset = relative(workspacePath, target);
  if (offset === '..' || offset.startsWith('../') || offset.startsWith('..\\') || isAbsolute(offset)) {
    throw new Error('Sandbox writes must stay inside the workspace');
  }
  return target;
}

function clampTimeout(timeoutMs: number | undefined): number {
  if (!Number.isFinite(timeoutMs) || timeoutMs === undefined) return DEFAULT_TIMEOUT_MS;
  return Math.min(Math.max(Math.trunc(timeoutMs), 1_000), 600_000);
}

/**
 * Agents are prompted with POSIX shell conventions, so prefer bash everywhere.
 * On Windows dev machines that means Git Bash; cmd.exe is the last resort and
 * will reject most of what the agent writes.
 */
const resolvedShell = (() => {
  const configured = process.env.ATOM_SANDBOX_SHELL?.trim();
  if (configured) return { shell: configured, args: ['-lc'] as const };
  if (process.platform !== 'win32') return { shell: '/bin/bash', args: ['-lc'] as const };
  for (const candidate of windowsBashCandidates()) {
    if (existsSync(candidate)) return { shell: candidate, args: ['-lc'] as const };
  }
  return { shell: process.env.COMSPEC ?? 'cmd.exe', args: ['/d', '/s', '/c'] as const };
})();

function windowsBashCandidates(): string[] {
  const programFiles = process.env.ProgramFiles ?? 'C:\\Program Files';
  const programFilesX86 = process.env['ProgramFiles(x86)'] ?? 'C:\\Program Files (x86)';
  return [
    join(programFiles, 'Git', 'usr', 'bin', 'bash.exe'),
    join(programFilesX86, 'Git', 'usr', 'bin', 'bash.exe'),
    'D:\\bugu_software\\Git\\usr\\bin\\bash.exe',
    'C:\\Windows\\System32\\bash.exe',
  ];
}

function defaultShell(): string {
  return resolvedShell.shell;
}

function defaultShellArgs(): readonly string[] {
  return resolvedShell.args;
}

class StreamCollector {
  private readonly chunks: Buffer[] = [];
  private bytes = 0;
  truncated = false;

  push(chunk: Buffer): void {
    if (this.bytes >= MAX_STREAM_BYTES) {
      this.truncated = true;
      return;
    }
    const remaining = MAX_STREAM_BYTES - this.bytes;
    if (chunk.byteLength > remaining) {
      this.chunks.push(chunk.subarray(0, remaining));
      this.bytes = MAX_STREAM_BYTES;
      this.truncated = true;
      return;
    }
    this.chunks.push(chunk);
    this.bytes += chunk.byteLength;
  }

  text(): string {
    return Buffer.concat(this.chunks).toString('utf8');
  }
}
