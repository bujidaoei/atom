import type { V3GroupPlanProposal } from '../../product-contracts/src/v3.ts';
import { V3GroupPlanProposalSchema } from '../../product-contracts/src/v3.ts';
import { Value } from 'typebox/value';

import {
  V3GroupMissionAggregate,
  type V3GroupMissionMember,
  type V3GroupPlanTaskInput,
} from './v3-group-orchestrator.ts';
import { V3_ROLE_RUN_REPORT_END, V3_ROLE_RUN_REPORT_START } from './v3-role-run-report.ts';
import { unwrapSingleJsonFence } from './v3-structured-json.ts';

export type { V3GroupPlanProposal } from '../../product-contracts/src/v3.ts';

export const V3_GROUP_PLAN_PROPOSAL_START = 'QODER_TEAM_PLAN_PROPOSAL' as const;
export const V3_GROUP_PLAN_PROPOSAL_END = 'END_QODER_TEAM_PLAN_PROPOSAL' as const;

export interface V3GroupPromptMember extends Omit<V3GroupMissionMember, 'available'> {
  bio: string;
  model: string;
  workspaceReferenceId: string | null;
  configurationVersionId?: string;
  effectiveSystemPrompt?: string;
}

export interface V3ExpectedGroupPlanProposal {
  missionId: string;
  missionGoal: string;
  leaderWakerId: string;
  members: V3GroupPromptMember[];
  requiredOwnerWakerIds: string[];
}

export type V3GroupPlanProposalParseResult =
  | { ok: true; proposal: V3GroupPlanProposal }
  | { ok: false; category: 'invalid_plan_proposal'; detail: string };

export interface V3GroupRoleRunPromptInput {
  missionId: string;
  roleRunId: string;
  taskId: string;
  planVersion: number;
  member: V3GroupPromptMember;
  task: V3GroupPlanProposal['tasks'][number];
  dependencyHandoffs: Array<{
    taskKey: string;
    summary: string;
    artifacts: string[];
    evidence: string[];
  }>;
}

function extractDelimitedJson(output: string, startMarker: string, endMarker: string): unknown {
  const lines = output.split(/\r?\n/u);
  const starts = lines.flatMap((line, index) => (line.trim() === startMarker ? [index] : []));
  const ends = lines.flatMap((line, index) => (line.trim() === endMarker ? [index] : []));
  const start = starts[0];
  const end = ends[0];
  if (starts.length === 1 && ends.length === 1 && start !== undefined && end !== undefined && end > start) {
    const encoded = lines
      .slice(start + 1, end)
      .join('\n')
      .trim();
    return JSON.parse(unwrapSingleJsonFence(encoded) ?? encoded) as unknown;
  }
  if (starts.length === 0 && ends.length === 1 && end !== undefined) {
    const trailing = lines
      .slice(end + 1)
      .join('\n')
      .trim();
    const encoded = unwrapSingleJsonFence(lines.slice(0, end).join('\n'));
    if (!trailing && encoded) return JSON.parse(encoded) as unknown;
  }
  if (starts.length === 0 && ends.length === 0) {
    const encoded = unwrapSingleJsonFence(output) ?? output.trim();
    return JSON.parse(encoded) as unknown;
  }
  throw new Error(`Exactly one ${startMarker} ... ${endMarker} block is required.`);
}

function planTasks(proposal: V3GroupPlanProposal): V3GroupPlanTaskInput[] {
  return proposal.tasks.map(({ recommendedSkillIds: _recommendedSkillIds, ...task }) => task);
}

export function formatV3GroupPlanProposal(proposal: V3GroupPlanProposal): string {
  return `${V3_GROUP_PLAN_PROPOSAL_START}\n${JSON.stringify(proposal, null, 2)}\n${V3_GROUP_PLAN_PROPOSAL_END}`;
}

