export const DESKTOP_PROVISIONING_OS_ENVIRONMENT_NAMES: readonly string[];

export function createDesktopProvisioningChildEnvironment(
  source: Readonly<NodeJS.ProcessEnv>,
  input: Readonly<{
    platformOrigin: string;
    desktopToken: string;
    model: string;
  }>,
): NodeJS.ProcessEnv;
