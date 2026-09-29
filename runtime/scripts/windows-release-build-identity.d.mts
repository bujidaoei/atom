export interface WindowsReleaseCriticalIdentity {
  executable: string;
  appAsar: string;
  nativeHost: string;
  uninstallHelper: string;
}

export interface WindowsReleaseBuildIdentity {
  unpacked: WindowsReleaseCriticalIdentity;
  zip: WindowsReleaseCriticalIdentity;
  nupkg: WindowsReleaseCriticalIdentity;
  nupkgSha256: string;
  setupEmbeddedNupkgSha256: string;
  setupSha256?: string;
  zipSha256?: string;
}

export function assertMatchingWindowsReleaseBuildIdentity<T extends WindowsReleaseBuildIdentity>(
  identity: T,
): Readonly<T>;

export function hashWindowsReleaseFile(path: string): Promise<string>;

export function inspectWindowsReleaseBuildIdentity(options: {
  sevenZipPath: string;
  packageRoot: string;
  zipPath: string;
  nupkgPath: string;
  setupPath: string;
}): Promise<Readonly<Required<WindowsReleaseBuildIdentity>>>;
