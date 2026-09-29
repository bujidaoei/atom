export interface SecretCanary {
  id: string;
  value: string;
}

export interface SecretArtifactRoot {
  category: 'bundle' | 'log' | 'evidence' | 'export' | 'release' | 'package' | string;
  path: string;
}

export interface SecretScanOptions {
  repositoryRoot?: string;
  env?: NodeJS.ProcessEnv;
  includeTracked?: boolean;
  trackedFiles?: string[];
  artifactRoots?: SecretArtifactRoot[];
  canaries?: SecretCanary[];
  concurrency?: number;
  filterMatches?: (input: {
    source: { category: string; path: string; artifact: boolean };
    buffer: Buffer;
    matches: SecretBufferMatch[];
  }) => SecretBufferMatch[] | Promise<SecretBufferMatch[]>;
}

export interface SecretFinding {
  category: string;
  path: string;
  line: number;
  detector: string;
  fingerprint: string;
}

export interface SecretScanError {
  category: string;
  path: string;
  error: string;
}

export interface SecretScanResult {
  findings: SecretFinding[];
  errors: SecretScanError[];
  scannedFiles: number;
  categories: string[];
}

export interface SecretBufferMatch {
  line: number;
  detector: string;
  fingerprint: string;
  offset?: number;
}

export function forEachUtf16AsciiString(buffer: Buffer, callback: (value: string) => void): void;

export function utf16AsciiStrings(buffer: Buffer): string[];

export function scanBufferForSecrets(
  buffer: Buffer,
  canaries: SecretCanary[],
  options?: { highConfidence?: boolean; includeOffsets?: boolean; utf8Only?: boolean },
): SecretBufferMatch[];

export function scanV3Secrets(options?: SecretScanOptions): Promise<SecretScanResult>;

export function mapScansInOrder<T, R>(
  items: T[],
  worker: (item: T, index: number) => R | Promise<R>,
  concurrency?: number,
): Promise<R[]>;
