export interface WindowsLifecycleFileIdentity {
  readonly path: string;
  readonly identity: string;
  readonly sha256: string;
  readonly sizeBytes: number;
}

export function createWindowsInnoTestInstallation(options: {
  installer: string;
  version: string;
  prefix: string;
  expectedInstallerSha256?: string;
  packageRoot?: string;
}): Promise<{
  root: string;
  installRoot: string;
  environment: NodeJS.ProcessEnv;
  userData: string;
  installedExecutable: string;
  applicationExecutable: string;
  applicationArchive: string;
  uninstallAndAssertApplicationRemoval(): Promise<void>;
  cleanup(): Promise<void>;
}>;

export function pathExistsFailClosed(
  path: string,
  inspect?: (path: string) => Promise<unknown>,
): Promise<boolean>;

export function plainFileIdentity(
  path: string,
  label: string,
): Promise<Readonly<WindowsLifecycleFileIdentity>>;

export function assertOwnedFile(
  path: string,
  expected: Readonly<WindowsLifecycleFileIdentity>,
  label: string,
): Promise<Readonly<WindowsLifecycleFileIdentity>>;
