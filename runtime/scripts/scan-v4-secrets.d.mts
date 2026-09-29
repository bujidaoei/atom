import type { SecretArtifactRoot, SecretScanOptions, SecretScanResult } from './scan-v3-secrets.mjs';

export type {
  SecretArtifactRoot,
  SecretCanary,
  SecretFinding,
  SecretScanError,
  SecretScanOptions,
  SecretScanResult,
} from './scan-v3-secrets.mjs';

export interface V4SecretArtifactRoot extends SecretArtifactRoot {
  piCache?: boolean;
  required?: boolean;
}

export interface V4SecretScanOptions extends Omit<SecretScanOptions, 'artifactRoots'> {
  artifactRoots?: V4SecretArtifactRoot[];
}

export function v4SecretCanaries(environment: NodeJS.ProcessEnv): SecretCanary[];
export function scanV4Secrets(options?: V4SecretScanOptions): Promise<SecretScanResult>;
