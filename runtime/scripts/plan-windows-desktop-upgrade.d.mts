export interface WindowsDesktopFileIdentity {
  path: string;
  sha256: string;
  sizeBytes: number;
}

export interface WindowsDesktopSignatureTarget {
  id: string;
  phase: 'pre-upgrade' | 'pre-install' | 'archive' | 'post-upgrade';
  sha256: string;
  path?: string;
  archivePath?: string;
  archiveSha256?: string;
  archiveSizeBytes?: number;
  entryPath?: string;
  relativePath?: string;
  sizeBytes?: number;
  compressedSizeBytes?: number;
}

export interface WindowsDesktopUpgradePlan {
  schemaVersion: 1;
  kind: 'windows-squirrel-in-place-upgrade';
  executionAllowed: false;
  previous: Readonly<WindowsDesktopFileIdentity & { version: string }>;
  current: Readonly<{
    version: string;
    setup: Readonly<WindowsDesktopFileIdentity>;
    nupkg: Readonly<WindowsDesktopFileIdentity>;
    zip: Readonly<WindowsDesktopFileIdentity>;
    packageRoot: string;
  }>;
  phases: readonly string[];
  signatureMatrix: readonly Readonly<WindowsDesktopSignatureTarget>[];
  retention: Readonly<{
    authority: 'real-product-data';
    manualMarkerIsInsufficient: true;
    sameUserDataBeforeAndAfterUpgrade: true;
  }>;
  smartScreen: Readonly<{
    status: 'external-required';
    substitutedByAuthenticode: false;
  }>;
  integrity: Readonly<{
    algorithm: 'sha256';
    planSha256: string;
  }>;
}

export function compareWindowsDesktopVersions(first: string, second: string): number;

export function canonicalizeWindowsDesktopUpgradePlan(value: unknown): string;

export function createWindowsDesktopUpgradePlan(options: {
  repositoryRoot?: string;
  previousInstallerPath: string;
  previousVersion: string;
  previousSha256: string;
}): Promise<Readonly<WindowsDesktopUpgradePlan>>;

export interface WindowsDesktopUpgradePlanFile {
  readonly executionAllowed: false;
  readonly planPath: string;
  readonly planSha256: string;
  readonly canonicalPlanSha256: string;
  readonly currentSetupSha256: string;
  readonly currentUpdaterSha256: string;
}

export function writeWindowsDesktopUpgradePlanFile(
  plan: Readonly<WindowsDesktopUpgradePlan>,
  options?: { outputRoot?: string },
): Promise<Readonly<WindowsDesktopUpgradePlanFile>>;
