import { randomUUID } from 'node:crypto';
import { lstat, open, realpath } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';

import type {
  V3GroupPlanProposal,
  V3ModelUsage,
  V3RoleRunArtifactReference,
} from '../../product-contracts/src/v3.ts';
import {
  redactProviderCorrelation,
  redactRunFailureDetail,
} from '../../product-contracts/src/provider-correlation.ts';
import {
  V3GroupMissionAggregate,
  type V3GroupMissionSnapshot,
  type V3GroupPlanTask,
} from './v3-group-orchestrator.ts';
import {
  buildV3GroupLeaderSystemPrompt,
  buildV3GroupRoleRunSystemPrompt,
  parseV3GroupPlanProposal,
  type V3GroupPromptMember,
} from './v3-group-prompts.ts';
import { parseV3RoleRunReport } from './v3-role-run-report.ts';
import { runFailureDetail } from './run-failure.ts';

export interface V3GroupMissionStoreRecord {
  id: string;
  prompt: string;
  mentionedWakerIds: string[];
  workspaceRoot: string;
  profiles: V3GroupPromptMember[];
  snapshot: V3GroupMissionSnapshot;
}

export interface V3GroupMissionStore {
  get(missionId: string): Promise<V3GroupMissionStoreRecord | undefined>;
  appendSnapshot(
    missionId: string,
    snapshot: V3GroupMissionSnapshot,
    event: { type: string; payload: Record<string, unknown> },
  ): Promise<void>;
}

interface V3GroupAgentRunCommon {
  executionId: string;
  missionId: string;
  member: V3GroupPromptMember;
  workspaceRoot: string;
  sessionPath: string;
  systemPrompt: string;
  prompt: string;
}

export type V3GroupAgentRunInput =
  | (V3GroupAgentRunCommon & { kind: 'leader_plan' | 'leader_aggregate' })
  | (V3GroupAgentRunCommon & {
      kind: 'role_run';
      reportRepair: boolean;
      roleRunId: string;
      taskId: string;
      planVersion: number;
      task: V3GroupPlanProposal['tasks'][number];
    });

export interface V3GroupAgentRunResult {
  resultText: string;
  usage?: V3ModelUsage | null;
  providerCorrelationId?: string | null;
}

export type V3GroupAgentExecutor = (input: V3GroupAgentRunInput) => Promise<V3GroupAgentRunResult>;

export interface V3GroupMissionRunnerOptions {
  store: V3GroupMissionStore;
  runAgent: V3GroupAgentExecutor;
  sessionRoot: string;
  resolveMemberWorkspaceRoot?(member: V3GroupPromptMember, fallbackWorkspaceRoot: string): Promise<string>;
  maxPlanAttempts?: number;
  maxLeaderSummaryAttempts?: number;
  maxRoleRunAttempts?: number;
  maxRemediationPlans?: number;
  commandTimeoutMs?: number;
  commandLeaseMs?: number;
  commandLeaseRefreshMs?: number;
  preview?: { url: string; entryPath: string };
  persistArtifacts?(input: {
    missionId: string;
    roleRunId: string;
    workspaceRoot: string;
    artifacts: Array<V3RoleRunArtifactReference & { bytes: Buffer }>;
  }): Promise<Array<V3RoleRunArtifactReference & { artifactId: string; fileObjectId: string }>>;
}

export type V3GroupMissionRunResult =
  | {
      status: 'awaiting_confirmation';
      planVersion: number;
      snapshot: V3GroupMissionSnapshot;
    }
  | {
      status: 'completed';
      summary: string;
      snapshot: V3GroupMissionSnapshot;
      previewUrl?: string;
    };

interface V3VerificationFailure {
  taskKey: string;
  ownerWakerId: string;
  roleRunId: string;
  detail: string;
  artifactPath: string;
}

interface V3VerificationReportIssue {
  detail: string;
  artifactPath: string;
  requiresRemediation: boolean;
}

const MAX_SHARED_WORKSPACE_FILE_BYTES = 500 * 1024 * 1024;

type BigIntWorkspaceFileStats = {
  readonly dev: bigint;
  readonly ino: bigint;
  readonly nlink: bigint;
  readonly size: bigint;
  readonly mtimeNs: bigint;
  readonly ctimeNs: bigint;
  isDirectory(): boolean;
  isFile(): boolean;
  isSymbolicLink(): boolean;
};

function sameWorkspacePath(first: string, second: string): boolean {
  return process.platform === 'win32'
    ? first.toLocaleLowerCase('en-US') === second.toLocaleLowerCase('en-US')
    : first === second;
}

function sameWorkspaceFileStats(first: BigIntWorkspaceFileStats, second: BigIntWorkspaceFileStats): boolean {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.nlink === second.nlink &&
    first.size === second.size &&
    first.mtimeNs === second.mtimeNs &&
    first.ctimeNs === second.ctimeNs
  );
}

function isWorkspaceDescendant(root: string, target: string): boolean {
  const distance = relative(root, target);
  const separator = process.platform === 'win32' ? '\\' : '/';
  return (
    Boolean(distance) && distance !== '..' && !distance.startsWith(`..${separator}`) && !isAbsolute(distance)
  );
}

function workspacePathTarget(
  workspaceRoot: string,
  artifactPath: string,
): {
  root: string;
  target: string;
} {
  const root = resolve(workspaceRoot);
  const target = resolve(root, artifactPath);
  if (!isWorkspaceDescendant(root, target)) {
    throw new Error(`Artifact escapes the shared workspace: ${artifactPath}.`);
  }
  return { root, target };
}

/**
 * Read one workspace-relative artifact through a single stable descriptor.
 * The returned bytes are the exact bytes that the persistence callback receives.
 */