export function parseV3GroupPlanProposal(
  output: string,
  expected: V3ExpectedGroupPlanProposal,
): V3GroupPlanProposalParseResult {
  let candidate: unknown;
  try {
    candidate = extractDelimitedJson(output, V3_GROUP_PLAN_PROPOSAL_START, V3_GROUP_PLAN_PROPOSAL_END);
  } catch (cause) {
    return {
      ok: false,
      category: 'invalid_plan_proposal',
      detail: cause instanceof Error ? cause.message : String(cause),
    };
  }
  if (!Value.Check(V3GroupPlanProposalSchema, candidate)) {
    const knownShapeIssues =
      candidate && typeof candidate === 'object' && !Array.isArray(candidate)
        ? [
            ...['scope', 'outOfScope', 'constraints', 'risks'].flatMap((field) => {
              const value = (candidate as Record<string, unknown>)[field];
              return Array.isArray(value)
                ? value.flatMap((item, index) =>
                    typeof item === 'string' ? [] : [`/${field}/${index}: must be string`],
                  )
                : [];
            }),
            ...(typeof (candidate as Record<string, unknown>).completionPolicy === 'string'
              ? []
              : ['/completionPolicy: must be string']),
          ]
        : [];
    const issues = (
      knownShapeIssues.length > 0
        ? knownShapeIssues
        : [...Value.Errors(V3GroupPlanProposalSchema, candidate)].slice(0, 8).map((issue) => {
            const path =
              'instancePath' in issue && typeof issue.instancePath === 'string' ? issue.instancePath : '/';
            return `${path || '/'}: ${issue.message}`;
          })
    ).join('; ');
    return {
      ok: false,
      category: 'invalid_plan_proposal',
      detail: `Leader output does not match the V3 group Plan proposal schema: ${issues}`,
    };
  }
  const proposal = candidate;
  if (proposal.missionId !== expected.missionId) {
    return {
      ok: false,
      category: 'invalid_plan_proposal',
      detail: `Plan missionId mismatch: expected ${expected.missionId}, received ${proposal.missionId}.`,
    };
  }

  try {
    V3GroupMissionAggregate.create({
      missionId: expected.missionId,
      goal: expected.missionGoal,
      leaderWakerId: expected.leaderWakerId,
      members: expected.members.map((member) => ({ ...member, available: true })),
    }).proposePlan(planTasks(proposal));
  } catch (cause) {
    return {
      ok: false,
      category: 'invalid_plan_proposal',
      detail: cause instanceof Error ? cause.message : String(cause),
    };
  }

  const owners = new Set(proposal.tasks.map((task) => task.ownerWakerId));
  const missingMentionOwners = expected.requiredOwnerWakerIds.filter((owner) => !owners.has(owner));
  if (missingMentionOwners.length > 0) {
    return {
      ok: false,
      category: 'invalid_plan_proposal',
      detail: `Plan does not assign a task to explicitly mentioned Wakers: ${missingMentionOwners.join(', ')}.`,
    };
  }
  return { ok: true, proposal };
}

export function buildV3GroupLeaderSystemPrompt(input: {
  missionId: string;
  leaderWakerId: string;
  members: V3GroupPromptMember[];
  requiredOwnerWakerIds: string[];
}): string {
  const roster = input.members
    .map((member) => `- ${member.name} (${member.wakerId}), role: ${member.roleName}, bio: ${member.bio}`)
    .join('\n');
  const leaderConfiguration = input.members.find(
    (member) => member.wakerId === input.leaderWakerId,
  )?.effectiveSystemPrompt;
  return `${leaderConfiguration ? `${leaderConfiguration}\n\n` : ''}You are the Leader Waker for QoderWake group mission ${input.missionId}.
Your immutable Leader identity is ${input.leaderWakerId}. Plan before execution; do not perform member tasks yourself.

Active group roster:
${roster}

Explicitly mentioned Wakers that must own at least one appropriate task: ${input.requiredOwnerWakerIds.join(', ') || 'none'}.
Create a dependency DAG using only active Waker IDs. Every task needs stable taskKey, concrete acceptanceCriteria, and real evidenceRequirements. Never invent a member, artifact, verification result, or completion claim.

Return exactly one ${V3_GROUP_PLAN_PROPOSAL_START} block whose JSON has reportType group_plan_proposal, schemaVersion 3.0.0, missionId, goal, scope, outOfScope, constraints, tasks, risks, and completionPolicy. scope, outOfScope, and constraints must be JSON arrays of strings. risks must be a JSON array of strings; do not return risk/mitigation objects. completionPolicy must be one JSON string, never an object or array. Each task must include taskKey, title, description, ownerWakerId, reviewerWakerIds, dependsOnTaskKeys, acceptanceCriteria[{key,description}], evidenceRequirements[{key,kind,description}], and recommendedSkillIds. Allowed evidence kinds are artifact, handoff_package, and verification_report.
The first output line must be the literal marker ${V3_GROUP_PLAN_PROPOSAL_START}, followed by raw JSON beginning with { on the next line. The final line must be ${V3_GROUP_PLAN_PROPOSAL_END}. Never emit Markdown code fences such as \`\`\`json and do not put planning prose outside the block.`;
}

