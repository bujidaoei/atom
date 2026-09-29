import type { V3EvidenceRecord } from './v3-evidence.mjs';

export const V3_VERIFICATION_SCHEMA_VERSION: 'workdude.v3.verification/v1';
export const V3_REQUIRED_RELEASE_GATES: readonly string[];

export interface V3VerificationManifest {
  schemaVersion: typeof V3_VERIFICATION_SCHEMA_VERSION;
  generatedAt: string;
  source: { revision: string; dirty: false };
  complete: boolean;
  gates: Array<{
    evidenceId: string;
    gateId: string;
    recordSha256: string;
    status: string;
    startedAt: string;
    finishedAt: string;
    artifacts: V3EvidenceRecord['artifacts'];
  }>;
  coverage: Record<string, Array<{ id: string; gateIds: string[] }>>;
  openTasks: Array<{ id: string; line: string }>;
  release: unknown;
}

export function parseV3SpecificationInventory(source: string): {
  requirements: string[];
  successCriteria: string[];
  acceptanceScenarios: string[];
};
export function parseV3ReferenceStateIds(source: string): string[];
export function parseOpenV3Tasks(source: string): Array<{ id: string; line: string }>;
export function evaluateV3Verification(input: {
  records: V3EvidenceRecord[];
  specSource: string;
  taskSource: string;
  referenceSource: string;
  release: unknown;
  requiredGateIds?: readonly string[];
  generatedAt?: string;
}): { errors: string[]; manifest: V3VerificationManifest };
export function renderV3Traceability(manifest: V3VerificationManifest): string;
export function renderV3Release(manifest: V3VerificationManifest): string;
export function writeV3VerificationArtifacts(
  outputDirectory: string,
  evaluation: { errors: string[]; manifest: V3VerificationManifest },
): Promise<string>;