export async function readV3SharedWorkspaceFile(
  workspaceRoot: string,
  artifactPath: string,
  options: { maxBytes?: number; signal?: AbortSignal } = {},
): Promise<Buffer> {
  options.signal?.throwIfAborted();
  const maxBytes = Math.min(
    options.maxBytes ?? MAX_SHARED_WORKSPACE_FILE_BYTES,
    MAX_SHARED_WORKSPACE_FILE_BYTES,
  );
  const { root, target } = workspacePathTarget(workspaceRoot, artifactPath);
  const rootEntry = (await lstat(root, { bigint: true })) as BigIntWorkspaceFileStats;
  if (!rootEntry.isDirectory() || rootEntry.isSymbolicLink()) {
    throw new Error('Shared workspace must be a plain directory');
  }
  const canonicalRoot = await realpath(root);
  if (!sameWorkspacePath(canonicalRoot, root)) {
    throw new Error('Shared workspace path traverses a link');
  }
  const pathBefore = (await lstat(target, { bigint: true })) as BigIntWorkspaceFileStats;
  if (!pathBefore.isFile() || pathBefore.isSymbolicLink() || pathBefore.nlink !== 1n) {
    throw new Error(`Artifact is not a plain file: ${artifactPath}.`);
  }
  if (pathBefore.size > BigInt(maxBytes)) {
    throw new Error(`Artifact exceeds the ${maxBytes}-byte limit: ${artifactPath}.`);
  }
  const canonicalTarget = await realpath(target);
  if (!isWorkspaceDescendant(canonicalRoot, canonicalTarget) || !sameWorkspacePath(canonicalTarget, target)) {
    throw new Error(`Artifact path traverses a link: ${artifactPath}.`);
  }
  const handle = await open(target, 'r');
  try {
    const opened = (await handle.stat({ bigint: true })) as BigIntWorkspaceFileStats;
    if (!sameWorkspaceFileStats(pathBefore, opened)) {
      throw new Error(`Artifact changed while opening: ${artifactPath}.`);
    }
    const bytes = Buffer.allocUnsafe(Number(opened.size));
    let offset = 0;
    while (offset < bytes.byteLength) {
      options.signal?.throwIfAborted();
      const { bytesRead } = await handle.read(bytes, offset, bytes.byteLength - offset, offset);
      if (bytesRead === 0) throw new Error(`Artifact ended before its declared size: ${artifactPath}.`);
      offset += bytesRead;
    }
    const after = (await handle.stat({ bigint: true })) as BigIntWorkspaceFileStats;
    const pathAfter = (await lstat(target, { bigint: true })) as BigIntWorkspaceFileStats;
    const canonicalPathAfter = await realpath(target);
    if (
      !sameWorkspaceFileStats(opened, after) ||
      !sameWorkspaceFileStats(after, pathAfter) ||
      !sameWorkspacePath(canonicalRoot, await realpath(root)) ||
      !sameWorkspacePath(canonicalTarget, canonicalPathAfter) ||
      !sameWorkspacePath(canonicalPathAfter, target)
    ) {
      throw new Error(`Artifact changed while reading: ${artifactPath}.`);
    }
    options.signal?.throwIfAborted();
    return bytes;
  } finally {
    await handle.close().catch(() => undefined);
  }
}

function planTaskInput(proposal: V3GroupPlanProposal): V3GroupPlanProposal['tasks'][number][] {
  return proposal.tasks;
}

function taskForPrompt(task: V3GroupPlanTask): V3GroupPlanProposal['tasks'][number] {
  return {
    taskKey: task.taskKey,
    title: task.title,
    description: task.description,
    ownerWakerId: task.ownerWakerId,
    reviewerWakerIds: [...task.reviewerWakerIds],
    dependsOnTaskKeys: [...task.dependsOnTaskKeys],
    acceptanceCriteria: structuredClone(task.acceptanceCriteria),
    evidenceRequirements: structuredClone(task.evidenceRequirements),
    recommendedSkillIds: [],
  };
}

function aggregateSystemPrompt(
  member: V3GroupPromptMember,
  missionId: string,
  preview?: { url: string; entryPath: string },
): string {
  return `You are the ${member.name} Leader Waker for QoderWake mission ${missionId}.
All Plan tasks have completed with validated evidence. Produce a concise final delivery summary based only on the supplied task results. Include actual artifact paths and verified URLs if present. Do not invent results, files, tests, or links. Return only user-facing prose. Never return a Plan, schema JSON, role-run report, protocol marker, or Markdown code fence.${
    preview
      ? `\nThe host has independently verified the persistent preview entry ${preview.entryPath}. The exact delivery URL is ${preview.url}. Include this exact URL; do not substitute another localhost URL.`
      : ''
  }`;
}

const INTERNAL_LEADER_SUMMARY =
  /(?:^|\n)(?:END_)?QODER_TEAM_(?:PLAN_PROPOSAL|ROLE_RUN_REPORT)(?:\n|$)|"reportType"\s*:\s*"(?:group_plan_proposal|role_run_completion)"/iu;

function leaderSummaryIssue(value: string): string | undefined {
  const summary = value.trim();
  if (!summary) return 'Leader aggregation returned no delivery summary.';
  if (INTERNAL_LEADER_SUMMARY.test(summary)) {
    return 'Leader aggregation returned an internal structured protocol instead of user-facing prose.';
  }
  if (summary.length > 12_000) return 'Leader aggregation exceeded the user-facing summary limit.';
  return undefined;
}

