export type PlatformSandboxPlatform = 'win32' | 'linux' | 'darwin';
export type PlatformSandboxArchitecture = 'x64' | 'arm64';
export type PlatformSandboxTargetId = 'win32/x64' | 'linux/x64' | 'darwin/x64' | 'darwin/arm64';

export interface PlatformSandboxTarget {
  readonly id: PlatformSandboxTargetId;
  readonly platform: PlatformSandboxPlatform;
  readonly arch: PlatformSandboxArchitecture;
  readonly label: 'Windows-x64' | 'Linux-x64' | 'macOS-x64' | 'macOS-arm64';
}

export interface PlatformSandboxDockerInvocation {
  readonly command: 'docker';
  readonly args: readonly string[];
}

export interface PlatformSandboxRunOptions {
  repositoryRoot?: string;
  targets?: string | readonly PlatformSandboxTargetId[];
  runNativeSmoke?: boolean;
  useDocker?: boolean;
  insideContainer?: boolean;
}

export const PLATFORM_SANDBOX_TARGETS: readonly PlatformSandboxTarget[];
export function parsePlatformSandboxTargets(value?: string): readonly PlatformSandboxTarget[];
export function expectedPlatformSandboxLabel(
  platform: PlatformSandboxPlatform,
  arch: PlatformSandboxArchitecture,
): PlatformSandboxTarget['label'];
export function buildPlatformSandboxDockerInvocation(options: {
  repositoryRoot: string;
  targets: string | readonly PlatformSandboxTargetId[];
  containerName: string;
}): PlatformSandboxDockerInvocation;
export function runDesktopPlatformSandbox(
  options?: PlatformSandboxRunOptions,
): Promise<Record<string, unknown>>;
