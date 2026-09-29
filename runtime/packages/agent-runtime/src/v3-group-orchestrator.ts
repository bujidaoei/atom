import { randomUUID } from 'node:crypto';

import {
  redactRunFailureCategory,
  redactRunFailureDetail,
} from '../../product-contracts/src/provider-correlation.ts';
import type {
  V3GroupAcceptanceCriterion,
  V3GroupEvidenceRequirement,
} from '../../product-contracts/src/v3.ts';

export interface V3GroupMissionMember {
  wakerId: string;
  name: string;
  roleName: string;
  available: boolean;
}

export interface V3GroupPlanTaskInput {
  taskKey: string;
  title: string;
  description: string;
  ownerWakerId: string;
  reviewerWakerIds: string[];
  dependsOnTaskKeys: string[];
  acceptanceCriteria: V3GroupAcceptanceCriterion[];
  evidenceRequirements: V3GroupEvidenceRequirement[];
}

export interface V3CarriedEvidence {
  requirementKey: string;
  artifactPath: string;
}

export interface V3GroupPlanTask extends V3GroupPlanTaskInput {
  id: string;
  planVersion: number;
  position: number;
  resumeDecision: 'execute' | 'carry_forward_completed';
  carriedEvidence: V3CarriedEvidence[];
}

export interface V3GroupPlan {
  id: string;
  version: number;
  state: 'proposed' | 'superseded' | 'confirmed' | 'completed';
  goal?: string;
  scope?: string[];
  outOfScope?: string[];
  constraints?: string[];
  risks?: string[];
  completionPolicy?: string;
  tasks: V3GroupPlanTask[];
}

export interface V3GroupPlanDetails {
  goal: string;
  scope: string[];
  outOfScope: string[];
  constraints: string[];
  risks: string[];
  completionPolicy: string;
}

export interface V3RoleRunAttempt {
  number: number;
  state: 'running' | 'completed' | 'failed';
  failureCategory: string | null;
  failureDetail: string | null;
}

export interface V3GroupRoleRun {
  id: string;
  taskId: string;
  taskKey: string;
  planVersion: number;
  ownerWakerId: string;
  state: 'waiting_dependencies' | 'queued' | 'running' | 'completed' | 'failed';
  attemptCount: number;
  attempts: V3RoleRunAttempt[];
  acceptanceKeys: string[];
  evidence: V3CarriedEvidence[];
}

export interface V3ExecutorCommand {
  id: string;
  roleRunId: string;
  attempt: number;
  state: 'created' | 'leased' | 'dispatched' | 'acknowledged' | 'completed' | 'failed';
  leaseOwnerId: string | null;
  leaseExpiresAt: string | null;
  hardDeadlineAt: string;
  failureCategory: string | null;
  failureDetail: string | null;
}

export interface V3GroupMissionSnapshot {
  missionId: string;
  goal: string;
  leaderWakerId: string;
  members: V3GroupMissionMember[];
  plans: V3GroupPlan[];
  roleRuns: V3GroupRoleRun[];
  commands: V3ExecutorCommand[];
}

export function redactV3GroupMissionFailureDetails(snapshot: V3GroupMissionSnapshot): V3GroupMissionSnapshot {
  const redacted = structuredClone(snapshot);
  for (const roleRun of redacted.roleRuns) {
    for (const attempt of roleRun.attempts) {
      if (attempt.failureCategory !== null) {
        attempt.failureCategory = redactRunFailureCategory(attempt.failureCategory);
      }
      if (attempt.failureDetail !== null) {
        attempt.failureDetail = redactRunFailureDetail(attempt.failureDetail);
      }
    }
  }
  for (const command of redacted.commands) {
    if (command.failureCategory !== null) {
      command.failureCategory = redactRunFailureCategory(command.failureCategory);
    }
    if (command.failureDetail !== null) {
      command.failureDetail = redactRunFailureDetail(command.failureDetail);
    }
  }
  return redacted;
}

export interface V3GroupPlanConfirmationResult {
  created: boolean;
  planVersion: number;
  roleRunIds: string[];
  snapshot: V3GroupMissionSnapshot;
}

export interface V3CreateGroupMissionInput {
  missionId: string;
  goal: string;
  leaderWakerId: string;
  members: V3GroupMissionMember[];
}

export interface V3CompleteRoleRunInput {
  acceptanceKeys: string[];
  evidence: V3CarriedEvidence[];
}

