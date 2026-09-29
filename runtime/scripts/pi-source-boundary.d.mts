export interface PiSourceLock {
  version: string;
  releaseTag: string;
  upstreamRepository: string;
  upstreamCommit: string;
  sourceArchive: string;
  sourceArchiveSha256: string;
  manifestSha256: string;
  fileCount: number;
}

declare const verifiedPiSourceLockBrand: unique symbol;

export type VerifiedPiSourceLock = Readonly<PiSourceLock> & {
  readonly [verifiedPiSourceLockBrand]: true;
};

export type PiSourceSnapshot = ReadonlyMap<string, string>;

export interface PiSourceBoundaryOptions {
  root?: string;
  lockPath?: string;
  piRoot?: string;
  quiet?: boolean;
}

export function normalizePiSourceLock(value: unknown): Readonly<PiSourceLock>;
export function readStablePlainFile(
  path: string,
  options: { repositoryRoot: string; trustedRoot?: string; label: string },
): Promise<Buffer>;
export function capturePiSourceSnapshot(piRoot: string): Promise<Map<string, string>>;
export function verifyIsolatedPiSourceTree(piRoot: string, lock: VerifiedPiSourceLock): Promise<void>;
export function verifyPiSourceSnapshot(piRoot: string, snapshot: PiSourceSnapshot): Promise<void>;
export function verifyPiSourceBoundary(options?: PiSourceBoundaryOptions): Promise<VerifiedPiSourceLock>;
