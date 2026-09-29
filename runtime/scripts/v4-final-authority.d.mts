export interface GitHubReleaseRunInspectionOptions {
  runId: string | undefined;
  expectedRevision: string;
  cwd: string;
  spawn?: (
    executable: string,
    args: string[],
    options: { cwd: string; encoding: 'utf8'; windowsHide: true; env: NodeJS.ProcessEnv },
  ) => {
    error?: Error;
    status: number | null;
    stdout?: string | Buffer;
  };
}

export function inspectGitHubReleaseRun(options: GitHubReleaseRunInspectionOptions): string[];

export interface V4GateReceiptPayload {
  schemaVersion: 1;
  kind: 'prepush' | 'windows-installed' | 'production';
  revision: string;
  rollbackRevision: string | null;
  gates: string[];
  manifestSha256: string;
  platform: string;
  arch: string;
  issuedAt: string;
}

export interface V4SignedGateReceipt {
  payload: V4GateReceiptPayload;
  signature: string;
}

export function signGateReceipt(options: {
  payload: V4GateReceiptPayload;
  privateKeyBase64: string;
}): V4SignedGateReceipt;

export function verifyGateReceipt(options: {
  receipt: unknown;
  expected: {
    kind: V4GateReceiptPayload['kind'];
    revision: string;
    rollbackRevision?: string | null;
    gates: string[];
    manifestSha256: string;
    platform?: string;
    arch?: string;
  };
  publicKeyBase64: string;
}): string[];