export interface V3FailRoleRunInput {
  category: string;
  detail: string;
  retryable: boolean;
  maxAttempts: number;
}

export class V3GroupPlanValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'V3GroupPlanValidationError';
  }
}

function unique(values: readonly string[], label: string): void {
  const seen = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) throw new V3GroupPlanValidationError(`${label} must be unique: ${value}.`);
    seen.add(value);
  }
}

function sameContractItems<T extends { key: string }>(left: readonly T[], right: readonly T[]): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function sameTaskContract(previous: V3GroupPlanTask, next: V3GroupPlanTaskInput): boolean {
  return (
    previous.ownerWakerId === next.ownerWakerId &&
    sameContractItems(previous.acceptanceCriteria, next.acceptanceCriteria) &&
    sameContractItems(previous.evidenceRequirements, next.evidenceRequirements)
  );
}

export function forkV3GroupMissionSnapshot(
  source: V3GroupMissionSnapshot,
  missionId: string,
  goal: string,
): V3GroupMissionSnapshot {
  const taskIds = new Map<string, string>();
  const plans = source.plans.map((plan) => ({
    ...structuredClone(plan),
    id: randomUUID(),
    tasks: plan.tasks.map((task) => {
      const id = randomUUID();
      taskIds.set(`${task.planVersion}:${task.id}`, id);
      return { ...structuredClone(task), id };
    }),
  }));
  const roleRuns = source.roleRuns.map((roleRun) => {
    const taskId = taskIds.get(`${roleRun.planVersion}:${roleRun.taskId}`);
    if (!taskId) throw new Error(`Cannot fork RoleRun with unknown Plan task: ${roleRun.id}.`);
    return { ...structuredClone(roleRun), id: randomUUID(), taskId };
  });
  return {
    missionId,
    goal,
    leaderWakerId: source.leaderWakerId,
    members: structuredClone(source.members),
    plans,
    roleRuns,
    commands: source.commands.map((command) => {
      const sourceRoleRun = source.roleRuns.find((roleRun) => roleRun.id === command.roleRunId);
      const targetRoleRun = sourceRoleRun ? roleRuns[source.roleRuns.indexOf(sourceRoleRun)] : undefined;
      if (!targetRoleRun) throw new Error(`Cannot fork command with unknown RoleRun: ${command.id}.`);
      return { ...structuredClone(command), id: randomUUID(), roleRunId: targetRoleRun.id };
    }),
  };
}

function assertExactKeys(actual: readonly string[], expected: readonly string[], label: string): void {
  unique(actual, label);
  assertCoveredKeys(actual, expected, label);
}

function assertCoveredKeys(actual: readonly string[], expected: readonly string[], label: string): void {
  const actualSet = new Set(actual);
  const expectedSet = new Set(expected);
  const missing = expected.filter((key) => !actualSet.has(key));
  const extra = actual.filter((key) => !expectedSet.has(key));
  if (missing.length > 0 || extra.length > 0) {
    throw new Error(
      `${label} do not match the confirmed Plan; missing: ${missing.join(', ') || 'none'}; unknown: ${extra.join(', ') || 'none'}.`,
    );
  }
}

export class V3GroupMissionAggregate {
  private constructor(private readonly state: V3GroupMissionSnapshot) {}

  static create(input: V3CreateGroupMissionInput): V3GroupMissionAggregate {
    if (!input.goal.trim()) throw new Error('Mission goal is required.');
    unique(
      input.members.map((member) => member.wakerId),
      'Group member identities',
    );
    const leader = input.members.find((member) => member.wakerId === input.leaderWakerId);
    if (!leader?.available) throw new Error('The group Leader must be an active group member.');
    return new V3GroupMissionAggregate({
      ...structuredClone(input),
      plans: [],
      roleRuns: [],
      commands: [],
    });
  }

  static hydrate(snapshot: V3GroupMissionSnapshot): V3GroupMissionAggregate {
    return new V3GroupMissionAggregate(redactV3GroupMissionFailureDetails(snapshot));
  }

  snapshot(): V3GroupMissionSnapshot {
    return structuredClone(this.state);
  }

