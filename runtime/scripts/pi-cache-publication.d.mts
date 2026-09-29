import type { PiSourceLock } from './pi-source-boundary.mjs';

declare const piCacheLayoutBrand: unique symbol;
declare const piCacheReaderLayoutBrand: unique symbol;
declare const piCacheReaderBrand: unique symbol;

export type TrustedPiSourceIdentity = Readonly<PiSourceLock>;

export interface PiCacheReaderLayout {
  readonly [piCacheReaderLayoutBrand]: true;
  readonly repositoryRoot: string;
  readonly trustedPiSource: Readonly<TrustedPiSourceIdentity>;
  readonly cacheParent: string;
  readonly cacheParentIdentity: string;
  readonly pointerPath: string;
}

export interface PiCacheLayout extends PiCacheReaderLayout {
  readonly [piCacheLayoutBrand]: true;
  readonly piRoot: string;
  readonly lockPath: string;
}

export interface PiCacheGenerationSnapshot {
  readonly generation: string;
  readonly manifestSha256: string;
  readonly sourceLockSha256: string;
  readonly sourceLockContent: string;
  readonly piSourceManifestSha256: string;
  readonly root: string;
}

export interface PiCacheReader extends PiCacheGenerationSnapshot {
  readonly [piCacheReaderBrand]: true;
  readonly repositoryRoot: string;
  readonly trustedPiSource: Readonly<TrustedPiSourceIdentity>;
}

export interface PiCacheLockOptions {
  timeoutMs?: number;
  staleMs?: number;
}

export interface PiCacheOperations {
  rename?: (source: string, destination: string) => Promise<void>;
}

export interface PiCachePublicationOptions extends PiCacheLockOptions {
  operations?: PiCacheOperations;
}

export function resolveSafePiCacheLayout(options?: { repositoryRoot?: string }): Promise<PiCacheLayout>;
export function resolvePiCacheReaderLayout(options?: {
  repositoryRoot?: string;
}): Promise<PiCacheReaderLayout>;
export function acquirePiBuildCacheLock(
  layout: PiCacheLayout,
  options?: PiCacheLockOptions,
): Promise<{ release(): Promise<void> }>;
export function recoverInterruptedPiBuildGenerationPublication(
  layout: PiCacheLayout,
  options?: PiCacheLockOptions,
): Promise<void>;
export function resolvePublishedPiBuildCache(
  layout: PiCacheReaderLayout,
): Promise<Readonly<PiCacheGenerationSnapshot>>;
export function pinPublishedPiBuildCache(options?: {
  repositoryRoot?: string;
}): Promise<Readonly<PiCacheReader>>;
export function resolvePiBuildCacheArtifact(reader: PiCacheReader, artifactPath: string): string;
export function readPiBuildCacheArtifact(reader: PiCacheReader, artifactPath: string): Promise<Buffer>;
export function removePiBuildCacheScratch(layout: PiCacheLayout, path: string): Promise<void>;
export function publishPiBuildCacheGeneration(
  layout: PiCacheLayout,
  publicationRoot: string,
  options?: PiCachePublicationOptions,
): Promise<Readonly<PiCacheGenerationSnapshot>>;
