/** Trusted ready-lease metadata. Never contains administrative credentials. */
export interface ExecutionBinding {
  executionId: string;
  workspaceId: string;
  attemptId: string;
  grantId: string;
  completionGrant: string;
  deadline: number;
}

export interface ExecutionReceipt {
  attempt_id: string;
  workspace_id: string;
  revision_id: string;
  artifact_key: string;
  snapshot_revision: string;
}

export interface ExecutionResult {
  outcome: 'succeeded' | 'failed' | 'cancelled' | 'timed_out';
  receipt: ExecutionReceipt | null;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function exact(value: Record<string, unknown>, names: string[]): boolean {
  return Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
}
const id = (value: unknown) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

/** Bounded completion transport. Unknown responses never trigger an automatic retry. */
export class ExecutionClient {
  readonly #origin: string;
  readonly #lease: Readonly<ExecutionBinding>;
  readonly #timeout: number;

  constructor(options: { baseUrl: string; lease: ExecutionBinding; timeoutMs?: number }) {
    let url: URL;
    try { url = new URL(options.baseUrl); } catch { throw new Error('Invalid execution origin'); }
    if (/[\\?#\s]/.test(options.baseUrl) || /[^\x21-\x7e]/.test(options.baseUrl)
        || (url.protocol !== 'https:' && !/^http:\/\/(?:127\.0\.0\.1|\[::1\])(?::[1-9][0-9]{0,4})?\/?$/.test(options.baseUrl))
        || url.username || url.password || url.pathname !== '/' || url.port === '0') throw new Error('Invalid execution origin');
    const lease = options.lease;
    if (!lease || !id(lease.executionId) || !id(lease.workspaceId) || !id(lease.grantId)
        || typeof lease.attemptId !== 'string' || !/^[a-f0-9]{32}$/.test(lease.attemptId)
        || typeof lease.completionGrant !== 'string' || lease.completionGrant.length > 8192
        || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(lease.completionGrant)
        || !Number.isSafeInteger(lease.deadline) || lease.deadline <= Date.now() / 1000) throw new Error('Invalid execution binding');
    const timeout = options.timeoutMs ?? 120_000;
    if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > 300_000) throw new Error('Invalid execution timeout');
    this.#origin = url.origin;
    this.#lease = Object.freeze({ ...lease });
    this.#timeout = timeout;
  }

  async #request(action: 'complete' | 'cancel'): Promise<ExecutionResult> {
    const signal = AbortSignal.timeout(this.#timeout);
    try {
      const response = await fetch(`${this.#origin}/v1/executions/${action}`, {
        method: 'POST', redirect: 'error', credentials: 'omit', signal,
        headers: { authorization: `Bearer ${this.#lease.completionGrant}`, 'accept-encoding': 'identity' },
      });
      if (response.status !== 200 || response.headers.has('content-encoding')
          || response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
        await response.body?.cancel();
        throw new Error();
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error();
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > 16384) throw new Error();
          chunks.push(value);
        }
        signal.throwIfAborted();
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
      const value: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
      const lease = this.#lease;
      if (!record(value) || !exact(value, ['attempt_id', 'workspace_id', 'grant_id', 'broker_attempt_id', 'deadline',
        'state', 'termination_state', 'outcome', 'receipt']) || value.attempt_id !== lease.executionId
        || value.workspace_id !== lease.workspaceId || value.grant_id !== lease.grantId
        || value.broker_attempt_id !== lease.attemptId || value.deadline !== lease.deadline
        || value.state !== 'closed' || value.termination_state !== 'confirmed'
        || !['succeeded', 'failed', 'cancelled', 'timed_out'].includes(value.outcome as string)) throw new Error();
      const receipt = value.receipt;
      if (receipt !== null && (!record(receipt) || !exact(receipt, ['attempt_id', 'workspace_id', 'revision_id', 'artifact_key', 'snapshot_revision'])
        || receipt.attempt_id !== lease.executionId || receipt.workspace_id !== lease.workspaceId
        || typeof receipt.revision_id !== 'string' || !/^[a-f0-9]{32}$/.test(receipt.revision_id)
        || !hash(receipt.artifact_key) || !hash(receipt.snapshot_revision))) throw new Error();
      if (value.outcome === 'succeeded' && receipt === null) throw new Error();
      return Object.freeze({ outcome: value.outcome as ExecutionResult['outcome'],
        receipt: receipt === null ? null : Object.freeze({ ...receipt }) as unknown as ExecutionReceipt });
    } catch { throw new Error('Execution response failed or outcome is unknown'); }
  }

  async complete(): Promise<ExecutionReceipt> {
    const result = await this.#request('complete');
    if (result.outcome !== 'succeeded' || !result.receipt) throw new Error('Execution did not complete successfully');
    return result.receipt;
  }

  async cancel(): Promise<ExecutionResult> { return this.#request('cancel'); }
}