  proposePlan(tasks: V3GroupPlanTaskInput[], details?: V3GroupPlanDetails): V3GroupPlan {
    this.validatePlan(tasks);
    for (const plan of this.state.plans) {
      if (plan.state === 'proposed') plan.state = 'superseded';
    }
    const version = (this.state.plans.at(-1)?.version ?? 0) + 1;
    const plan: V3GroupPlan = {
      id: randomUUID(),
      version,
      state: 'proposed',
      ...(details ? structuredClone(details) : {}),
      tasks: tasks.map((task, position) => ({
        ...structuredClone(task),
        id: randomUUID(),
        planVersion: version,
        position,
        resumeDecision: 'execute',
        carriedEvidence: [],
      })),
    };
    this.state.plans.push(plan);
    return structuredClone(plan);
  }

  proposeFollowupPlan(tasks: V3GroupPlanTaskInput[], details?: V3GroupPlanDetails): V3GroupPlan {
    const previous = [...this.state.plans]
      .reverse()
      .find((plan) => plan.state === 'confirmed' || plan.state === 'completed');
    if (!previous) throw new Error('A follow-up Plan requires a previously confirmed Plan.');
    for (const priorTask of previous.tasks) {
      const nextTask = tasks.find((candidate) => candidate.taskKey === priorTask.taskKey);
      if (!nextTask) {
        throw new V3GroupPlanValidationError(
          `Follow-up Plan must retain prior task contract: ${priorTask.taskKey}.`,
        );
      }
      if (!sameTaskContract(priorTask, nextTask)) {
        throw new V3GroupPlanValidationError(
          `Follow-up Plan cannot change owner, acceptance, or evidence for prior task: ${priorTask.taskKey}.`,
        );
      }
    }
    this.validatePlan(tasks);

    const version = (this.state.plans.at(-1)?.version ?? 0) + 1;
    const plan: V3GroupPlan = {
      id: randomUUID(),
      version,
      state: 'proposed',
      ...(details ? structuredClone(details) : {}),
      tasks: tasks.map((task, position) => {
        const priorTask = previous.tasks.find((candidate) => candidate.taskKey === task.taskKey);
        const priorRun = priorTask
          ? this.state.roleRuns.find(
              (candidate) => candidate.taskId === priorTask.id && candidate.state === 'completed',
            )
          : undefined;
        const carry = Boolean(priorTask && priorRun && sameTaskContract(priorTask, task));
        return {
          ...structuredClone(task),
          id: randomUUID(),
          planVersion: version,
          position,
          resumeDecision: carry ? 'carry_forward_completed' : 'execute',
          carriedEvidence: carry ? structuredClone(priorRun!.evidence) : [],
        };
      }),
    };
    this.state.plans.push(plan);
    return structuredClone(plan);
  }

  confirmPlan(version: number, actorWakerId: string): { plan: V3GroupPlan; roleRuns: V3GroupRoleRun[] } {
    if (actorWakerId !== this.state.leaderWakerId) {
      throw new Error('Only the group Leader can confirm a Plan.');
    }
    const plan = this.state.plans.find((candidate) => candidate.version === version);
    if (!plan || plan.state !== 'proposed') throw new Error('Only a proposed Plan can be confirmed.');
    if (this.state.plans.at(-1)?.id !== plan.id) throw new Error('Only the latest Plan can be confirmed.');

    plan.state = 'confirmed';
    const roleRuns = plan.tasks
      .filter((task) => task.resumeDecision === 'execute')
      .map<V3GroupRoleRun>((task) => ({
        id: randomUUID(),
        taskId: task.id,
        taskKey: task.taskKey,
        planVersion: plan.version,
        ownerWakerId: task.ownerWakerId,
        state: task.dependsOnTaskKeys.length === 0 ? 'queued' : 'waiting_dependencies',
        attemptCount: 0,
        attempts: [],
        acceptanceKeys: [],
        evidence: [],
      }));
    this.state.roleRuns.push(...roleRuns);
    this.refreshReadiness(plan);
    if (roleRuns.length === 0) plan.state = 'completed';
    return { plan: structuredClone(plan), roleRuns: structuredClone(roleRuns) };
  }

  runnableRoleRuns(): V3GroupRoleRun[] {
    const plan = [...this.state.plans].reverse().find((candidate) => candidate.state === 'confirmed');
    if (!plan) return [];
    this.refreshReadiness(plan);
    return structuredClone(
      this.state.roleRuns.filter(
        (roleRun) => roleRun.planVersion === plan.version && roleRun.state === 'queued',
      ),
    );
  }