function fallbackLeaderSummary(
  snapshot: V3GroupMissionSnapshot,
  prompt: string,
  preview?: { url: string; entryPath: string },
): string {
  const plan = snapshot.plans.at(-1);
  const titles = (plan?.tasks ?? []).map(({ title }) => title).filter(Boolean);
  const titleList = titles.slice(0, 6).join(/\p{Script=Han}/u.test(prompt) ? '、' : ', ');
  const remaining = Math.max(0, titles.length - 6);
  const chinese = /\p{Script=Han}/u.test(prompt);
  const summary = chinese
    ? `已完成并验证全部 ${titles.length} 个计划任务${titleList ? `：${titleList}${remaining ? `等 ${remaining} 项` : ''}` : ''}。所有完成结论均来自已持久化的任务与证据。`
    : `All ${titles.length} planned tasks have completed with persisted evidence${titleList ? `: ${titleList}${remaining ? ` and ${remaining} more` : ''}` : ''}.`;
  return preview ? `${summary}\n\n${preview.url}` : summary;
}

function previewContract(preview?: { url: string; entryPath: string }): string {
  return preview
    ? `\n\nOptional persistent preview capability:\n- Use this only when the confirmed user request and Plan require a browser-deliverable artifact. Do not create a preview for document, analysis, or other non-browser work.\n- When required, the host serves the shared workspace at ${preview.url} and the browser entry file must be ${preview.entryPath} relative to the shared workspace root.\n- Verify that exact entry and URL. Do not claim a different localhost port or a sandbox-only server as the delivery link.`
    : '';
}

function canonicalPreviewSummary(summary: string, previewUrl: string): string {
  const escapedUrl = previewUrl.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
  const previewVariant = new RegExp(`${escapedUrl}[A-Za-z0-9._~!$&'()*+,;=:@%/?#-]*`, 'gu');
  let included = false;
  const normalized = summary
    .replace(previewVariant, () => {
      if (included) return '';
      included = true;
      return previewUrl;
    })
    .trim();
  return included ? normalized : `${normalized}\n\n${previewUrl}`;
}

function isReportOnlyFailure(
  category: string | null | undefined,
  detail: string | null | undefined,
): boolean {
  return (
    category === 'invalid_structured_report' &&
    Boolean(
      detail &&
      /structured-report schema|report (?:roleRunId|taskId|planVersion) mismatch|Evidence kind mismatch|completion\/|unresolved issues|ready for review|marker|valid JSON/iu.test(
        detail,
      ),
    )
  );
}

async function assertArtifactsExist(
  workspaceRoot: string,
  artifacts: Array<{ path: string }>,
): Promise<string | undefined> {
  const root = resolve(workspaceRoot);
  let canonicalRoot: string;
  try {
    const rootEntry = (await lstat(root, { bigint: true })) as BigIntWorkspaceFileStats;
    if (!rootEntry.isDirectory() || rootEntry.isSymbolicLink()) {
      return 'Shared workspace is not a plain directory.';
    }
    canonicalRoot = await realpath(root);
    if (!sameWorkspacePath(canonicalRoot, root)) {
      return 'Shared workspace path traverses a link.';
    }
  } catch {
    return 'Declared artifact does not exist in the shared workspace.';
  }
  for (const artifact of artifacts) {
    let target: string;
    try {
      target = workspacePathTarget(root, artifact.path).target;
    } catch (error) {
      return error instanceof Error
        ? error.message
        : `Artifact escapes the shared workspace: ${artifact.path}.`;
    }
    try {
      const metadata = (await lstat(target, { bigint: true })) as BigIntWorkspaceFileStats;
      if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1n) {
        return `Artifact is not a plain file: ${artifact.path}.`;
      }
      const canonicalTarget = await realpath(target);
      if (
        !isWorkspaceDescendant(canonicalRoot, canonicalTarget) ||
        !sameWorkspacePath(canonicalTarget, target)
      ) {
        return `Artifact path traverses a link: ${artifact.path}.`;
      }
    } catch (error) {
      if (error instanceof Error && 'code' in error && error.code !== 'ENOENT') {
        return `Artifact cannot be read: ${artifact.path}.`;
      }
      return `Declared artifact does not exist in the shared workspace: ${artifact.path}.`;
    }
  }
  return undefined;
}

async function inspectVerificationReports(
  workspaceRoot: string,
  evidence: Array<{ kind: string; artifactPath: string }>,
): Promise<V3VerificationReportIssue | undefined> {
  for (const item of evidence) {
    if (item.kind !== 'verification_report' || !item.artifactPath.toLowerCase().endsWith('.json')) {
      continue;
    }
    let report: unknown;
    try {
      report = JSON.parse(
        (await readV3SharedWorkspaceFile(workspaceRoot, item.artifactPath)).toString('utf8'),
      );
    } catch {
      return {
        detail: `Verification report is not valid JSON: ${item.artifactPath}.`,
        artifactPath: item.artifactPath,
        requiresRemediation: false,
      };
    }
    if (typeof report !== 'object' || report === null || !('status' in report)) continue;
    const record = report as Record<string, unknown>;
    const status = record.status;
    const normalizedStatus = typeof status === 'string' ? status.trim().toLowerCase() : undefined;
    const completion = record.completion;
    const completedRoleRun =
      normalizedStatus === 'completed' &&
      record.schemaVersion === '3.0.0' &&
      record.reportType === 'role_run_completion' &&
      Array.isArray(record.unresolvedIssues) &&
      record.unresolvedIssues.length === 0 &&
      typeof completion === 'object' &&
      completion !== null &&
      !Array.isArray(completion) &&
      (completion as { readyForReview?: unknown }).readyForReview === true;
    if (
      typeof status === 'string' &&
      normalizedStatus !== 'pass' &&
      normalizedStatus !== 'passed' &&
      !completedRoleRun
    ) {
      const interactionError = (report as { interactionError?: unknown }).interactionError;
      const transientDetail =
        typeof interactionError === 'string' && interactionError ? `: ${interactionError}` : '.';
      return {
        detail: `Verification report ${item.artifactPath} reported status ${status}${transientDetail}`,
        artifactPath: item.artifactPath,
        requiresRemediation: !(typeof interactionError === 'string' && interactionError),
      };
    }
  }
  return undefined;
}