export function buildV3GroupRoleRunSystemPrompt(input: V3GroupRoleRunPromptInput): string {
  const acceptanceKeys = input.task.acceptanceCriteria.map(({ key }) => key);
  const evidenceContract = input.task.evidenceRequirements.map(({ key, kind, description }) => ({
    requirementKey: key,
    kind,
    description,
  }));
  const reportTemplate = {
    schemaVersion: '3.0.0',
    reportType: 'role_run_completion',
    roleRunId: input.roleRunId,
    taskId: input.taskId,
    planVersion: input.planVersion,
    status: 'completed',
    summary: '<concise outcome>',
    inputSummary: '<confirmed task input>',
    roleResult: '<handoff-ready result as a string>',
    workPerformed: ['<real operation performed>'],
    changeSet: ['<workspace-relative changed path, or omit all entries when read-only>'],
    artifacts: [],
    evidence: evidenceContract.map(({ requirementKey, kind }) => ({
      requirementKey,
      acceptanceKeys,
      kind,
      artifactPath: `<real workspace-relative evidence path for ${requirementKey}>`,
      summary: '<what this persisted file proves>',
    })),
    unresolvedIssues: [],
    nextStepInput: '<what the next role or Leader needs>',
    completion: {
      acceptanceKeys,
      evidenceRequirementKeys: evidenceContract.map(({ requirementKey }) => requirementKey),
      readyForReview: true,
    },
  };
  return `${input.member.effectiveSystemPrompt ? `${input.member.effectiveSystemPrompt}\n\n` : ''}You are the ${input.member.name} Waker (${input.member.roleName}) in QoderWake mission ${input.missionId}.
Identity: ${input.member.bio}
Execute only the confirmed Plan task below. Work in the shared project root. Use read_file, glob, and grep for inspection, and sandbox_exec for shell commands, writes, builds, server starts, and verification. Do not claim files, tests, URLs, or evidence unless the corresponding operation really succeeded in the workspace.
The sandbox includes a real headless Chromium verifier at workdude-browser-verify. For any browser or UI acceptance criterion, use it through sandbox_exec, for example: workdude-browser-verify --entry index.html --selector '.cell' --screenshot evidence/browser.png --report evidence/browser.json. It performs a real page load and interaction and writes persistent screenshot/report evidence. The browser runtime is already installed; never install or download a browser package. Do not inspect, modify, replace, or bypass this verifier, and do not create a custom Playwright or Chromium harness. If it reports a failure or timeout, diagnose and fix the application code, then rerun the built-in verifier once.

Immutable execution binding:
- roleRunId must equal ${input.roleRunId}
- taskId must equal ${input.taskId}
- planVersion must equal ${input.planVersion}

Confirmed task contract:
${JSON.stringify(input.task, null, 2)}

Validated dependency handoffs:
${JSON.stringify(input.dependencyHandoffs, null, 2)}

Authoritative evidence mapping (copy every requirementKey and kind exactly; kind is never free-form):
${JSON.stringify(evidenceContract, null, 2)}
The only legal evidence kinds are artifact, handoff_package, and verification_report. Never emit aliases such as file, test, report, screenshot, browser, or document. The host also canonicalizes a known requirementKey to this authoritative kind before validation, but every other field remains strict.

Canonical final report template (replace every angle-bracket placeholder with a real value and real persisted path; do not copy placeholder text):
${JSON.stringify(reportTemplate, null, 2)}

You may stream concise progress while working. Your final assistant message must contain exactly one ${V3_ROLE_RUN_REPORT_START} block and end it with ${V3_ROLE_RUN_REPORT_END}. Put raw JSON directly between those markers; never wrap it in Markdown code fences such as \`\`\`json. The report object must contain exactly these top-level keys and no others: schemaVersion, reportType, roleRunId, taskId, planVersion, status, summary, inputSummary, roleResult, workPerformed, changeSet, artifacts, evidence, unresolvedIssues, nextStepInput, completion. Do not include taskKey or any other extra property. The JSON must use schemaVersion 3.0.0, reportType role_run_completion, and the immutable binding above. status must be completed or blocked. summary, inputSummary, roleResult, and nextStepInput must each be a string; roleResult must be a string, never an object. workPerformed, changeSet, and unresolvedIssues must be arrays of strings. artifacts must be [{path,displayName,mediaType}], evidence must be [{requirementKey,acceptanceKeys,kind,artifactPath,summary}], and completion must be {acceptanceKeys,evidenceRequirementKeys,readyForReview}. Every evidence item's acceptanceKeys must contain at least one acceptance key from the confirmed task contract; never submit an empty acceptanceKeys array. Artifact paths must be relative to the shared workspace. One evidence requirement may be supported by multiple persisted evidence files, so evidence may contain repeated requirementKey values with different artifactPath values. Delivery artifacts and verification evidence are separate: an evidence artifactPath does not have to be repeated in artifacts, but every artifact and evidence path must reference a real file that persists in the shared workspace. Every completed acceptance criterion and evidence requirement must be backed by such a file. If the workspace is not writable, an artifact is missing, or verification cannot run, report status blocked and explain why; never report completed with unresolvedIssues.`;
}
