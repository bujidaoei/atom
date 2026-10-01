import { createHash, randomUUID } from 'node:crypto';
import type { SandboxClient, SandboxExecRequest, SandboxExecResult, SandboxFileRequest, SandboxFileResult, WorkspaceFileData, WorkspaceFileOperation } from '../packages/product-contracts/src/index.ts';

export interface BrokerLease {
  runId: string;
  workspaceId: string;
  attemptId: string;
  grant: string;
  deadline: number;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function validData(data: unknown, operation: WorkspaceFileOperation): data is WorkspaceFileData {
  if (!record(data)) return false;
  if (operation.op === 'read_bytes') {
    if (typeof data.base64 !== 'string' || data.base64.length > 11184812 || typeof data.sha256 !== 'string') return false;
    const bytes = Buffer.from(data.base64, 'base64');
    return bytes.length <= 8 * 1024 * 1024 && bytes.toString('base64') === data.base64
      && createHash('sha256').update(bytes).digest('hex') === data.sha256;
  }
  if (operation.op === 'write') return data.bytes_written === Buffer.byteLength(operation.content)
    && typeof data.sha256 === 'string' && createHash('sha256').update(operation.content).digest('hex') === data.sha256;
  return typeof data.text === 'string' && Buffer.byteLength(data.text) <= 256 * 1024;
}

/** One trusted, already-seeded lease. No administrative secrets or local fallback. */
export class BrokerSandboxClient implements SandboxClient {
  readonly #origin: string;
  readonly #lease: Readonly<BrokerLease>;
  readonly #timeout: number;
  #state: 'new' | 'active' | 'uncertain' | 'closing' | 'closed' = 'new';
  #creation?: Promise<string>;
  #release?: Promise<void>;
  #fileTail: Promise<void> = Promise.resolve();
  #pendingFiles = 0;

  constructor(options: { baseUrl: string; lease: BrokerLease; timeoutMs?: number }) {
    let url: URL;
    try { url = new URL(options.baseUrl); } catch { throw new Error('Invalid broker origin'); }
    if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', '[::1]'].includes(url.hostname)))
        || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Invalid broker origin');
    const lease = options.lease;
    if (!lease || !/^[a-f0-9]{32}$/.test(lease.attemptId) || typeof lease.grant !== 'string'
        || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(lease.grant) || lease.grant.length > 8192
        || typeof lease.runId !== 'string' || !lease.runId || typeof lease.workspaceId !== 'string' || !lease.workspaceId
        || !Number.isSafeInteger(lease.deadline) || lease.deadline <= Date.now() / 1000) throw new Error('Invalid broker lease');
    const timeout = options.timeoutMs ?? 45_000;
    if (!Number.isInteger(timeout) || timeout < 1 || timeout > 60_000) throw new Error('Invalid broker timeout');
    this.#origin = url.origin;
    this.#lease = Object.freeze({ ...lease });
    this.#timeout = timeout;
  }

  async #request(method: string, suffix: string, body?: unknown, signal?: AbortSignal): Promise<unknown> {
    const deadline = AbortSignal.timeout(this.#timeout);
    const combined = signal ? AbortSignal.any([signal, deadline]) : deadline;
    try {
      const encoded = body === undefined ? undefined : JSON.stringify(body);
      if (encoded !== undefined && Buffer.byteLength(encoded) > 50 * 1024 * 1024) throw new Error('Broker request too large');
      const response = await fetch(`${this.#origin}/v1/attempts/${this.#lease.attemptId}${suffix}`, {
        method, redirect: 'error', credentials: 'omit', signal: combined,
        headers: { authorization: `Bearer ${this.#lease.grant}`, ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
        body: encoded,
      });
      if (!response.ok) {
        await response.body?.cancel();
        throw new Error('Broker request rejected');
      }
      if (response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
        await response.body?.cancel();
        throw new Error('Invalid broker response');
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error('Missing broker response');
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > 12 * 1024 * 1024) throw new Error('Broker response too large');
          chunks.push(value);
        }
        combined.throwIfAborted();
        return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    } catch { throw new Error('Broker request failed or outcome is unknown'); }
  }