export class V3GroupMissionRunner {
  private readonly maxPlanAttempts: number;
  private readonly maxLeaderSummaryAttempts: number;
  private readonly maxRoleRunAttempts: number;
  private readonly maxRemediationPlans: number;
  private readonly commandTimeoutMs: number;
  private readonly commandLeaseMs: number;
  private readonly commandLeaseRefreshMs: number;
  constructor(private readonly options: V3GroupMissionRunnerOptions) {
    this.maxPlanAttempts = options.maxPlanAttempts ?? 3;
    this.maxLeaderSummaryAttempts = options.maxLeaderSummaryAttempts ?? 2;
    this.maxRoleRunAttempts = options.maxRoleRunAttempts ?? 3;
    this.maxRemediationPlans = options.maxRemediationPlans ?? 3;
    this.commandTimeoutMs = options.commandTimeoutMs ?? 60 * 60_000;
    this.commandLeaseMs = options.commandLeaseMs ?? 60_000;
    this.commandLeaseRefreshMs = options.commandLeaseRefreshMs ?? 30_000;
  }

  async run(missionId: string): Promise<V3GroupMissionRunResult> {
    const record = await this.options.store.get(missionId);
    if (!record) throw new Error(`Group mission not found: ${missionId}.`);
    const aggregate = V3GroupMissionAggregate.hydrate(record.snapshot);
    const profiles = new Map(record.profiles.map((profile) => [profile.wakerId, profile]));
    const leader = this.requireProfile(profiles, record.snapshot.leaderWakerId);
    this.requireAllProfiles(profiles, record.snapshot);
    const recoveries = aggregate.recoverInterruptedRoleRuns(this.maxRoleRunAttempts);
    for (const recovery of recoveries) {
      await this.persist(aggregate, 'role_run.interrupted', recovery);
    }

    const initialLatestPlan = record.snapshot.plans.at(-1);
    let proposedNow = false;
    let autoConfirmFollowup = false;
    if (record.snapshot.plans.length === 0) {
      await this.plan(record, aggregate, leader, profiles, false);
      proposedNow = true;
    } else if (initialLatestPlan?.state === 'superseded') {
      await this.persist(aggregate, 'plan.superseded', {
        planVersion: initialLatestPlan.version,
      });
      await this.plan(record, aggregate, leader, profiles, false);
      proposedNow = true;
    } else if (initialLatestPlan?.state === 'completed') {
      await this.plan(record, aggregate, leader, profiles, true);
      proposedNow = true;
      autoConfirmFollowup = true;
    }
    let snapshot = aggregate.snapshot();
    const proposedPlan = snapshot.plans.at(-1);
    if (proposedPlan?.state === 'proposed') {
      if (autoConfirmFollowup) {
        const confirmed = aggregate.confirmPlan(proposedPlan.version, leader.wakerId);
        await this.persist(aggregate, 'plan.confirmed', {
          planVersion: proposedPlan.version,
          actorWakerId: leader.wakerId,
          roleRunIds: confirmed.roleRuns.map((roleRun) => roleRun.id),
          confirmationMode: 'automatic_completed_mission_followup',
        });
        snapshot = aggregate.snapshot();
      } else {
        if (proposedNow) {
          await this.persist(aggregate, 'plan.awaiting_confirmation', {
            planVersion: proposedPlan.version,
          });
        }
        return {
          status: 'awaiting_confirmation',
          planVersion: proposedPlan.version,
          snapshot: aggregate.snapshot(),
        };
      }
    }
    let remediationPlans = Math.max(0, snapshot.plans.length - 1);
    while (true) {
      const latestPlan = snapshot.plans.at(-1);
      if (!latestPlan) throw new Error('Leader did not produce a Plan.');
      const verificationFailures = await this.executePlan(record, aggregate, profiles);
      snapshot = aggregate.snapshot();
      if (verificationFailures.length === 0) break;
      remediationPlans += 1;
      if (remediationPlans > this.maxRemediationPlans) {
        throw new Error(
          `Verification remediation exceeded ${this.maxRemediationPlans} Plan attempts: ${verificationFailures
            .map(({ detail }) => detail)
            .join('; ')}`,
        );
      }
      await this.persist(aggregate, 'mission.remediation_planning', {
        priorPlanVersion: snapshot.plans.at(-1)?.version,
        remediationAttempt: remediationPlans,
        failures: verificationFailures,
      });
      await this.plan(record, aggregate, leader, profiles, true, verificationFailures);
      snapshot = aggregate.snapshot();
      const remediationPlan = snapshot.plans.at(-1);
      if (!remediationPlan || remediationPlan.state !== 'proposed') {
        throw new Error('Leader did not produce a remediation Plan.');
      }
      await this.persist(aggregate, 'plan.awaiting_confirmation', {
        planVersion: remediationPlan.version,
        remediationAttempt: remediationPlans,
      });
      return {
        status: 'awaiting_confirmation',
        planVersion: remediationPlan.version,
        snapshot: aggregate.snapshot(),
      };
    }
    const completedPlan = snapshot.plans.at(-1);
    if (!completedPlan || completedPlan.state !== 'completed') {
      throw new Error('Group mission cannot be aggregated before its confirmed Plan completes.');
    }
    const leaderWorkspaceRoot = await this.memberWorkspaceRoot(leader, record.workspaceRoot);
    const availablePreview =
      this.options.preview &&
      !(await assertArtifactsExist(leaderWorkspaceRoot, [{ path: this.options.preview.entryPath }]))
        ? this.options.preview
        : undefined;

    let leaderSummary = '';
    let lastSummaryIssue = 'Leader aggregation returned no delivery summary.';
    await this.persist(aggregate, 'mission.summarizing', {
      planVersion: completedPlan.version,
      taskCount: completedPlan.tasks.length,
    });
    for (let attempt = 1; attempt <= this.maxLeaderSummaryAttempts; attempt += 1) {
      const executionId = randomUUID();
      let summaryResult: V3GroupAgentRunResult;
      try {
        summaryResult = await this.options.runAgent({
          kind: 'leader_aggregate',
          executionId,
          missionId,
          member: leader,
          workspaceRoot: leaderWorkspaceRoot,
          sessionPath: join(this.options.sessionRoot, missionId, `leader-aggregate-${attempt}.jsonl`),
          systemPrompt: aggregateSystemPrompt(leader, missionId, availablePreview),
          prompt: `${
            attempt === 1
              ? ''
              : `The previous delivery summary was rejected: ${lastSummaryIssue}\nReturn concise user-facing prose only.\n\n`
          }Original request:\n${record.prompt}\n\nValidated mission state:\n${JSON.stringify(snapshot, null, 2)}${previewContract(availablePreview)}`,
        });
      } catch (cause) {
        await this.persist(aggregate, 'leader.attempt.failed', {
          phase: 'aggregate',
          attempt,
          executionId,
          memberWakerId: leader.wakerId,
          model: leader.model,
          workspaceReferenceId: leader.workspaceReferenceId,
          detail: runFailureDetail(cause),
        });
        throw cause;
      }
      await this.persist(aggregate, 'leader.attempt.completed', {
        phase: 'aggregate',
        attempt,
        executionId,
        memberWakerId: leader.wakerId,
        model: leader.model,
        workspaceReferenceId: leader.workspaceReferenceId,
        usage: summaryResult.usage ?? null,
        providerCorrelationId: redactProviderCorrelation(summaryResult.providerCorrelationId),
      });
      const candidate = summaryResult.resultText.trim();
      const issue = leaderSummaryIssue(candidate);
      if (!issue) {
        leaderSummary = candidate;
        break;
      }
      lastSummaryIssue = issue;
      await this.persist(aggregate, 'mission.summary_rejected', {
        attempt,
        maxAttempts: this.maxLeaderSummaryAttempts,
        category: 'invalid_leader_summary',
        detail: issue,
      });
    }
    if (!leaderSummary) {
      leaderSummary = fallbackLeaderSummary(snapshot, record.prompt, availablePreview);
      await this.persist(aggregate, 'mission.summary_fallback', {
        attempts: this.maxLeaderSummaryAttempts,
        category: 'invalid_leader_summary',
        detail: lastSummaryIssue,
      });
    }
    const summary = availablePreview
      ? canonicalPreviewSummary(leaderSummary, availablePreview.url)
      : leaderSummary;
    await this.persist(aggregate, 'mission.completed', {
      planVersion: completedPlan.version,
      summary,
      ...(availablePreview ? { previewUrl: availablePreview.url } : {}),
    });
    return {
      status: 'completed',
      summary,
      snapshot: aggregate.snapshot(),
      ...(availablePreview ? { previewUrl: availablePreview.url } : {}),
    };
  }

