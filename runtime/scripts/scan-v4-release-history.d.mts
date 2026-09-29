import type { SecretCanary, SecretFinding, SecretScanError } from './scan-v3-secrets.mjs';

export interface V4ReleaseHistoryScanOptions {
  repositoryRoot?: string;
  baseRevision: string;
  targetRevision: string;
  tag: string;
  includeBase?: boolean;
  env?: NodeJS.ProcessEnv;
  canaries?: SecretCanary[];
}

export interface V4ReleaseHistoryRange {
  repositoryRoot: string;
  baseRevision: string;
  targetRevision: string;
  tag: string;
  includeBase: boolean;
  commits: string[];
  objectIds: string[];
}

export interface V4ReleaseHistoryScanResult {
  baseRevision: string | null;
  targetRevision: string | null;
  tag: string | null;
  includeBase: boolean;
  commitCount: number;
  objectCount: number;
  scannedObjects: number;
  scannedBytes: number;
  findings: SecretFinding[];
  errors: SecretScanError[];
}

export function inspectV4ReleaseHistoryRange(options: V4ReleaseHistoryScanOptions): V4ReleaseHistoryRange;
export function scanV4ReleaseHistory(
  options: V4ReleaseHistoryScanOptions,
): Promise<V4ReleaseHistoryScanResult>;
