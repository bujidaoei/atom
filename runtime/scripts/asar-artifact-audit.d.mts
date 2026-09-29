import type { SecretCanary, SecretFinding, SecretScanError } from './scan-v3-secrets.mjs';

export interface ProviderArtifactMatch {
  detector: string;
  index: number;
  line: number;
  value: string;
  fingerprint: string;
}

export interface ArtifactAuditResult {
  findings: SecretFinding[];
  errors: SecretScanError[];
  complete: boolean;
  rawPath: string;
  scannedFiles?: number;
}

export interface AsarAuditOptions {
  repositoryRoot: string;
  archivePath: string;
  category: string;
  canaries: SecretCanary[];
  providerMatches(text: string): ProviderArtifactMatch[];
  limits?: Partial<{
    archiveBytes: number;
    entryBytes: number;
    headerBytes: number;
    opaqueFallbackBytes: number;
    entries: number;
    depth: number;
  }>;
}

export interface ElectronAuditOptions {
  repositoryRoot: string;
  executablePath: string;
  category: string;
  providerMatches(text: string): ProviderArtifactMatch[];
}

export function auditAsarArtifact(options: AsarAuditOptions): Promise<ArtifactAuditResult>;
export function auditElectronExecutable(options: ElectronAuditOptions): Promise<ArtifactAuditResult>;