  private async plan(
    record: V3GroupMissionStoreRecord,
    aggregate: V3GroupMissionAggregate,
    leader: V3GroupPromptMember,
    profiles: ReadonlyMap<string, V3GroupPromptMember>,
    followup: boolean,
    remediationFailures: V3VerificationFailure[] = [],
  ): Promise<void> {
    const leaderWorkspaceRoot = await this.memberWorkspaceRoot(leader, record.workspaceRoot);
    const expected = {
      missionId: record.id,
      missionGoal: record.snapshot.goal,
      leaderWakerId: record.snapshot.leaderWakerId,
      members: record.snapshot.members.map((member) => this.requireProfile(profiles, member.wakerId)),
      requiredOwnerWakerIds: record.mentionedWakerIds,
    };
    const priorPlan = followup ? aggregate.snapshot().plans.at(-1) : undefined;
    const remediation = remediationFailures.length > 0;
    const systemPrompt = `${buildV3GroupLeaderSystemPrompt(expected)}${previewContract(this.options.preview)}${
      priorPlan
        ? remediation
          ? `\n\nThis is a remediation of completed Plan v${priorPlan.version} after deterministic acceptance evidence failed. Return the full next Plan, not only the new work. Every prior task must remain present with the same taskKey, ownerWakerId, acceptanceCriteria, and evidenceRequirements. Carry completed work forward, add the smallest executable repair and re-verification tasks, and make re-verification depend on the repair. Do not erase or rewrite the failed evidence. Prior validated Plan:\n${JSON.stringify(priorPlan, null, 2)}`
          : `\n\nThis is a follow-up to completed Plan v${priorPlan.version}. Return the full next Plan, not only the new work. Every prior task must remain present with the same taskKey, ownerWakerId, acceptanceCriteria, and evidenceRequirements. Add only the work necessary for the follow-up. Prior validated Plan:\n${JSON.stringify(priorPlan, null, 2)}`
        : ''
    }`;
    let lastFailure = 'Leader produced no Plan proposal.';
    for (let attempt = 1; attempt <= this.maxPlanAttempts; attempt += 1) {
      const executionId = randomUUID();
      let result: V3GroupAgentRunResult;
      try {
        result = await this.options.runAgent({
          kind: 'leader_plan',
          executionId,
          missionId: record.id,
          member: leader,
          workspaceRoot: leaderWorkspaceRoot,
          sessionPath: join(this.options.sessionRoot, record.id, 'leader-plan.jsonl'),
          systemPrompt,
          prompt:
            attempt === 1
              ? remediation
                ? `Create the executable remediation Plan. Verification failures requiring remediation:\n${JSON.stringify(remediationFailures, null, 2)}`
                : followup
                  ? `Create the executable follow-up Plan for this new user input:\n${record.prompt}`
                  : `Create the executable Plan for this user request:\n${record.prompt}`
              : `The previous Plan proposal was rejected: ${lastFailure}\nReturn a corrected full Plan proposal.`,
        });
      } catch (cause) {
        await this.persist(aggregate, 'leader.attempt.failed', {
          phase: 'plan',
          attempt,
          executionId,
          memberWakerId: leader.wakerId,
          model: leader.model,
          workspaceReferenceId: leader.workspaceReferenceId,
          detail: runFailureDetail(cause),
        });
        throw cause;
      }
      await this.persist(aggregate, 'leader.attempt.completed', {
        phase: 'plan',
        attempt,
        executionId,
        memberWakerId: leader.wakerId,
        model: leader.model,
        workspaceReferenceId: leader.workspaceReferenceId,
        usage: result.usage ?? null,
        providerCorrelationId: redactProviderCorrelation(result.providerCorrelationId),
      });
      const parsed = parseV3GroupPlanProposal(result.resultText, expected);
      if (!parsed.ok) {
        lastFailure = parsed.detail;
        await this.persist(aggregate, 'plan.proposal_rejected', {
          attempt,
          category: parsed.category,
          detail: parsed.detail,
        });
        continue;
      }
      let proposed;
      try {
        const tasks = planTaskInput(parsed.proposal).map(({ recommendedSkillIds: _skills, ...task }) => task);
        const details = {
          goal: parsed.proposal.goal,
          scope: parsed.proposal.scope,
          outOfScope: parsed.proposal.outOfScope,
          constraints: parsed.proposal.constraints,
          risks: parsed.proposal.risks,
          completionPolicy: parsed.proposal.completionPolicy,
        };
        proposed = followup
          ? aggregate.proposeFollowupPlan(tasks, details)
          : aggregate.proposePlan(tasks, details);
      } catch (cause) {
        lastFailure = runFailureDetail(cause);
        await this.persist(aggregate, 'plan.proposal_rejected', {
          attempt,
          category: 'invalid_plan_proposal',
          detail: lastFailure,
        });
        continue;
      }
      await this.persist(aggregate, 'plan.proposed', {
        attempt,
        planVersion: proposed.version,
        plan: proposed,
        taskCount: proposed.tasks.length,
        acceptanceCount: proposed.tasks.reduce((total, task) => total + task.acceptanceCriteria.length, 0),
        evidenceRequirementCount: proposed.tasks.reduce(
          (total, task) => total + task.evidenceRequirements.length,
          0,
        ),
        ...(remediation ? { reason: 'verification_remediation', remediationFailures } : {}),
      });
      return;
    }
    throw new Error(`Leader Plan failed after ${this.maxPlanAttempts} attempts: ${lastFailure}`);
  }