  async create(runId: string, workspaceId: string): Promise<string> {
    if (runId !== this.#lease.runId || workspaceId !== this.#lease.workspaceId) throw new Error('Broker lease scope mismatch');
    if (!['new', 'active'].includes(this.#state)) throw new Error('Broker lease is closed or uncertain');
    if (!this.#creation) this.#creation = (async () => {
      try {
        const response = await this.#request('GET', '');
        if (!record(response) || response.attempt_id !== this.#lease.attemptId || response.state !== 'ready'
            || response.deadline !== this.#lease.deadline || this.#state !== 'new') throw new Error('Invalid broker lease status');
        this.#state = 'active';
        return this.#lease.attemptId;
      } catch {
        if (this.#state !== 'closing' && this.#state !== 'closed') this.#state = 'uncertain';
        // The lease was provisioned before this adapter acquired it. Failed
        // create is not released by withSandbox, so own that cleanup here.
        try { await this.destroy(this.#lease.attemptId); }
        catch { throw new Error('Broker acquisition failed and release is unconfirmed'); }
        throw new Error('Broker lease acquisition failed');
      }
    })();
    return this.#creation;
  }

  async exec(_id: string, _request: SandboxExecRequest, _signal?: AbortSignal): Promise<SandboxExecResult> {
    throw new Error('Broker files-v1 does not authorize shell execution');
  }

  async fileOperation(id: string, request: SandboxFileRequest, signal?: AbortSignal): Promise<SandboxFileResult> {
    signal?.throwIfAborted();
    if (id !== this.#lease.attemptId || this.#state !== 'active') throw new Error('Broker lease is closed or uncertain');
    if (this.#pendingFiles >= 16) throw new Error('Broker file queue capacity exceeded');
    const previous = this.#fileTail;
    const slot = Promise.withResolvers<void>();
    this.#fileTail = slot.promise;
    this.#pendingFiles++;
    const deadline = AbortSignal.timeout(this.#timeout);
    const queuedSignal = signal ? AbortSignal.any([signal, deadline]) : deadline;
    try {
      // Model tools may run in parallel; the broker admits one transfer at a time.
      // Never retry a dispatched operation whose outcome is unknown.
      await previous;
      queuedSignal.throwIfAborted();
      return await this.#fileOperation(id, request, queuedSignal);
    } finally {
      this.#pendingFiles--;
      slot.resolve();
    }
  }

  async #fileOperation(id: string, request: SandboxFileRequest, signal?: AbortSignal): Promise<SandboxFileResult> {
    signal?.throwIfAborted();
    if (id !== this.#lease.attemptId || this.#state !== 'active') throw new Error('Broker lease is closed or uncertain');
    let result: SandboxFileResult | undefined;
    let failure: string | undefined;
    try {
      const response = await this.#request('POST', '/files', {
        operation_id: randomUUID(), tool_call_id: request.toolCallId, operation: request.operation,
      }, signal);
      if (!record(response) || response.tool_call_id !== request.toolCallId || !record(response.outcome)
          || typeof response.outcome.ok !== 'boolean') throw new Error('Invalid broker file response');
      if (response.outcome.ok && !validData(response.outcome.data, request.operation)) throw new Error('Invalid broker file data');
      if (!response.outcome.ok && (typeof response.outcome.error !== 'string'
          || !/^[a-z_]{1,64}$/.test(response.outcome.error))) throw new Error('Invalid broker file error');
      signal?.throwIfAborted();
      if (this.#state !== 'active') throw new Error('Broker lease no longer active');
      if (response.outcome.ok) result = { toolCallId: request.toolCallId, data: response.outcome.data as WorkspaceFileData };
      else failure = response.outcome.error as string;
    } catch {
      if (this.#state === 'active') this.#state = 'uncertain';
      throw new Error('Broker file operation outcome is unknown');
    }
    if (failure) throw new Error(`Broker file operation failed: ${failure}`);
    return result!;
  }

  async destroy(id: string): Promise<void> {
    if (id !== this.#lease.attemptId) throw new Error('Broker lease scope mismatch');
    if (this.#state === 'closed') return;
    this.#state = 'closing';
    if (!this.#release) this.#release = (async () => {
      try {
        const response = await this.#request('POST', '/release');
        if (!record(response) || response.attempt_id !== id || response.state !== 'terminated') throw new Error('Unconfirmed broker termination');
        this.#state = 'closed';
      } catch { this.#state = 'uncertain'; throw new Error('Broker release is unconfirmed'); }
      finally { this.#release = undefined; }
    })();
    return this.#release;
  }
}