  startRoleRun(roleRunId: string): V3GroupRoleRun {
    const roleRun = this.requireRoleRun(roleRunId);
    if (roleRun.state !== 'queued') throw new Error('Only a queued RoleRun can start.');
    roleRun.attemptCount += 1;
    roleRun.state = 'running';
    roleRun.attempts.push({
      number: roleRun.attemptCount,
      state: 'running',
      failureCategory: null,
      failureDetail: null,
    });
    return structuredClone(roleRun);
  }

  completeRoleRun(roleRunId: string, input: V3CompleteRoleRunInput): V3GroupRoleRun {
    const roleRun = this.requireRunningRoleRun(roleRunId);
    const task = this.requireTask(roleRun);
    assertExactKeys(
      input.acceptanceKeys,
      task.acceptanceCriteria.map((criterion) => criterion.key),
      'Acceptance keys',
    );
    assertCoveredKeys(
      input.evidence.map((evidence) => evidence.requirementKey),
      task.evidenceRequirements.map((requirement) => requirement.key),
      'Evidence requirement keys',
    );
    roleRun.state = 'completed';
    roleRun.acceptanceKeys = [...input.acceptanceKeys];
    roleRun.evidence = structuredClone(input.evidence);
    const attempt = roleRun.attempts.at(-1)!;
    attempt.state = 'completed';
    this.refreshReadiness(this.requirePlan(roleRun.planVersion));
    this.completePlanWhenDone(roleRun.planVersion);
    return structuredClone(roleRun);
  }

  failRoleRun(roleRunId: string, input: V3FailRoleRunInput): V3GroupRoleRun {
    const roleRun = this.requireRunningRoleRun(roleRunId);
    const attempt = roleRun.attempts.at(-1)!;
    attempt.state = 'failed';
    attempt.failureCategory = redactRunFailureCategory(input.category);
    attempt.failureDetail = redactRunFailureDetail(input.detail);
    roleRun.state = input.retryable && roleRun.attemptCount < input.maxAttempts ? 'queued' : 'failed';
    return structuredClone(roleRun);
  }

  createExecutorCommand(roleRunId: string, hardDeadlineAt: string): V3ExecutorCommand {
    const roleRun = this.requireRunningRoleRun(roleRunId);
    if (!Number.isFinite(Date.parse(hardDeadlineAt))) throw new Error('Command hard deadline is invalid.');
    if (
      this.state.commands.some(
        (command) => command.roleRunId === roleRunId && command.attempt === roleRun.attemptCount,
      )
    ) {
      throw new Error('A RoleRun attempt can have only one ExecutorCommand.');
    }
    const command: V3ExecutorCommand = {
      id: randomUUID(),
      roleRunId,
      attempt: roleRun.attemptCount,
      state: 'created',
      leaseOwnerId: null,
      leaseExpiresAt: null,
      hardDeadlineAt,
      failureCategory: null,
      failureDetail: null,
    };
    this.state.commands.push(command);
    return structuredClone(command);
  }

  leaseExecutorCommand(commandId: string, leaseOwnerId: string, leaseExpiresAt: string): V3ExecutorCommand {
    const command = this.requireCommand(commandId, 'created');
    if (!leaseOwnerId.trim() || !Number.isFinite(Date.parse(leaseExpiresAt))) {
      throw new Error('ExecutorCommand lease is invalid.');
    }
    command.state = 'leased';
    command.leaseOwnerId = leaseOwnerId;
    command.leaseExpiresAt = leaseExpiresAt;
    return structuredClone(command);
  }

  dispatchExecutorCommand(commandId: string): V3ExecutorCommand {
    const command = this.requireCommand(commandId, 'leased');
    command.state = 'dispatched';
    return structuredClone(command);
  }

  acknowledgeExecutorCommand(commandId: string): V3ExecutorCommand {
    const command = this.requireCommand(commandId, 'dispatched');
    command.state = 'acknowledged';
    return structuredClone(command);
  }

  refreshExecutorCommandLease(
    commandId: string,
    leaseOwnerId: string,
    leaseExpiresAt: string,
  ): V3ExecutorCommand {
    const command = this.requireCommand(commandId, 'acknowledged');
    if (command.leaseOwnerId !== leaseOwnerId) throw new Error('ExecutorCommand lease owner mismatch.');
    if (!Number.isFinite(Date.parse(leaseExpiresAt)))
      throw new Error('ExecutorCommand lease expiry is invalid.');
    command.leaseExpiresAt = leaseExpiresAt;
    return structuredClone(command);
  }