  private async executePlan(
    record: V3GroupMissionStoreRecord,
    aggregate: V3GroupMissionAggregate,
    profiles: ReadonlyMap<string, V3GroupPromptMember>,
  ): Promise<V3VerificationFailure[]> {
    const remediationFailures: V3VerificationFailure[] = [];
    while (true) {
      const runnable = aggregate.runnableRoleRuns();
      if (runnable.length === 0) {
        const snapshot = aggregate.snapshot();
        const latest = snapshot.plans.at(-1);
        if (latest?.state === 'completed') return remediationFailures;
        const failed = snapshot.roleRuns.find(
          (roleRun) => roleRun.planVersion === latest?.version && roleRun.state === 'failed',
        );
        if (failed) throw new Error(`RoleRun exhausted retries: ${failed.id}.`);
        throw new Error('Confirmed Plan is blocked with no runnable RoleRun.');
      }

      for (const queued of runnable) {
        const started = aggregate.startRoleRun(queued.id);
        const previousAttempt = started.attempts.at(-2);
        const reportRepair = isReportOnlyFailure(
          previousAttempt?.failureCategory,
          previousAttempt?.failureDetail,
        );
        const member = this.requireProfile(profiles, started.ownerWakerId);
        await this.persist(aggregate, 'role_run.started', {
          roleRunId: started.id,
          taskId: started.taskId,
          taskKey: started.taskKey,
          ownerWakerId: started.ownerWakerId,
          attempt: started.attemptCount,
          reportRepair,
          model: member.model,
          workspaceReferenceId: member.workspaceReferenceId,
        });
        const snapshot = aggregate.snapshot();
        const plan = snapshot.plans.find((candidate) => candidate.version === started.planVersion)!;
        const task = plan.tasks.find((candidate) => candidate.id === started.taskId)!;
        const promptTask = taskForPrompt(task);
        const memberWorkspaceRoot = await this.memberWorkspaceRoot(member, record.workspaceRoot);
        const dependencyHandoffs = task.dependsOnTaskKeys.map((taskKey) => {
          const dependencyTask = plan.tasks.find((candidate) => candidate.taskKey === taskKey)!;
          const dependencyRun = snapshot.roleRuns.find(
            (candidate) => candidate.taskId === dependencyTask.id && candidate.state === 'completed',
          );
          return {
            taskKey,
            summary: `${dependencyTask.title} completed with validated evidence.`,
            artifacts: dependencyRun?.evidence.map((item) => item.artifactPath) ?? [],
            evidence: dependencyRun?.evidence.map((item) => item.requirementKey) ?? [],
          };
        });
        const executionId = randomUUID();
        const hardDeadlineAt = new Date(Date.now() + this.commandTimeoutMs).toISOString();
        const command = aggregate.createExecutorCommand(started.id, hardDeadlineAt);
        await this.persist(aggregate, 'executor_command.created', {
          commandId: command.id,
          roleRunId: started.id,
          attempt: started.attemptCount,
          hardDeadlineAt,
        });
        const leaseExpiresAt = new Date(Date.now() + this.commandLeaseMs).toISOString();
        aggregate.leaseExecutorCommand(command.id, executionId, leaseExpiresAt);
        await this.persist(aggregate, 'executor_command.leased', {
          commandId: command.id,
          roleRunId: started.id,
          leaseOwnerId: executionId,
          leaseExpiresAt,
        });
        aggregate.dispatchExecutorCommand(command.id);
        await this.persist(aggregate, 'executor_command.dispatched', {
          commandId: command.id,
          roleRunId: started.id,
        });
        aggregate.acknowledgeExecutorCommand(command.id);
        await this.persist(aggregate, 'executor_command.acknowledged', {
          commandId: command.id,
          roleRunId: started.id,
        });
        let result: V3GroupAgentRunResult;
        try {
          const previousFailure = previousAttempt?.failureDetail;
          const executionPrompt = reportRepair
            ? `Report repair only. Do not call tools, modify files, repeat verification, or redo the completed task. Re-emit only the final marker-delimited structured report for the already completed work. Use every authoritative requirementKey, acceptance key, and evidence kind from the system prompt exactly. Parser diagnostics from the previous report:\n${previousFailure}`
            : `Execute your confirmed task for this original user request:\n${record.prompt}${
                previousFailure
                  ? `\n\nPrevious attempt was rejected: ${previousFailure}\nCorrect the reported task or evidence problem. Reuse existing valid files and verification where possible. A requirementKey may appear in multiple evidence entries when distinct persisted files support it. A completed report requires unresolvedIssues to be [] and readyForReview to be true. Return the marker-delimited raw JSON block exactly as required, with no Markdown code fences.`
                  : ''
              }`;
          result = await this.runAcknowledgedCommand(
            aggregate,
            command.id,
            executionId,
            Date.parse(hardDeadlineAt),
            () =>
              this.options.runAgent({
                kind: 'role_run',
                reportRepair,
                executionId,
                missionId: record.id,
                member,
                roleRunId: started.id,
                taskId: started.taskId,
                planVersion: started.planVersion,
                task: promptTask,
                workspaceRoot: memberWorkspaceRoot,
                sessionPath: join(this.options.sessionRoot, record.id, 'role-runs', `${started.id}.jsonl`),
                systemPrompt: `${buildV3GroupRoleRunSystemPrompt({
                  missionId: record.id,
                  roleRunId: started.id,
                  taskId: started.taskId,
                  planVersion: started.planVersion,
                  member,
                  task: promptTask,
                  dependencyHandoffs,
                })}${previewContract(this.options.preview)}`,
                prompt: executionPrompt,
              }),
          );
          await this.persist(aggregate, 'role_run.attempt.completed', {
            roleRunId: started.id,
            taskId: started.taskId,
            planVersion: started.planVersion,
            attempt: started.attemptCount,
            reportRepair,
            executionId,
            memberWakerId: member.wakerId,
            model: member.model,
            workspaceReferenceId: member.workspaceReferenceId,
            usage: result.usage ?? null,
            providerCorrelationId: redactProviderCorrelation(result.providerCorrelationId),
          });
        } catch (cause) {
          const detail = runFailureDetail(cause);
          aggregate.failExecutorCommand(command.id, 'executor_error', detail);
          await this.persist(aggregate, 'executor_command.failed', {
            commandId: command.id,
            roleRunId: started.id,
            executionId,
            memberWakerId: member.wakerId,
            model: member.model,
            workspaceReferenceId: member.workspaceReferenceId,
            category: 'executor_error',
            detail,
          });
          const failed = aggregate.failRoleRun(started.id, {
            category: 'executor_error',
            detail,
            retryable: true,
            maxAttempts: this.maxRoleRunAttempts,
          });
          await this.persist(aggregate, 'role_run.execution_failed', {
            roleRunId: started.id,
            taskId: started.taskId,
            taskKey: started.taskKey,
            ownerWakerId: started.ownerWakerId,
            attempt: started.attemptCount,
            detail,
            retryQueued: failed.state === 'queued',
          });
          continue;
        }
        const expected = {
          roleRunId: started.id,
          taskId: started.taskId,
          planVersion: started.planVersion,
          requiredAcceptanceKeys: task.acceptanceCriteria.map((criterion) => criterion.key),
          requiredEvidenceKeys: task.evidenceRequirements.map((requirement) => requirement.key),
          requiredEvidenceKinds: Object.fromEntries(
            task.evidenceRequirements.map((requirement) => [requirement.key, requirement.kind]),
          ),
        };
        const parsed = parseV3RoleRunReport(result.resultText, expected);
        let rejection = parsed.ok
          ? await assertArtifactsExist(memberWorkspaceRoot, [
              ...parsed.report.artifacts,
              ...parsed.report.evidence.map((evidence) => ({ path: evidence.artifactPath })),
            ])
          : parsed.detail;
        if (parsed.ok && !rejection) {
          const expectedKinds = new Map(
            task.evidenceRequirements.map((requirement) => [requirement.key, requirement.kind]),
          );
          const mismatch = parsed.report.evidence.find(
            (evidence) => expectedKinds.get(evidence.requirementKey) !== evidence.kind,
          );
          if (mismatch) rejection = `Evidence kind mismatch for ${mismatch.requirementKey}.`;
        }
        const verificationIssue =
          parsed.ok && !rejection
            ? await inspectVerificationReports(memberWorkspaceRoot, parsed.report.evidence)
            : undefined;
        if (verificationIssue && !verificationIssue.requiresRemediation) {
          rejection = verificationIssue.detail;
        }
        let persistedArtifacts = parsed.ok ? parsed.report.artifacts : [];
        if (parsed.ok && !rejection && this.options.persistArtifacts) {
          try {
            const artifacts = await Promise.all(
              parsed.report.artifacts.map(async (artifact) => ({
                ...artifact,
                bytes: await readV3SharedWorkspaceFile(memberWorkspaceRoot, artifact.path),
              })),
            );
            persistedArtifacts = await this.options.persistArtifacts({
              missionId: record.id,
              roleRunId: started.id,
              workspaceRoot: memberWorkspaceRoot,
              artifacts,
            });
          } catch (cause) {
            rejection = `Artifact persistence failed: ${runFailureDetail(cause)}`;
          }
        }
        if (!parsed.ok || rejection || parsed.report.status !== 'completed') {
          const rawDetail =
            rejection ??
            (parsed.ok
              ? parsed.report.unresolvedIssues.join('; ') || 'RoleRun reported blocked.'
              : parsed.detail);
          const detail = redactRunFailureDetail(rawDetail);
          aggregate.failExecutorCommand(command.id, 'invalid_structured_report', detail);
          await this.persist(aggregate, 'executor_command.failed', {
            commandId: command.id,
            roleRunId: started.id,
            category: 'invalid_structured_report',
            detail,
          });
          const failed = aggregate.failRoleRun(started.id, {
            category: parsed.ok ? 'invalid_structured_report' : parsed.category,
            detail,
            retryable: true,
            maxAttempts: this.maxRoleRunAttempts,
          });
          await this.persist(aggregate, 'role_run.report_rejected', {
            roleRunId: started.id,
            taskId: started.taskId,
            taskKey: started.taskKey,
            ownerWakerId: started.ownerWakerId,
            attempt: started.attemptCount,
            category: 'invalid_structured_report',
            detail,
            retryQueued: failed.state === 'queued',
            maxAttempts: this.maxRoleRunAttempts,
          });
          continue;
        }
        aggregate.completeExecutorCommand(command.id);
        await this.persist(aggregate, 'executor_command.completed', {
          commandId: command.id,
          roleRunId: started.id,
          attempt: started.attemptCount,
        });
        aggregate.completeRoleRun(started.id, {
          acceptanceKeys: parsed.report.completion.acceptanceKeys,
          evidence: parsed.report.evidence.map((evidence) => ({
            requirementKey: evidence.requirementKey,
            artifactPath: evidence.artifactPath,
          })),
        });
        if (verificationIssue?.requiresRemediation) {
          const failure: V3VerificationFailure = {
            taskKey: started.taskKey,
            ownerWakerId: started.ownerWakerId,
            roleRunId: started.id,
            detail: redactRunFailureDetail(verificationIssue.detail),
            artifactPath: verificationIssue.artifactPath,
          };
          remediationFailures.push(failure);
          await this.persist(aggregate, 'role_run.verification_failed', {
            ...failure,
            taskId: started.taskId,
            attempt: started.attemptCount,
            summary: parsed.report.summary,
            evidence: parsed.report.evidence,
          });
        }
        await this.persist(aggregate, 'role_run.completed', {
          roleRunId: started.id,
          taskId: started.taskId,
          taskKey: started.taskKey,
          ownerWakerId: started.ownerWakerId,
          attempt: started.attemptCount,
          summary: parsed.report.summary,
          artifacts: persistedArtifacts,
          evidence: parsed.report.evidence,
          verificationOutcome: verificationIssue?.requiresRemediation ? 'failed' : 'passed',
        });
      }
    }
  }

