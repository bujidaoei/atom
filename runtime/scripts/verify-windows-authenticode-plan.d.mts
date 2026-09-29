export type WindowsAuthenticodePhase = 'pre-upgrade' | 'pre-install' | 'archive' | 'post-upgrade';

export interface WindowsAuthenticodeSignatureResult {
  status: string;
  signerThumbprint: string | null;
  timeStamperCertificatePresent: boolean;
}

export interface WindowsAuthenticodeVerifiedTarget {
  id: string;
  phase: WindowsAuthenticodePhase;
  sha256: string;
  sizeBytes: number;
}

export interface WindowsAuthenticodeVerificationResult {
  schemaVersion: 1;
  planSha256: string;
  signerThumbprint: string;
  phases: readonly WindowsAuthenticodePhase[];
  timestampRequired: true;
  verifiedTargets: readonly Readonly<WindowsAuthenticodeVerifiedTarget>[];
}

export type WindowsAuthenticodeSignatureRunner = (
  path: string,
) => Promise<WindowsAuthenticodeSignatureResult>;

export interface WindowsAuthenticodeVerificationOptions {
  planPath: string;
  expectedPlanSha256: string;
  expectedThumbprint: string;
  phases: readonly WindowsAuthenticodePhase[];
  installRoot?: string;
  signatureRunner?: WindowsAuthenticodeSignatureRunner;
}

export function normalizeWindowsCertificateThumbprint(value: string): string;

export function validateWindowsAuthenticodeSignature(
  result: unknown,
  expectedThumbprint: string,
  label?: string,
): Readonly<{ signerThumbprint: string; timestampVerified: true }>;

export function runWindowsAuthenticodeSignature(path: string): Promise<WindowsAuthenticodeSignatureResult>;

export function verifyWindowsAuthenticodePlan(
  options: WindowsAuthenticodeVerificationOptions,
): Promise<Readonly<WindowsAuthenticodeVerificationResult>>;

export function parseWindowsAuthenticodeCliArguments(arguments_: readonly string[]): Readonly<{
  planPath: string;
  expectedPlanSha256: string;
  expectedThumbprint: string;
  phases: string[];
  installRoot: string | undefined;
}>;