  completeExecutorCommand(commandId: string): V3ExecutorCommand {
    const command = this.requireCommand(commandId, 'acknowledged');
    command.state = 'completed';
    command.leaseExpiresAt = null;
    return structuredClone(command);
  }

  failExecutorCommand(commandId: string, category: string, detail: string): V3ExecutorCommand {
    const command = this.state.commands.find((candidate) => candidate.id === commandId);
    if (!command || command.state === 'completed' || command.state === 'failed') {
      throw new Error('Only an active ExecutorCommand can fail.');
    }
    command.state = 'failed';
    command.leaseExpiresAt = null;
    command.failureCategory = redactRunFailureCategory(category);
    command.failureDetail = redactRunFailureDetail(detail);
    return structuredClone(command);
  }

  recoverInterruptedRoleRuns(
    maxAttempts: number,
  ): Array<{ roleRunId: string; interruptedAttempt: number; retryQueued: boolean }> {
    const recovered: Array<{
      roleRunId: string;
      interruptedAttempt: number;
      retryQueued: boolean;
    }> = [];
    for (const roleRun of this.state.roleRuns) {
      if (roleRun.state !== 'running') continue;
      const attempt = roleRun.attempts.at(-1);
      if (!attempt || attempt.state !== 'running') {
        throw new Error(`Running RoleRun has no running attempt: ${roleRun.id}.`);
      }
      attempt.state = 'failed';
      attempt.failureCategory = 'interrupted';
      attempt.failureDetail = 'Agent host restarted before the RoleRun completed.';
      const retryQueued = roleRun.attemptCount < maxAttempts;
      roleRun.state = retryQueued ? 'queued' : 'failed';
      const command = this.state.commands.find(
        (candidate) =>
          candidate.roleRunId === roleRun.id &&
          candidate.attempt === attempt.number &&
          !['completed', 'failed'].includes(candidate.state),
      );
      if (command) {
        command.state = 'failed';
        command.leaseExpiresAt = null;
        command.failureCategory = 'interrupted';
        command.failureDetail = 'Agent host restarted before the ExecutorCommand completed.';
      }
      recovered.push({
        roleRunId: roleRun.id,
        interruptedAttempt: attempt.number,
        retryQueued,
      });
    }
    return recovered;
  }

  private validatePlan(tasks: V3GroupPlanTaskInput[]): void {
    if (tasks.length === 0) throw new V3GroupPlanValidationError('A Plan requires at least one task.');
    unique(
      tasks.map((task) => task.taskKey),
      'Plan task keys',
    );
    const activeMembers = new Set(
      this.state.members.filter((member) => member.available).map((member) => member.wakerId),
    );
    const taskKeys = new Set(tasks.map((task) => task.taskKey));
    for (const task of tasks) {
      if (!task.taskKey.trim() || !task.title.trim() || !task.description.trim()) {
        throw new V3GroupPlanValidationError('Every Plan task requires a key, title, and description.');
      }
      if (!activeMembers.has(task.ownerWakerId)) {
        throw new V3GroupPlanValidationError(`Task ${task.taskKey} owner must be an active group member.`);
      }
      for (const reviewer of task.reviewerWakerIds) {
        if (!activeMembers.has(reviewer)) {
          throw new V3GroupPlanValidationError(
            `Task ${task.taskKey} reviewer must be an active group member.`,
          );
        }
      }
      unique(task.reviewerWakerIds, `Task ${task.taskKey} reviewer identities`);
      unique(task.dependsOnTaskKeys, `Task ${task.taskKey} dependencies`);
      unique(
        task.acceptanceCriteria.map((criterion) => criterion.key),
        `Task ${task.taskKey} acceptance keys`,
      );
      unique(
        task.evidenceRequirements.map((requirement) => requirement.key),
        `Task ${task.taskKey} evidence keys`,
      );
      for (const dependency of task.dependsOnTaskKeys) {
        if (!taskKeys.has(dependency)) {
          throw new V3GroupPlanValidationError(`Task ${task.taskKey} has unknown dependency ${dependency}.`);
        }
        if (dependency === task.taskKey) {
          throw new V3GroupPlanValidationError(`Task ${task.taskKey} cannot depend on itself.`);
        }
      }
    }

    const byKey = new Map(tasks.map((task) => [task.taskKey, task]));
    const visiting = new Set<string>();
    const visited = new Set<string>();
    const visit = (taskKey: string): void => {
      if (visiting.has(taskKey)) {
        throw new V3GroupPlanValidationError(`Plan dependency graph contains a cycle at ${taskKey}.`);
      }
      if (visited.has(taskKey)) return;
      visiting.add(taskKey);
      for (const dependency of byKey.get(taskKey)!.dependsOnTaskKeys) visit(dependency);
      visiting.delete(taskKey);
      visited.add(taskKey);
    };
    for (const task of tasks) visit(task.taskKey);
  }

