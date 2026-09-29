import { isAbsolute, posix } from 'node:path';

import type { V3GroupEvidenceKind, V3RoleRunReport } from '../../product-contracts/src/v3.ts';
import { V3_PRODUCT_CONTRACT_VERSION, V3RoleRunReportSchema } from '../../product-contracts/src/v3.ts';
import { Value } from 'typebox/value';

import { unwrapSingleJsonFence } from './v3-structured-json.ts';

export type { V3RoleRunReport } from '../../product-contracts/src/v3.ts';

export const V3_ROLE_RUN_REPORT_START = 'QODER_TEAM_ROLE_RUN_REPORT' as const;
export const V3_ROLE_RUN_REPORT_END = 'END_QODER_TEAM_ROLE_RUN_REPORT' as const;

export interface V3ExpectedRoleRunReport {
  roleRunId: string;
  taskId: string;
  planVersion: number;
  requiredAcceptanceKeys: string[];
  requiredEvidenceKeys: string[];
  requiredEvidenceKinds?: Record<string, V3GroupEvidenceKind>;
}

export type V3RoleRunReportParseResult =
  | { ok: true; report: V3RoleRunReport }
  | { ok: false; category: 'invalid_structured_report'; detail: string };

function invalid(detail: string): V3RoleRunReportParseResult {
  return { ok: false, category: 'invalid_structured_report', detail };
}

function duplicate(values: readonly string[]): string | undefined {
  const seen = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) return value;
    seen.add(value);
  }
  return undefined;
}

function missing(expected: readonly string[], actual: ReadonlySet<string>): string[] {
  return expected.filter((key) => !actual.has(key));
}

