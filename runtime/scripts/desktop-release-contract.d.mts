export const DESKTOP_RELEASE_LABELS: readonly ['Windows-x64', 'Linux-x64', 'macOS-x64', 'macOS-arm64'];

export type DesktopReleaseLabel = (typeof DESKTOP_RELEASE_LABELS)[number];

export interface RemoteReleaseAsset {
  name?: string;
  size?: number;
  state?: string;
  digest?: string | null;
}

export interface ExpectedReleaseAsset {
  name: string;
  sizeBytes: number;
  sha256: string;
}

export function hasExactDesktopReleaseVersion(name: string, version: string): boolean;
export function assertDebianPackageIdentity(
  identity: { package: string; version: string; architecture: string },
  expectedVersion: string,
): void;
export function selectNativeDesktopInstaller(
  files: string[],
  makeDirectory: string,
  label: DesktopReleaseLabel,
  version: string,
): string;
export function desktopReleasePackageNames(version: string, label: DesktopReleaseLabel): string[];
export function desktopReleaseAssetNames(version: string): string[];
export function assertRemoteAssetDigests(
  remoteAssets: RemoteReleaseAsset[],
  expectedAssets: ExpectedReleaseAsset[],
): void;

export function isDesktopReleaseCandidateForLabel(
  path: string,
  makeDirectory: string,
  label: DesktopReleaseLabel,
): boolean;