  private requirePlan(version: number): V3GroupPlan {
    const plan = this.state.plans.find((candidate) => candidate.version === version);
    if (!plan) throw new Error(`Plan version not found: ${version}.`);
    return plan;
  }

  private requireRoleRun(roleRunId: string): V3GroupRoleRun {
    const roleRun = this.state.roleRuns.find((candidate) => candidate.id === roleRunId);
    if (!roleRun) throw new Error(`RoleRun not found: ${roleRunId}.`);
    return roleRun;
  }

  private requireRunningRoleRun(roleRunId: string): V3GroupRoleRun {
    const roleRun = this.requireRoleRun(roleRunId);
    if (roleRun.state !== 'running') throw new Error('Only a running RoleRun can finish.');
    return roleRun;
  }

  private requireCommand(commandId: string, state: V3ExecutorCommand['state']): V3ExecutorCommand {
    const command = this.state.commands.find((candidate) => candidate.id === commandId);
    if (!command) throw new Error(`ExecutorCommand not found: ${commandId}.`);
    if (command.state !== state) {
      throw new Error(`ExecutorCommand must be ${state}; current state is ${command.state}.`);
    }
    return command;
  }

  private requireTask(roleRun: V3GroupRoleRun): V3GroupPlanTask {
    const task = this.requirePlan(roleRun.planVersion).tasks.find(
      (candidate) => candidate.id === roleRun.taskId,
    );
    if (!task) throw new Error(`Plan task not found: ${roleRun.taskId}.`);
    return task;
  }

  private taskCompleted(plan: V3GroupPlan, taskKey: string): boolean {
    const task = plan.tasks.find((candidate) => candidate.taskKey === taskKey);
    if (!task) return false;
    if (task.resumeDecision === 'carry_forward_completed') return true;
    return this.state.roleRuns.some((roleRun) => roleRun.taskId === task.id && roleRun.state === 'completed');
  }

  private refreshReadiness(plan: V3GroupPlan): void {
    for (const roleRun of this.state.roleRuns) {
      if (roleRun.planVersion !== plan.version || roleRun.state !== 'waiting_dependencies') continue;
      const task = this.requireTask(roleRun);
      if (task.dependsOnTaskKeys.every((key) => this.taskCompleted(plan, key))) {
        roleRun.state = 'queued';
      }
    }
  }

  private completePlanWhenDone(version: number): void {
    const plan = this.requirePlan(version);
    if (plan.tasks.every((task) => this.taskCompleted(plan, task.taskKey))) plan.state = 'completed';
  }
}

export function confirmV3GroupMissionPlan(
  snapshot: V3GroupMissionSnapshot,
  planVersion: number,
  actorWakerId: string,
): V3GroupPlanConfirmationResult {
  if (actorWakerId !== snapshot.leaderWakerId) {
    throw new Error('Only the group Leader can confirm a Plan.');
  }
  const latest = snapshot.plans.at(-1);
  if (!latest || latest.version !== planVersion) {
    throw new Error('Only the latest Plan can be confirmed.');
  }
  if (latest.state === 'confirmed' || latest.state === 'completed') {
    return {
      created: false,
      planVersion,
      roleRunIds: snapshot.roleRuns
        .filter((roleRun) => roleRun.planVersion === planVersion)
        .map((roleRun) => roleRun.id),
      snapshot: structuredClone(snapshot),
    };
  }
  const aggregate = V3GroupMissionAggregate.hydrate(snapshot);
  const confirmed = aggregate.confirmPlan(planVersion, actorWakerId);
  return {
    created: true,
    planVersion,
    roleRunIds: confirmed.roleRuns.map((roleRun) => roleRun.id),
    snapshot: aggregate.snapshot(),
  };
}
