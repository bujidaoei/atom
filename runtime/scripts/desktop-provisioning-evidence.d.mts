export interface DesktopProvisioningEvidence {
  readonly operation: 'platform_config_provision';
  readonly status: 'ready';
  readonly model: string;
  readonly availableModelCount: number;
}

export function parseDesktopProvisioningEvidence(stdout: string): DesktopProvisioningEvidence;
