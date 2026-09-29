export const V3_EVIDENCE_SCHEMA_VERSION: 'workdude.v3.evidence/v1';

export interface V3EvidenceRecord {
  schemaVersion: typeof V3_EVIDENCE_SCHEMA_VERSION;
  evidenceId: string;
  gateId: string;
  taskIds: string[];
  claims: {
    requirements: string[];
    successCriteria: string[];
    acceptanceScenarios: string[];
    referenceStates: string[];
  };
  source: { revision: string; dirty: boolean };
  command: { argv: string[]; cwd?: string };
  environment: { details: Record<string, unknown>; fingerprint: string };
  timing: { startedAt: string; finishedAt: string; durationMs: number };
  outcome: {
    status: 'passed' | 'failed' | 'skipped' | 'partial';
    exitCode: number | null;
    mocked: boolean;
    skipped: boolean;
    partial: boolean;
    reason?: string;
  };
  metrics: Record<string, string | number | boolean | null>;
  artifacts: Array<{ path: string; sha256: string; bytes?: number }>;
}

export function createEvidenceRecord(input: unknown): V3EvidenceRecord;
export function validateEvidenceRecord(record: unknown): string[];
export function assertEvidenceRecord(record: unknown): V3EvidenceRecord;
export function isPassingEvidence(record: unknown): boolean;
export function writeEvidenceRecord(outputPath: string, record: unknown): Promise<string>;
