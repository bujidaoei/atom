import { describe, expect, it } from 'vitest';

import {
  forkV3GroupMissionSnapshot,
  V3GroupMissionAggregate,
  V3GroupPlanValidationError,
  type V3GroupPlanTaskInput,
} from '../src/v3-group-orchestrator.ts';

const ids = {
  mission: '11111111-1111-4111-8111-111111111111',
  leader: '22222222-2222-4222-8222-222222222222',
  product: '33333333-3333-4333-8333-333333333333',
  frontend: '44444444-4444-4444-8444-444444444444',
};

const members = [
  { wakerId: ids.leader, name: '后端', roleName: '后端工程师', available: true },
  { wakerId: ids.product, name: '产品', roleName: '产品经理', available: true },
  { wakerId: ids.frontend, name: '前端', roleName: '前端工程师', available: true },
];

const productTask: V3GroupPlanTaskInput = {
  taskKey: 'product-design',
  title: '扫雷游戏产品设计',
  description: '产出可执行的产品方案。',
  ownerWakerId: ids.product,
  reviewerWakerIds: [ids.leader],
  dependsOnTaskKeys: [],
  acceptanceCriteria: [{ key: 'prd-complete', description: 'PRD 覆盖规则、交互和验收标准。' }],
  evidenceRequirements: [{ key: 'prd-artifact', kind: 'artifact', description: '提交真实 PRD 文件。' }],
};

const frontendTask: V3GroupPlanTaskInput = {
  taskKey: 'game-impl-and-deploy',
  title: '扫雷游戏实现与本地部署',
  description: '依据 PRD 实现并启动网页。',
  ownerWakerId: ids.frontend,
  reviewerWakerIds: [ids.leader, ids.product],
  dependsOnTaskKeys: ['product-design'],
  acceptanceCriteria: [
    { key: 'game-runs', description: '扫雷可以正常游玩。' },
    { key: 'browser-opens', description: '本地链接可直接打开。' },
  ],
  evidenceRequirements: [
    { key: 'source-files', kind: 'artifact', description: '提交游戏源码。' },
    { key: 'runtime-check', kind: 'verification_report', description: '提交运行验证。' },
  ],
};

function mission() {
  return V3GroupMissionAggregate.create({
    missionId: ids.mission,
    goal: '交付本地可运行的扫雷游戏。',
    leaderWakerId: ids.leader,
    members,
  });
}