  private async runAcknowledgedCommand(
    aggregate: V3GroupMissionAggregate,
    commandId: string,
    leaseOwnerId: string,
    hardDeadlineMs: number,
    operation: () => Promise<V3GroupAgentRunResult>,
  ): Promise<V3GroupAgentRunResult> {
    const outcome = operation().then(
      (value) => ({ kind: 'completed' as const, value }),
      (cause: unknown) => ({ kind: 'failed' as const, cause }),
    );
    while (true) {
      const remaining = hardDeadlineMs - Date.now();
      if (remaining <= 0) throw new Error('ExecutorCommand exceeded its hard timeout.');
      let timer: ReturnType<typeof setTimeout> | undefined;
      const tick = new Promise<{ kind: 'lease_refresh' }>((resolveTick) => {
        timer = setTimeout(
          () => resolveTick({ kind: 'lease_refresh' }),
          Math.min(this.commandLeaseRefreshMs, remaining),
        );
      });
      const next = await Promise.race([outcome, tick]);
      if (timer) clearTimeout(timer);
      if (next.kind === 'completed') return next.value;
      if (next.kind === 'failed') throw next.cause;
      if (Date.now() >= hardDeadlineMs) throw new Error('ExecutorCommand exceeded its hard timeout.');
      const leaseExpiresAt = new Date(Date.now() + this.commandLeaseMs).toISOString();
      aggregate.refreshExecutorCommandLease(commandId, leaseOwnerId, leaseExpiresAt);
      await this.persist(aggregate, 'executor_command.lease_refreshed', {
        commandId,
        leaseOwnerId,
        leaseExpiresAt,
      });
    }
  }

  private requireProfile(
    profiles: ReadonlyMap<string, V3GroupPromptMember>,
    wakerId: string,
  ): V3GroupPromptMember {
    const profile = profiles.get(wakerId);
    if (!profile) throw new Error(`Effective Waker profile is missing: ${wakerId}.`);
    return profile;
  }

  private requireAllProfiles(
    profiles: ReadonlyMap<string, V3GroupPromptMember>,
    snapshot: V3GroupMissionSnapshot,
  ): void {
    for (const member of snapshot.members) this.requireProfile(profiles, member.wakerId);
  }

  private async memberWorkspaceRoot(
    member: V3GroupPromptMember,
    fallbackWorkspaceRoot: string,
  ): Promise<string> {
    return this.options.resolveMemberWorkspaceRoot
      ? this.options.resolveMemberWorkspaceRoot(member, fallbackWorkspaceRoot)
      : fallbackWorkspaceRoot;
  }

  private async persist(
    aggregate: V3GroupMissionAggregate,
    type: string,
    payload: Record<string, unknown>,
  ): Promise<void> {
    const snapshot = aggregate.snapshot();
    await this.options.store.appendSnapshot(snapshot.missionId, snapshot, { type, payload });
  }
}
