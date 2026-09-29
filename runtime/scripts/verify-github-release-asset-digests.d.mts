export interface RemoteReleaseDigestVerificationOptions {
  tag: string;
  repository: string;
  assets: string[];
  attempts?: number;
  retryDelayMs?: number;
}

export function verifyRemoteReleaseAssetDigests(
  options: RemoteReleaseDigestVerificationOptions,
): Promise<Array<{ name: string; sizeBytes: number; sha256: string }>>;