describe('V3 group mission aggregate', () => {
  it('preserves superseded Plan attempts and confirms a versioned executable DAG', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask, frontendTask]);
    aggregate.proposePlan([productTask, { ...frontendTask, description: '第二次生成的实现方案。' }]);

    const confirmed = aggregate.confirmPlan(2, ids.leader);
    const snapshot = aggregate.snapshot();

    expect(snapshot.plans.map(({ version, state }) => ({ version, state }))).toEqual([
      { version: 1, state: 'superseded' },
      { version: 2, state: 'confirmed' },
    ]);
    expect(confirmed.roleRuns).toHaveLength(2);
    expect(aggregate.runnableRoleRuns().map((run) => run.taskKey)).toEqual(['product-design']);
    expect(snapshot.roleRuns.find((run) => run.taskKey === 'game-impl-and-deploy')).toMatchObject({
      state: 'waiting_dependencies',
      attemptCount: 0,
    });
  });

  it('rejects cycles, unknown dependencies, and assignments outside active membership', () => {
    expect(() =>
      mission().proposePlan([{ ...productTask, dependsOnTaskKeys: ['game-impl-and-deploy'] }, frontendTask]),
    ).toThrow(V3GroupPlanValidationError);
    expect(() => mission().proposePlan([{ ...productTask, dependsOnTaskKeys: ['missing-task'] }])).toThrow(
      'unknown dependency',
    );
    expect(() =>
      mission().proposePlan([
        {
          ...productTask,
          ownerWakerId: '55555555-5555-4555-8555-555555555555',
        },
      ]),
    ).toThrow('active group member');
  });

  it('unlocks dependencies only after validated completion evidence', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask, frontendTask]);
    const { roleRuns } = aggregate.confirmPlan(1, ids.leader);
    const productRun = roleRuns.find((run) => run.taskKey === 'product-design')!;

    aggregate.startRoleRun(productRun.id);
    aggregate.completeRoleRun(productRun.id, {
      acceptanceKeys: ['prd-complete'],
      evidence: [{ requirementKey: 'prd-artifact', artifactPath: 'PRD-minesweeper.md' }],
    });

    expect(aggregate.runnableRoleRuns().map((run) => run.taskKey)).toEqual(['game-impl-and-deploy']);
  });

  it('retries the same logical RoleRun after invalid_structured_report and survives hydration', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask]);
    const roleRun = aggregate.confirmPlan(1, ids.leader).roleRuns[0]!;
    aggregate.startRoleRun(roleRun.id);
    aggregate.failRoleRun(roleRun.id, {
      category: 'invalid_structured_report',
      detail: 'RoleRun report roleRunId mismatch',
      retryable: true,
      maxAttempts: 2,
    });

    const restored = V3GroupMissionAggregate.hydrate(aggregate.snapshot());
    const retried = restored.runnableRoleRuns()[0]!;

    expect(retried.id).toBe(roleRun.id);
    expect(retried.attemptCount).toBe(1);
    restored.startRoleRun(retried.id);
    expect(restored.snapshot().roleRuns[0]).toMatchObject({
      id: roleRun.id,
      attemptCount: 2,
      state: 'running',
    });
  });

  it('recovers an interrupted active attempt as a retry on the same RoleRun', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask]);
    const roleRun = aggregate.confirmPlan(1, ids.leader).roleRuns[0]!;
    aggregate.startRoleRun(roleRun.id);
    const command = aggregate.createExecutorCommand(roleRun.id, '2026-08-14T04:00:00.000Z');
    aggregate.leaseExecutorCommand(command.id, 'worker-1', '2026-08-14T03:01:00.000Z');
    aggregate.dispatchExecutorCommand(command.id);
    aggregate.acknowledgeExecutorCommand(command.id);

    const recovered = V3GroupMissionAggregate.hydrate(aggregate.snapshot());
    const decisions = recovered.recoverInterruptedRoleRuns(2);

    expect(decisions).toEqual([{ roleRunId: roleRun.id, interruptedAttempt: 1, retryQueued: true }]);
    expect(recovered.runnableRoleRuns()[0]).toMatchObject({
      id: roleRun.id,
      attemptCount: 1,
      state: 'queued',
    });
    expect(recovered.snapshot().commands[0]).toMatchObject({
      id: command.id,
      state: 'failed',
      failureCategory: 'interrupted',
    });
  });

  it('enforces the durable ExecutorCommand lease and acknowledgement lifecycle', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask]);
    const roleRun = aggregate.confirmPlan(1, ids.leader).roleRuns[0]!;
    aggregate.startRoleRun(roleRun.id);
    const command = aggregate.createExecutorCommand(roleRun.id, '2026-08-14T04:00:00.000Z');

    expect(() => aggregate.acknowledgeExecutorCommand(command.id)).toThrow(
      'ExecutorCommand must be dispatched',
    );
    aggregate.leaseExecutorCommand(command.id, 'worker-1', '2026-08-14T03:01:00.000Z');
    aggregate.dispatchExecutorCommand(command.id);
    aggregate.acknowledgeExecutorCommand(command.id);
    aggregate.refreshExecutorCommandLease(command.id, 'worker-1', '2026-08-14T03:02:00.000Z');
    const completed = aggregate.completeExecutorCommand(command.id);

    expect(completed).toMatchObject({
      roleRunId: roleRun.id,
      attempt: 1,
      state: 'completed',
      leaseOwnerId: 'worker-1',
      leaseExpiresAt: null,
    });
  });

  it('creates a follow-up Plan version that carries completed identities and evidence forward', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask]);
    const roleRun = aggregate.confirmPlan(1, ids.leader).roleRuns[0]!;
    aggregate.startRoleRun(roleRun.id);
    aggregate.completeRoleRun(roleRun.id, {
      acceptanceKeys: ['prd-complete'],
      evidence: [{ requirementKey: 'prd-artifact', artifactPath: 'PRD-minesweeper.md' }],
    });

    const followup = aggregate.proposeFollowupPlan([
      productTask,
      {
        ...frontendTask,
        taskKey: 'bugfix-user-reported-errors',
        dependsOnTaskKeys: ['product-design'],
      },
    ]);
    const carried = followup.tasks.find((task) => task.taskKey === 'product-design')!;

    expect(followup.version).toBe(2);
    expect(carried.resumeDecision).toBe('carry_forward_completed');
    expect(carried.carriedEvidence).toEqual([
      { requirementKey: 'prd-artifact', artifactPath: 'PRD-minesweeper.md' },
    ]);
  });

  it('rejects a follow-up Plan that drops or rewrites a prior accepted task contract', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask]);
    const roleRun = aggregate.confirmPlan(1, ids.leader).roleRuns[0]!;
    aggregate.startRoleRun(roleRun.id);
    aggregate.completeRoleRun(roleRun.id, {
      acceptanceKeys: ['prd-complete'],
      evidence: [{ requirementKey: 'prd-artifact', artifactPath: 'PRD-minesweeper.md' }],
    });

    expect(() => aggregate.proposeFollowupPlan([frontendTask])).toThrow(
      'Follow-up Plan must retain prior task contract: product-design.',
    );
    expect(() =>
      aggregate.proposeFollowupPlan([
        {
          ...productTask,
          acceptanceCriteria: [{ key: 'prd-complete', description: '偷偷改写验收口径。' }],
        },
        frontendTask,
      ]),
    ).toThrow('Follow-up Plan cannot change owner, acceptance, or evidence for prior task: product-design.');
  });

  it('forks completed mission history with independent storage identities and intact RoleRun references', () => {
    const aggregate = mission();
    aggregate.proposePlan([productTask]);
    const roleRun = aggregate.confirmPlan(1, ids.leader).roleRuns[0]!;
    aggregate.startRoleRun(roleRun.id);
    aggregate.completeRoleRun(roleRun.id, {
      acceptanceKeys: ['prd-complete'],
      evidence: [{ requirementKey: 'prd-artifact', artifactPath: 'PRD-minesweeper.md' }],
    });
    const source = aggregate.snapshot();
    const forked = forkV3GroupMissionSnapshot(
      source,
      '55555555-5555-4555-8555-555555555555',
      '用户反馈报错，请验证并修复。',
    );

    expect(forked.missionId).not.toBe(source.missionId);
    expect(forked.goal).toBe('用户反馈报错，请验证并修复。');
    expect(forked.plans[0]?.id).not.toBe(source.plans[0]?.id);
    expect(forked.plans[0]?.tasks[0]?.id).not.toBe(source.plans[0]?.tasks[0]?.id);
    expect(forked.roleRuns[0]?.id).not.toBe(source.roleRuns[0]?.id);
    expect(forked.roleRuns[0]?.taskId).toBe(forked.plans[0]?.tasks[0]?.id);
    expect(forked.roleRuns[0]?.evidence).toEqual(source.roleRuns[0]?.evidence);
  });
});