function unexpected(expected: ReadonlySet<string>, actual: readonly string[]): string[] {
  return actual.filter((key) => !expected.has(key));
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function canonicalizeEvidenceKinds(candidate: unknown, expected: V3ExpectedRoleRunReport): unknown {
  const report = record(candidate);
  if (!report || !Array.isArray(report.evidence) || !expected.requiredEvidenceKinds) return candidate;
  let changed = false;
  const evidence = report.evidence.map((item) => {
    const submitted = record(item);
    if (!submitted || typeof submitted.requirementKey !== 'string') return item;
    const authoritative = expected.requiredEvidenceKinds?.[submitted.requirementKey];
    if (!authoritative || submitted.kind === authoritative) return item;
    changed = true;
    return { ...submitted, kind: authoritative };
  });
  return changed ? { ...report, evidence } : candidate;
}

function completionContractIssues(candidate: unknown, expected: V3ExpectedRoleRunReport): string[] {
  const report = record(candidate);
  const completion = record(report?.completion);
  if (
    !report ||
    !Array.isArray(report.evidence) ||
    !completion ||
    !Array.isArray(completion.acceptanceKeys) ||
    !Array.isArray(completion.evidenceRequirementKeys)
  ) {
    return [];
  }
  const evidence = report.evidence.flatMap((item) => {
    const submitted = record(item);
    return submitted ? [submitted] : [];
  });
  const expectedAcceptance = new Set(expected.requiredAcceptanceKeys);
  const expectedEvidence = new Set(expected.requiredEvidenceKeys);
  const completionAcceptance = new Set(strings(completion.acceptanceKeys));
  const completionEvidence = new Set(strings(completion.evidenceRequirementKeys));
  const evidenceKeys = new Set(
    evidence.flatMap((item) => (typeof item.requirementKey === 'string' ? [item.requirementKey] : [])),
  );
  const provenAcceptance = new Set(evidence.flatMap((item) => strings(item.acceptanceKeys)));

  const missingEvidence = missing(expected.requiredEvidenceKeys, evidenceKeys);
  const missingEvidenceCompletion = missing(expected.requiredEvidenceKeys, completionEvidence);
  const missingAcceptance = missing(expected.requiredAcceptanceKeys, completionAcceptance);
  const unprovenAcceptance = missing(expected.requiredAcceptanceKeys, provenAcceptance);
  const extraEvidence = unexpected(expectedEvidence, [...evidenceKeys, ...completionEvidence]);
  const extraAcceptance = unexpected(expectedAcceptance, [...completionAcceptance, ...provenAcceptance]);
  return [
    ...(missingEvidence.length > 0
      ? [`/evidence[].requirementKey must include: ${missingEvidence.join(', ')}.`]
      : []),
    ...(missingEvidenceCompletion.length > 0
      ? [`/completion/evidenceRequirementKeys must include: ${missingEvidenceCompletion.join(', ')}.`]
      : []),
    ...(missingAcceptance.length > 0
      ? [`/completion/acceptanceKeys must include: ${missingAcceptance.join(', ')}.`]
      : []),
    ...(unprovenAcceptance.length > 0
      ? [`/evidence[].acceptanceKeys must collectively include: ${unprovenAcceptance.join(', ')}.`]
      : []),
    ...(extraEvidence.length > 0
      ? [
          `Only evidence requirement keys are allowed in /evidence[].requirementKey and /completion/evidenceRequirementKeys; remove: ${extraEvidence.join(', ')}.`,
        ]
      : []),
    ...(extraAcceptance.length > 0
      ? [
          `Only acceptance keys are allowed in /completion/acceptanceKeys and /evidence[].acceptanceKeys; remove: ${extraAcceptance.join(', ')}.`,
        ]
      : []),
    ...(report.status === 'completed' && completion.readyForReview !== true
      ? ['A completed RoleRun must be ready for review.']
      : []),
    ...(report.status === 'completed' && strings(report.unresolvedIssues).length > 0
      ? ['A completed RoleRun cannot contain unresolved issues.']
      : []),
  ];
}

function formatSchemaIssue(issue: {
  instancePath?: unknown;
  keyword?: unknown;
  message?: unknown;
  params?: unknown;
}): string {
  const path = typeof issue.instancePath === 'string' ? issue.instancePath : '/';
  const parameters = record(issue.params);
  if (issue.keyword === 'additionalProperties' && Array.isArray(parameters?.additionalProperties)) {
    const properties = strings(parameters.additionalProperties);
    if (properties.length > 0) {
      return properties
        .map((property) => `${path || ''}/${property}: additional property is not allowed`)
        .join('; ');
    }
  }
  return `${path || '/'}: ${typeof issue.message === 'string' ? issue.message : 'is invalid'}`;
}

function isWorkspaceRelativePath(value: string): boolean {
  if (isAbsolute(value) || /^[a-zA-Z]:[\\/]/u.test(value) || value.startsWith('\\\\')) return false;
  const normalized = posix.normalize(value.replaceAll('\\', '/'));
  return normalized !== '..' && !normalized.startsWith('../') && !normalized.startsWith('/');
}

export function formatV3RoleRunReport(report: V3RoleRunReport): string {
  return `${V3_ROLE_RUN_REPORT_START}\n${JSON.stringify(report, null, 2)}\n${V3_ROLE_RUN_REPORT_END}`;
}

export function parseV3RoleRunReport(
  output: string,
  expected: V3ExpectedRoleRunReport,
): V3RoleRunReportParseResult {
  const lines = output.split(/\r?\n/u);
  const starts = lines.flatMap((line, index) => {
    const normalized = line.trimStart();
    const marker = normalized.startsWith(V3_ROLE_RUN_REPORT_START)
      ? V3_ROLE_RUN_REPORT_START
      : normalized.startsWith(`<${V3_ROLE_RUN_REPORT_START}>`)
        ? `<${V3_ROLE_RUN_REPORT_START}>`
        : undefined;
    if (!marker) return [];
    const suffix = normalized.slice(marker.length).trimStart();
    return suffix === '' || suffix === ':' || suffix.startsWith('{') || suffix.startsWith('```')
      ? [{ index, suffix }]
      : [];
  });
  const ends = lines.flatMap((line, index) =>
    line.trim() === V3_ROLE_RUN_REPORT_END || line.trim() === `<${V3_ROLE_RUN_REPORT_END}>` ? [index] : [],
  );
  const startMarker = starts[0];
  const start = startMarker?.index;
  const end = ends[0];
  let raw: string;
  if (starts.length === 0 && ends.length === 0) {
    raw = output.trim();
  } else if (
    starts.length === 1 &&
    ends.length === 1 &&
    start !== undefined &&
    end !== undefined &&
    end > start
  ) {
    const markerSuffix = startMarker!.suffix;
    const inline = markerSuffix === ':' ? '' : markerSuffix;
    raw = [inline, ...lines.slice(start + 1, end)].join('\n').trim();
  } else {
    return invalid(
      `Exactly one ${V3_ROLE_RUN_REPORT_START} ... ${V3_ROLE_RUN_REPORT_END} block is required.`,
    );
  }
  const encoded = unwrapSingleJsonFence(raw) ?? raw;
  let candidate: unknown;
  try {
    candidate = JSON.parse(encoded);
  } catch (cause) {
    return invalid(
      `RoleRun report is not valid JSON: ${cause instanceof Error ? cause.message : String(cause)}`,
    );
  }
  candidate = canonicalizeEvidenceKinds(candidate, expected);
  if (!Value.Check(V3RoleRunReportSchema, candidate)) {
    if (
      candidate &&
      typeof candidate === 'object' &&
      !Array.isArray(candidate) &&
      typeof (candidate as Record<string, unknown>).roleResult !== 'string'
    ) {
      return invalid('/roleResult: must be string.');
    }
    if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
      const report = candidate as Record<string, unknown>;
      const allowed = Object.keys(V3RoleRunReportSchema.properties);
      const missingKeys = allowed.filter((key) => !(key in report));
      const additionalKeys = Object.keys(report).filter((key) => !allowed.includes(key));
      const propertyIssues = [
        ...missingKeys.map((key) => `/${key}: is required`),
        ...additionalKeys.map((key) => `/${key}: additional property is not allowed`),
      ];
      if (propertyIssues.length > 0) {
        const issues = [...propertyIssues, ...completionContractIssues(candidate, expected)];
        return invalid(`RoleRun report does not match the V3 structured-report schema: ${issues.join('; ')}`);
      }
      const discriminatorIssues = [
        ...(report.schemaVersion === V3_PRODUCT_CONTRACT_VERSION
          ? []
          : [`/schemaVersion: must equal "${V3_PRODUCT_CONTRACT_VERSION}"`]),
        ...(report.reportType === 'role_run_completion'
          ? []
          : ['/reportType: must equal "role_run_completion"']),
        ...(report.status === 'completed' || report.status === 'blocked'
          ? []
          : ['/status: must be one of "completed", "blocked"']),
      ];
      if (discriminatorIssues.length > 0) {
        const issues = [...discriminatorIssues, ...completionContractIssues(candidate, expected)];
        return invalid(`RoleRun report does not match the V3 structured-report schema: ${issues.join('; ')}`);
      }
    }
    const issues = [...Value.Errors(V3RoleRunReportSchema, candidate)]
      .slice(0, 12)
      .map(formatSchemaIssue)
      .concat(completionContractIssues(candidate, expected))
      .join('; ');
    return invalid(`RoleRun report does not match the V3 structured-report schema: ${issues}`);
  }
  const report = candidate;

  if (report.roleRunId !== expected.roleRunId) {
    return invalid(
      `RoleRun report roleRunId mismatch: expected ${expected.roleRunId}, received ${report.roleRunId}.`,
    );
  }
  if (report.taskId !== expected.taskId) {
    return invalid(`RoleRun report taskId mismatch: expected ${expected.taskId}, received ${report.taskId}.`);
  }
  if (report.planVersion !== expected.planVersion) {
    return invalid(
      `RoleRun report planVersion mismatch: expected ${expected.planVersion}, received ${report.planVersion}.`,
    );
  }

  const artifactPaths = report.artifacts.map((artifact) => artifact.path);
  const invalidPath = [...artifactPaths, ...report.evidence.map((item) => item.artifactPath)].find(
    (path) => !isWorkspaceRelativePath(path),
  );
  if (invalidPath) return invalid(`Artifact path must be workspace-relative: ${invalidPath}.`);
  const duplicateArtifact = duplicate(artifactPaths);
  if (duplicateArtifact) return invalid(`Artifact path is duplicated: ${duplicateArtifact}.`);

  const completionIssues = completionContractIssues(report, expected);
  if (completionIssues.length > 0) return invalid(completionIssues.join(' '));

  return { ok: true, report };
}
