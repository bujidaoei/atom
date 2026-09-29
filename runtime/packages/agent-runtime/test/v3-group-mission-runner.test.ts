import { link, mkdir, mkdtemp, readFile, rm, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { formatV3GroupPlanProposal, type V3GroupPlanProposal } from '../src/v3-group-prompts.ts';
import {
  V3GroupMissionRunner,
  readV3SharedWorkspaceFile,
  type V3GroupMissionStore,
  type V3GroupMissionStoreRecord,
} from '../src/v3-group-mission-runner.ts';
import { V3GroupMissionAggregate } from '../src/v3-group-orchestrator.ts';
import { formatV3RoleRunReport } from '../src/v3-role-run-report.ts';

const roots: string[] = [];
const ids = {
  mission: '11111111-1111-4111-8111-111111111111',
  leader: '22222222-2222-4222-8222-222222222222',
  product: '33333333-3333-4333-8333-333333333333',
  frontend: '44444444-4444-4444-8444-444444444444',
};

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

function confirmPlan(record: V3GroupMissionStoreRecord, planVersion: number, events: string[]): void {
  const aggregate = V3GroupMissionAggregate.hydrate(record.snapshot);
  aggregate.confirmPlan(planVersion, record.snapshot.leaderWakerId);
  record.snapshot = aggregate.snapshot();
  events.push('plan.confirmed');
}

describe('V3 PI-backed group mission runner', () => {
  it('uses descriptor-bound plain-file reads for RoleRun artifact validation', async () => {
    const source = await readFile(new URL('../src/v3-group-mission-runner.ts', import.meta.url), 'utf8');
    expect(source).toContain('readV3SharedWorkspaceFile');
    expect(source).toContain('lstat(');
    expect(source).toContain('handle.read(');
    expect(source).not.toContain("readFile(resolve(root, item.artifactPath), 'utf8')");
  });

  it('reads workspace artifacts from one stable descriptor and rejects links or escapes', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-group-artifact-read-'));
    roots.push(root);
    const workspaceRoot = join(root, 'workspace');
    const outside = join(root, 'outside.txt');
    const artifact = join(workspaceRoot, 'artifact.txt');
    const alias = join(workspaceRoot, 'alias.txt');
    await mkdir(workspaceRoot, { recursive: true });
    await writeFile(outside, 'outside');
    await writeFile(artifact, 'trusted artifact');

    await expect(readV3SharedWorkspaceFile(workspaceRoot, '../outside.txt')).rejects.toThrow(/escapes/u);
    await link(artifact, alias);
    await expect(readV3SharedWorkspaceFile(workspaceRoot, 'alias.txt')).rejects.toThrow(/plain file/u);
    await unlink(alias);
    await expect(readV3SharedWorkspaceFile(workspaceRoot, 'artifact.txt')).resolves.toEqual(
      Buffer.from('trusted artifact'),
    );
  });

  it('persists a proposed Plan and remains idle across recovery until the Leader confirms it', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-group-plan-confirmation-'));
    roots.push(root);
    const workspaceRoot = join(root, 'workspace');
    await mkdir(workspaceRoot, { recursive: true });
    const record: V3GroupMissionStoreRecord = {
      id: ids.mission,
      prompt: '请先制定计划，等待确认后再创建文件。',
      mentionedWakerIds: [ids.product],
      workspaceRoot,
      profiles: [
        {
          wakerId: ids.leader,
          name: '后端',
          roleName: '后端工程师',
          bio: '统筹交付。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
        {
          wakerId: ids.product,
          name: '产品',
          roleName: '产品经理',
          bio: '负责产品设计。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
      ],
      snapshot: V3GroupMissionAggregate.create({
        missionId: ids.mission,
        goal: '等待确认后创建文件。',
        leaderWakerId: ids.leader,
        members: [
          { wakerId: ids.leader, name: '后端', roleName: '后端工程师', available: true },
          { wakerId: ids.product, name: '产品', roleName: '产品经理', available: true },
        ],
      }).snapshot(),
    };
    const proposal: V3GroupPlanProposal = {
      schemaVersion: '3.0.0',
      reportType: 'group_plan_proposal',
      missionId: ids.mission,
      goal: record.snapshot.goal,
      scope: ['创建文件'],
      outOfScope: [],
      constraints: ['必须等待人工确认'],
      tasks: [
        {
          taskKey: 'create-file',
          title: '创建文件',
          description: '在共享工作区创建文件。',
          ownerWakerId: ids.product,
          reviewerWakerIds: [ids.leader],
          dependsOnTaskKeys: [],
          acceptanceCriteria: [{ key: 'file-created', description: '文件存在。' }],
          evidenceRequirements: [{ key: 'file', kind: 'artifact', description: '真实文件。' }],
          recommendedSkillIds: [],
        },
      ],
      risks: [],
      completionPolicy: '文件存在且内容正确。',
    };
    const events: string[] = [];
    const store: V3GroupMissionStore = {
      get: vi.fn(async () => structuredClone(record)),
      appendSnapshot: vi.fn(async (_missionId, snapshot, event) => {
        record.snapshot = structuredClone(snapshot);
        events.push(event.type);
      }),
    };
    const runAgent = vi.fn(async (input) => {
      if (input.kind === 'leader_plan') return { resultText: formatV3GroupPlanProposal(proposal) };
      throw new Error('RoleRun and aggregation must not start before Plan confirmation.');
    });
    const runner = new V3GroupMissionRunner({ store, runAgent, sessionRoot: join(root, 'sessions') });

    const initial = await runner.run(ids.mission);
    const recovered = await runner.run(ids.mission);
    record.prompt = '修改计划：文件改为两行，其余要求不变。';
    record.snapshot.plans[0]!.state = 'superseded';
    const revised = await runner.run(ids.mission);

    expect(initial).toMatchObject({ status: 'awaiting_confirmation', planVersion: 1 });
    expect(recovered).toMatchObject({ status: 'awaiting_confirmation', planVersion: 1 });
    expect(revised).toMatchObject({ status: 'awaiting_confirmation', planVersion: 2 });
    expect(record.snapshot.plans).toEqual([
      expect.objectContaining({ version: 1, state: 'superseded' }),
      expect.objectContaining({ version: 2, state: 'proposed' }),
    ]);
    expect(record.snapshot.roleRuns).toEqual([]);
    expect(runAgent).toHaveBeenCalledTimes(2);
    expect(events).toEqual([
      'leader.attempt.completed',
      'plan.proposed',
      'plan.awaiting_confirmation',
      'plan.superseded',
      'leader.attempt.completed',
      'plan.proposed',
      'plan.awaiting_confirmation',
    ]);
  });

  it('attributes a failed Leader attempt to its immutable member execution snapshot', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-group-leader-failure-'));
    roots.push(root);
    const record: V3GroupMissionStoreRecord = {
      id: ids.mission,
      prompt: '创建计划。',
      mentionedWakerIds: [],
      workspaceRoot: join(root, 'workspace'),
      profiles: [
        {
          wakerId: ids.leader,
          name: '后端',
          roleName: 'Leader',
          bio: '统筹。',
          model: 'immutable-leader-model',
          workspaceReferenceId: ids.leader,
        },
      ],
      snapshot: V3GroupMissionAggregate.create({
        missionId: ids.mission,
        goal: '创建计划。',
        leaderWakerId: ids.leader,
        members: [{ wakerId: ids.leader, name: '后端', roleName: 'Leader', available: true }],
      }).snapshot(),
    };
    const events: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const runner = new V3GroupMissionRunner({
      store: {
        get: vi.fn(async () => structuredClone(record)),
        appendSnapshot: vi.fn(async (_missionId, snapshot, event) => {
          record.snapshot = structuredClone(snapshot);
          events.push(event);
        }),
      },
      runAgent: vi.fn(async () => {
        throw new Error('gateway unavailable');
      }),
      sessionRoot: join(root, 'sessions'),
    });

    await expect(runner.run(ids.mission)).rejects.toThrow('gateway unavailable');
    expect(events).toEqual([
      {
        type: 'leader.attempt.failed',
        payload: expect.objectContaining({
          phase: 'plan',
          attempt: 1,
          memberWakerId: ids.leader,
          model: 'immutable-leader-model',
          workspaceReferenceId: ids.leader,
          detail: 'gateway unavailable',
        }),
      },
    ]);
  });

  it('plans, honors dependencies, retries invalid reports on the same RoleRun, verifies files, and aggregates completion', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-group-runner-'));
    roots.push(root);
    const workspaceRoot = join(root, 'workspace');
    await mkdir(workspaceRoot, { recursive: true });
    const record: V3GroupMissionStoreRecord = {
      id: ids.mission,
      prompt: '**@产品** 请规划并实现一个本地可运行的扫雷游戏。',
      mentionedWakerIds: [ids.product],
      workspaceRoot,
      profiles: [
        {
          wakerId: ids.leader,
          name: '后端',
          roleName: '后端工程师',
          bio: '统筹交付。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
        {
          wakerId: ids.product,
          name: '产品',
          roleName: '产品经理',
          bio: '负责产品设计。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
        {
          wakerId: ids.frontend,
          name: '前端',
          roleName: '前端工程师',
          bio: '负责网页实现。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
      ],
      snapshot: {
        missionId: ids.mission,
        goal: '交付本地可运行的扫雷游戏。',
        leaderWakerId: ids.leader,
        members: [
          { wakerId: ids.leader, name: '后端', roleName: '后端工程师', available: true },
          { wakerId: ids.product, name: '产品', roleName: '产品经理', available: true },
          { wakerId: ids.frontend, name: '前端', roleName: '前端工程师', available: true },
        ],
        plans: [],
        roleRuns: [],
        commands: [],
      },
    };
    const events: string[] = [];
    const attemptEvents: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const store: V3GroupMissionStore = {
      get: vi.fn(async () => structuredClone(record)),
      appendSnapshot: vi.fn(async (_missionId, snapshot, event) => {
        record.snapshot = structuredClone(snapshot);
        events.push(event.type);
        if (event.type.endsWith('.attempt.completed')) attemptEvents.push(event);
      }),
    };
    const proposal: V3GroupPlanProposal = {
      schemaVersion: '3.0.0',
      reportType: 'group_plan_proposal',
      missionId: ids.mission,
      goal: record.snapshot.goal,
      scope: ['产品设计', '网页实现'],
      outOfScope: ['公网部署'],
      constraints: ['共享工作区'],
      tasks: [
        {
          taskKey: 'product-design',
          title: '扫雷产品设计',
          description: '产出 PRD。',
          ownerWakerId: ids.product,
          reviewerWakerIds: [ids.leader],
          dependsOnTaskKeys: [],
          acceptanceCriteria: [{ key: 'prd-complete', description: 'PRD 可指导实现。' }],
          evidenceRequirements: [{ key: 'prd-artifact', kind: 'artifact', description: '真实 PRD 文件。' }],
          recommendedSkillIds: [],
        },
        {
          taskKey: 'game-implementation',
          title: '扫雷实现与启动',
          description: '依据 PRD 实现并启动。',
          ownerWakerId: ids.frontend,
          reviewerWakerIds: [ids.leader, ids.product],
          dependsOnTaskKeys: ['product-design'],
          acceptanceCriteria: [{ key: 'game-runs', description: '游戏可运行。' }],
          evidenceRequirements: [
            { key: 'game-artifact', kind: 'verification_report', description: '真实游戏与浏览器验证。' },
          ],
          recommendedSkillIds: [],
        },
      ],
      risks: [],
      completionPolicy: '全部任务验收和证据完成。',
    };
    let productAttempts = 0;
    let frontendAttempts = 0;
    let aggregateAttempts = 0;
    const previewUrl = 'http://localhost:3000/previews/workspace/groups/minesweeper/';
    const calls: Array<{
      kind: string;
      memberWakerId: string;
      prompt: string;
      systemPrompt: string;
      roleRunId?: string;
      reportRepair?: boolean;
      sessionPath: string;
    }> = [];
    const runAgent = vi.fn(async (input) => {
      calls.push({
        kind: input.kind,
        memberWakerId: input.member.wakerId,
        prompt: input.prompt,
        systemPrompt: input.systemPrompt,
        sessionPath: input.sessionPath,
        ...(input.roleRunId ? { roleRunId: input.roleRunId } : {}),
        ...(input.kind === 'role_run' ? { reportRepair: input.reportRepair } : {}),
      });
      const observability = {
        usage: { inputTokens: 7, outputTokens: 5, totalTokens: 12 },
        providerCorrelationId:
          calls.length === 1 ? 'signature=group-attempt-secret' : `${input.kind}-${calls.length}`,
      };
      if (input.kind === 'leader_plan') {
        return { resultText: formatV3GroupPlanProposal(proposal), ...observability };
      }
      if (input.kind === 'leader_aggregate') {
        aggregateAttempts += 1;
        if (aggregateAttempts === 1) {
          return { resultText: formatV3GroupPlanProposal(proposal), ...observability };
        }
        return { resultText: `扫雷游戏已完成并验证。\n\n${previewUrl}index.html`, ...observability };
      }
      const artifactPath = input.task.taskKey === 'product-design' ? 'PRD-minesweeper.md' : 'index.html';
      await writeFile(join(workspaceRoot, artifactPath), `${input.task.taskKey}\n`, 'utf8');
      if (input.task.taskKey === 'product-design') productAttempts += 1;
      if (input.task.taskKey === 'game-implementation') {
        frontendAttempts += 1;
        await writeFile(
          join(workspaceRoot, 'evidence-browser.json'),
          `${JSON.stringify(
            frontendAttempts === 1
              ? { status: 'failed', interactionError: 'locator.click timed out' }
              : { status: 'PASS', interactionError: null },
          )}\n`,
          'utf8',
        );
        await writeFile(
          join(workspaceRoot, 'evidence-role-run.json'),
          `${JSON.stringify({
            schemaVersion: '3.0.0',
            reportType: 'role_run_completion',
            status: 'completed',
            unresolvedIssues: [],
            completion: { readyForReview: true },
          })}\n`,
          'utf8',
        );
      }
      const evidence = [
        {
          requirementKey: input.task.evidenceRequirements[0].key,
          acceptanceKeys: [input.task.acceptanceCriteria[0].key],
          kind: input.task.evidenceRequirements[0].kind,
          artifactPath,
          summary: '文件已写入共享工作区。',
        },
        ...(input.task.taskKey === 'game-implementation'
          ? [
              {
                requirementKey: input.task.evidenceRequirements[0].key,
                acceptanceKeys: [input.task.acceptanceCriteria[0].key],
                kind: input.task.evidenceRequirements[0].kind,
                artifactPath: 'evidence-browser.json',
                summary: '真实浏览器验证通过。',
              },
              {
                requirementKey: input.task.evidenceRequirements[0].key,
                acceptanceKeys: [input.task.acceptanceCriteria[0].key],
                kind: input.task.evidenceRequirements[0].kind,
                artifactPath: 'evidence-role-run.json',
                summary: '结构化 RoleRun 完成报告验证通过。',
              },
            ]
          : []),
      ];
      return {
        ...observability,
        resultText: formatV3RoleRunReport({
          schemaVersion: '3.0.0',
          reportType: 'role_run_completion',
          roleRunId: productAttempts <= 2 ? '55555555-5555-4555-8555-555555555555' : input.roleRunId,
          taskId: input.taskId,
          planVersion: input.planVersion,
          status: 'completed',
          summary: `${input.task.title}完成。`,
          inputSummary: input.task.description,
          roleResult: '可以交接。',
          workPerformed: ['完成任务并写入共享工作区。'],
          changeSet: [artifactPath],
          artifacts: [{ path: artifactPath, displayName: input.task.title, mediaType: 'text/plain' }],
          evidence,
          unresolvedIssues: [],
          nextStepInput: '交给下游或 Leader。',
          completion: {
            acceptanceKeys: [input.task.acceptanceCriteria[0].key],
            evidenceRequirementKeys: [input.task.evidenceRequirements[0].key],
            readyForReview: true,
          },
        }),
      };
    });

    const runner = new V3GroupMissionRunner({
      store,
      runAgent,
      sessionRoot: join(root, 'sessions'),
      maxPlanAttempts: 3,
      preview: { url: previewUrl, entryPath: 'index.html' },
    });
    await expect(runner.run(ids.mission)).resolves.toMatchObject({
      status: 'awaiting_confirmation',
      planVersion: 1,
    });
    confirmPlan(record, 1, events);
    const result = await runner.run(ids.mission);

    expect(result.snapshot.plans).toEqual([expect.objectContaining({ version: 1, state: 'completed' })]);
    expect(result.snapshot.roleRuns).toEqual([
      expect.objectContaining({ taskKey: 'product-design', attemptCount: 3, state: 'completed' }),
      expect.objectContaining({ taskKey: 'game-implementation', attemptCount: 2, state: 'completed' }),
    ]);
    expect(result.snapshot.commands).toEqual([
      expect.objectContaining({ roleRunId: result.snapshot.roleRuns[0]!.id, attempt: 1, state: 'failed' }),
      expect.objectContaining({ roleRunId: result.snapshot.roleRuns[0]!.id, attempt: 2, state: 'failed' }),
      expect.objectContaining({ roleRunId: result.snapshot.roleRuns[0]!.id, attempt: 3, state: 'completed' }),
      expect.objectContaining({ roleRunId: result.snapshot.roleRuns[1]!.id, attempt: 1, state: 'failed' }),
      expect.objectContaining({ roleRunId: result.snapshot.roleRuns[1]!.id, attempt: 2, state: 'completed' }),
    ]);
    const productCalls = calls.filter(
      (call) => call.kind === 'role_run' && call.memberWakerId === ids.product,
    );
    expect(productCalls).toHaveLength(3);
    expect(productCalls[0]?.roleRunId).toBe(productCalls[1]?.roleRunId);
    expect(productCalls[1]?.roleRunId).toBe(productCalls[2]?.roleRunId);
    expect(productCalls[0]).toMatchObject({ reportRepair: false });
    expect(productCalls[1]).toMatchObject({ reportRepair: true });
    expect(productCalls[2]).toMatchObject({ reportRepair: true });
    expect(productCalls[0]?.prompt).not.toContain('Report repair only');
    expect(productCalls[1]?.prompt).toContain('Report repair only');
    expect(productCalls[1]?.prompt).toContain('Do not call tools');
    expect(productCalls[1]?.prompt).toContain('roleRunId mismatch');
    expect(productCalls[1]?.systemPrompt).toContain('Authoritative evidence mapping');
    const frontendCalls = calls.filter(
      (call) => call.kind === 'role_run' && call.memberWakerId === ids.frontend,
    );
    expect(frontendCalls).toHaveLength(2);
    expect(frontendCalls[0]?.roleRunId).toBe(frontendCalls[1]?.roleRunId);
    expect(frontendCalls[1]?.prompt).toContain('reported status failed');
    expect(calls.find(({ kind }) => kind === 'leader_plan')?.systemPrompt).toContain(previewUrl);
    expect(calls.find(({ kind }) => kind === 'leader_plan')?.sessionPath).toContain('leader-plan.jsonl');
    expect(
      calls.find(({ kind, memberWakerId }) => kind === 'role_run' && memberWakerId === ids.frontend)
        ?.systemPrompt,
    ).toContain('index.html');
    const aggregateCalls = calls.filter(({ kind }) => kind === 'leader_aggregate');
    expect(aggregateCalls).toHaveLength(2);
    expect(aggregateCalls[0]?.prompt).toContain(previewUrl);
    expect(aggregateCalls[0]?.sessionPath).toContain('leader-aggregate-1.jsonl');
    expect(aggregateCalls[1]?.sessionPath).toContain('leader-aggregate-2.jsonl');
    expect(aggregateCalls[1]?.prompt).toContain('internal structured protocol');
    expect(calls.map((call) => `${call.kind}:${call.memberWakerId}`)).toEqual([
      `leader_plan:${ids.leader}`,
      `role_run:${ids.product}`,
      `role_run:${ids.product}`,
      `role_run:${ids.product}`,
      `role_run:${ids.frontend}`,
      `role_run:${ids.frontend}`,
      `leader_aggregate:${ids.leader}`,
      `leader_aggregate:${ids.leader}`,
    ]);
    expect(events).toContain('role_run.report_rejected');
    expect(events).toContain('mission.summarizing');
    expect(events).toContain('mission.summary_rejected');
    expect(events.filter((event) => event === 'executor_command.created')).toHaveLength(5);
    expect(attemptEvents).toHaveLength(8);
    expect(attemptEvents[0]).toEqual({
      type: 'leader.attempt.completed',
      payload: expect.objectContaining({
        phase: 'plan',
        attempt: 1,
        memberWakerId: ids.leader,
        model: 'gateway-test-model',
        usage: { inputTokens: 7, outputTokens: 5, totalTokens: 12 },
        providerCorrelationId: 'signature=[REDACTED]',
      }),
    });
    expect(attemptEvents.find(({ type }) => type === 'role_run.attempt.completed')).toEqual(
      expect.objectContaining({
        payload: expect.objectContaining({
          memberWakerId: ids.product,
          model: 'gateway-test-model',
          usage: { inputTokens: 7, outputTokens: 5, totalTokens: 12 },
        }),
      }),
    );
    expect(events.at(-1)).toBe('mission.completed');
    expect(result.status).toBe('completed');
    if (result.status !== 'completed') throw new Error('Mission did not complete after confirmation.');
    expect(result.summary).toBe(`扫雷游戏已完成并验证。\n\n${previewUrl}`);
    expect(result.summary.match(/\/previews\//gu)).toHaveLength(1);
    expect(result.previewUrl).toBe(previewUrl);
  });

  it('turns a completed mission follow-up into Plan v2 and carries prior validated evidence', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-group-followup-'));
    roots.push(root);
    const workspaceRoot = join(root, 'workspace');
    await mkdir(workspaceRoot, { recursive: true });
    await writeFile(join(workspaceRoot, 'PRD-minesweeper.md'), 'validated PRD\n', 'utf8');
    const productTask = {
      taskKey: 'product-design',
      title: '扫雷产品设计',
      description: '产出 PRD。',
      ownerWakerId: ids.product,
      reviewerWakerIds: [ids.leader],
      dependsOnTaskKeys: [],
      acceptanceCriteria: [{ key: 'prd-complete', description: 'PRD 可指导实现。' }],
      evidenceRequirements: [
        { key: 'prd-artifact', kind: 'artifact' as const, description: '真实 PRD 文件。' },
      ],
    };
    const source = V3GroupMissionAggregate.create({
      missionId: ids.mission,
      goal: '交付本地可运行的扫雷游戏。',
      leaderWakerId: ids.leader,
      members: [
        { wakerId: ids.leader, name: '后端', roleName: '后端工程师', available: true },
        { wakerId: ids.product, name: '产品', roleName: '产品经理', available: true },
        { wakerId: ids.frontend, name: '前端', roleName: '前端工程师', available: true },
      ],
    });
    source.proposePlan([productTask]);
    const originalRun = source.confirmPlan(1, ids.leader).roleRuns[0]!;
    source.startRoleRun(originalRun.id);
    source.completeRoleRun(originalRun.id, {
      acceptanceKeys: ['prd-complete'],
      evidence: [{ requirementKey: 'prd-artifact', artifactPath: 'PRD-minesweeper.md' }],
    });
    const record: V3GroupMissionStoreRecord = {
      id: ids.mission,
      prompt: '游戏报错了，请验证并修复。',
      mentionedWakerIds: [],
      workspaceRoot,
      profiles: [
        {
          wakerId: ids.leader,
          name: '后端',
          roleName: '后端工程师',
          bio: '统筹交付。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
        {
          wakerId: ids.product,
          name: '产品',
          roleName: '产品经理',
          bio: '负责产品设计。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
        {
          wakerId: ids.frontend,
          name: '前端',
          roleName: '前端工程师',
          bio: '负责网页实现。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
      ],
      snapshot: source.snapshot(),
    };
    const events: string[] = [];
    const store: V3GroupMissionStore = {
      get: vi.fn(async () => structuredClone(record)),
      appendSnapshot: vi.fn(async (_missionId, snapshot, event) => {
        record.snapshot = structuredClone(snapshot);
        events.push(event.type);
      }),
    };
    const followupProposal: V3GroupPlanProposal = {
      schemaVersion: '3.0.0',
      reportType: 'group_plan_proposal',
      missionId: ids.mission,
      goal: '交付本地可运行且无报错的扫雷游戏。',
      scope: ['保留已完成任务', '验证并修复用户报告的问题'],
      outOfScope: [],
      constraints: ['不得重跑已验收的产品任务'],
      tasks: [
        { ...productTask, recommendedSkillIds: [] },
        {
          taskKey: 'repair-user-reported-error',
          title: '排查并修复游戏报错',
          description: '复现用户报告的问题，完成修复并重新验证浏览器链接。',
          ownerWakerId: ids.frontend,
          reviewerWakerIds: [ids.leader],
          dependsOnTaskKeys: ['product-design'],
          acceptanceCriteria: [{ key: 'error-fixed', description: '报错已复现并修复。' }],
          evidenceRequirements: [
            { key: 'verification', kind: 'verification_report', description: '修复验证报告。' },
          ],
          recommendedSkillIds: [],
        },
      ],
      risks: [],
      completionPolicy: '保留历史证据且新修复任务完成。',
    };
    const calls: string[] = [];
    const runAgent = vi.fn(async (input) => {
      calls.push(input.kind);
      if (input.kind === 'leader_plan') {
        expect(input.systemPrompt).toContain('Return the full next Plan');
        return { resultText: formatV3GroupPlanProposal(followupProposal) };
      }
      if (input.kind === 'leader_aggregate') return { resultText: '报错已修复，原验收证据保持有效。' };
      expect(input.task.taskKey).toBe('repair-user-reported-error');
      await writeFile(join(workspaceRoot, 'repair-verification.md'), 'fixed and verified\n', 'utf8');
      return {
        resultText: formatV3RoleRunReport({
          schemaVersion: '3.0.0',
          reportType: 'role_run_completion',
          roleRunId: input.roleRunId,
          taskId: input.taskId,
          planVersion: input.planVersion,
          status: 'completed',
          summary: '报错已修复。',
          inputSummary: input.task.description,
          roleResult: '浏览器验证通过。',
          workPerformed: ['复现、修复并验证。'],
          changeSet: ['repair-verification.md'],
          artifacts: [
            {
              path: 'repair-verification.md',
              displayName: '修复验证报告',
              mediaType: 'text/markdown',
            },
          ],
          evidence: [
            {
              requirementKey: 'verification',
              acceptanceKeys: ['error-fixed'],
              kind: 'verification_report',
              artifactPath: 'repair-verification.md',
              summary: '修复后浏览器验证通过。',
            },
          ],
          unresolvedIssues: [],
          nextStepInput: 'Leader 汇总。',
          completion: {
            acceptanceKeys: ['error-fixed'],
            evidenceRequirementKeys: ['verification'],
            readyForReview: true,
          },
        }),
      };
    });

    const runner = new V3GroupMissionRunner({
      store,
      runAgent,
      sessionRoot: join(root, 'sessions'),
    });
    const result = await runner.run(ids.mission);

    expect(result.status).toBe('completed');
    expect(result.snapshot.plans).toEqual([
      expect.objectContaining({ version: 1, state: 'completed' }),
      expect.objectContaining({ version: 2, state: 'completed' }),
    ]);
    expect(result.snapshot.plans[1]?.tasks[0]).toMatchObject({
      taskKey: 'product-design',
      resumeDecision: 'carry_forward_completed',
      carriedEvidence: [{ requirementKey: 'prd-artifact', artifactPath: 'PRD-minesweeper.md' }],
    });
    expect(calls).toEqual(['leader_plan', 'role_run', 'leader_aggregate']);
    expect(events).not.toContain('plan.awaiting_confirmation');
    expect(events).toContain('plan.confirmed');
    expect(events.at(-1)).toBe('mission.completed');
  });

  it('turns a deterministic failed acceptance report into a repair and re-verification Plan', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-group-remediation-'));
    roots.push(root);
    const workspaceRoot = join(root, 'workspace');
    await mkdir(workspaceRoot, { recursive: true });
    const record: V3GroupMissionStoreRecord = {
      id: ids.mission,
      prompt: '检查扫雷键盘可操作性，发现问题后修复并复验。',
      mentionedWakerIds: [ids.frontend],
      workspaceRoot,
      profiles: [
        {
          wakerId: ids.leader,
          name: '后端',
          roleName: 'Leader',
          bio: '统筹修复闭环。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
        {
          wakerId: ids.frontend,
          name: '前端',
          roleName: '前端工程师',
          bio: '执行验证与修复。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
      ],
      snapshot: {
        missionId: ids.mission,
        goal: '完成键盘验收、修复与复验。',
        leaderWakerId: ids.leader,
        members: [
          { wakerId: ids.leader, name: '后端', roleName: 'Leader', available: true },
          { wakerId: ids.frontend, name: '前端', roleName: '前端工程师', available: true },
        ],
        plans: [],
        roleRuns: [],
        commands: [],
      },
    };
    const events: string[] = [];
    const store: V3GroupMissionStore = {
      get: vi.fn(async () => structuredClone(record)),
      appendSnapshot: vi.fn(async (_missionId, snapshot, event) => {
        record.snapshot = structuredClone(snapshot);
        events.push(event.type);
      }),
    };
    const auditTask: V3GroupPlanProposal['tasks'][number] = {
      taskKey: 'keyboard-audit',
      title: '键盘可操作性验收',
      description: '真实执行键盘验收并记录结果。',
      ownerWakerId: ids.frontend,
      reviewerWakerIds: [ids.leader],
      dependsOnTaskKeys: [],
      acceptanceCriteria: [{ key: 'audit-executed', description: '验收已真实执行。' }],
      evidenceRequirements: [
        { key: 'audit-report', kind: 'verification_report', description: '机器可读验收报告。' },
      ],
      recommendedSkillIds: [],
    };
    const proposal = (tasks: V3GroupPlanProposal['tasks']): V3GroupPlanProposal => ({
      schemaVersion: '3.0.0',
      reportType: 'group_plan_proposal',
      missionId: ids.mission,
      goal: record.snapshot.goal,
      scope: ['验收闭环'],
      outOfScope: [],
      constraints: ['必须保留失败证据'],
      tasks,
      risks: [],
      completionPolicy: '修复并复验通过后完成。',
    });
    const repairTask: V3GroupPlanProposal['tasks'][number] = {
      taskKey: 'focus-indicator-repair',
      title: '修复焦点指示器',
      description: '添加可见的 focus-visible 样式。',
      ownerWakerId: ids.frontend,
      reviewerWakerIds: [ids.leader],
      dependsOnTaskKeys: ['keyboard-audit'],
      acceptanceCriteria: [{ key: 'focus-fixed', description: '焦点指示器可见。' }],
      evidenceRequirements: [{ key: 'fix-artifact', kind: 'artifact', description: '修复后的页面。' }],
      recommendedSkillIds: [],
    };
    const recheckTask: V3GroupPlanProposal['tasks'][number] = {
      taskKey: 'keyboard-recheck',
      title: '焦点修复后复验',
      description: '重新执行键盘验收。',
      ownerWakerId: ids.frontend,
      reviewerWakerIds: [ids.leader],
      dependsOnTaskKeys: ['focus-indicator-repair'],
      acceptanceCriteria: [{ key: 'recheck-passed', description: '复验通过。' }],
      evidenceRequirements: [
        { key: 'recheck-report', kind: 'verification_report', description: '通过的复验报告。' },
      ],
      recommendedSkillIds: [],
    };
    let planCalls = 0;
    const roleCalls: string[] = [];
    const runAgent = vi.fn(async (input) => {
      if (input.kind === 'leader_plan') {
        planCalls += 1;
        if (planCalls === 2) {
          expect(input.prompt).toContain('Verification failures requiring remediation');
          expect(input.systemPrompt).toContain('repair and re-verification');
        }
        return {
          resultText: formatV3GroupPlanProposal(
            planCalls === 1 ? proposal([auditTask]) : proposal([auditTask, repairTask, recheckTask]),
          ),
        };
      }
      if (input.kind === 'leader_aggregate') return { resultText: '焦点问题已修复并复验通过。' };
      roleCalls.push(input.task.taskKey);
      const reportPath =
        input.task.taskKey === 'keyboard-audit'
          ? 'keyboard-audit.json'
          : input.task.taskKey === 'keyboard-recheck'
            ? 'keyboard-recheck.json'
            : 'index.html';
      await writeFile(
        join(workspaceRoot, reportPath),
        input.task.taskKey === 'keyboard-audit'
          ? `${JSON.stringify({ status: 'failed', failedChecks: ['cell focus indicator'] })}\n`
          : input.task.taskKey === 'keyboard-recheck'
            ? `${JSON.stringify({ status: 'passed', failedChecks: [] })}\n`
            : '.cell:focus-visible { outline: 2px solid navy; }\n',
        'utf8',
      );
      const criterion = input.task.acceptanceCriteria[0]!;
      const requirement = input.task.evidenceRequirements[0]!;
      return {
        resultText: formatV3RoleRunReport({
          schemaVersion: '3.0.0',
          reportType: 'role_run_completion',
          roleRunId: input.roleRunId,
          taskId: input.taskId,
          planVersion: input.planVersion,
          status: 'completed',
          summary: `${input.task.title}已执行。`,
          inputSummary: input.task.description,
          roleResult: '已提交真实结果。',
          workPerformed: ['执行任务并保存证据。'],
          changeSet: [reportPath],
          artifacts: [{ path: reportPath, displayName: input.task.title, mediaType: 'text/plain' }],
          evidence: [
            {
              requirementKey: requirement.key,
              acceptanceKeys: [criterion.key],
              kind: requirement.kind,
              artifactPath: reportPath,
              summary: '真实证据已保存。',
            },
          ],
          unresolvedIssues: [],
          nextStepInput: '交给 Leader 判断。',
          completion: {
            acceptanceKeys: [criterion.key],
            evidenceRequirementKeys: [requirement.key],
            readyForReview: true,
          },
        }),
      };
    });

    const runner = new V3GroupMissionRunner({
      store,
      runAgent,
      sessionRoot: join(root, 'sessions'),
      maxRemediationPlans: 2,
    });
    await expect(runner.run(ids.mission)).resolves.toMatchObject({
      status: 'awaiting_confirmation',
      planVersion: 1,
    });
    confirmPlan(record, 1, events);
    await expect(runner.run(ids.mission)).resolves.toMatchObject({
      status: 'awaiting_confirmation',
      planVersion: 2,
    });
    confirmPlan(record, 2, events);
    const result = await runner.run(ids.mission);

    expect(result.snapshot.plans).toEqual([
      expect.objectContaining({ version: 1, state: 'completed' }),
      expect.objectContaining({ version: 2, state: 'completed' }),
    ]);
    expect(result.snapshot.plans[1]?.tasks[0]).toMatchObject({
      taskKey: 'keyboard-audit',
      resumeDecision: 'carry_forward_completed',
    });
    expect(roleCalls).toEqual(['keyboard-audit', 'focus-indicator-repair', 'keyboard-recheck']);
    expect(events).toContain('role_run.verification_failed');
    expect(events).toContain('mission.remediation_planning');
    expect(events.at(-1)).toBe('mission.completed');
  });

  it('enforces the remediation Plan budget across separate confirmation dispatches', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-group-remediation-budget-'));
    roots.push(root);
    const workspaceRoot = join(root, 'workspace');
    await mkdir(workspaceRoot, { recursive: true });
    const auditTask: V3GroupPlanProposal['tasks'][number] = {
      taskKey: 'initial-audit',
      title: '初次验收',
      description: '执行初次验收。',
      ownerWakerId: ids.frontend,
      reviewerWakerIds: [ids.leader],
      dependsOnTaskKeys: [],
      acceptanceCriteria: [{ key: 'audit-finished', description: '验收已执行。' }],
      evidenceRequirements: [{ key: 'audit-report', kind: 'verification_report', description: '验收报告。' }],
      recommendedSkillIds: [],
    };
    const recheckTask: V3GroupPlanProposal['tasks'][number] = {
      taskKey: 'remediation-recheck',
      title: '补救复验',
      description: '执行补救后的复验。',
      ownerWakerId: ids.frontend,
      reviewerWakerIds: [ids.leader],
      dependsOnTaskKeys: ['initial-audit'],
      acceptanceCriteria: [{ key: 'recheck-finished', description: '复验已执行。' }],
      evidenceRequirements: [
        { key: 'recheck-report', kind: 'verification_report', description: '复验报告。' },
      ],
      recommendedSkillIds: [],
    };
    const aggregate = V3GroupMissionAggregate.create({
      missionId: ids.mission,
      goal: '验证补救预算。',
      leaderWakerId: ids.leader,
      members: [
        { wakerId: ids.leader, name: '后端', roleName: 'Leader', available: true },
        { wakerId: ids.frontend, name: '前端', roleName: '前端工程师', available: true },
      ],
    });
    aggregate.proposePlan([auditTask]);
    const initialRun = aggregate.confirmPlan(1, ids.leader).roleRuns[0]!;
    aggregate.startRoleRun(initialRun.id);
    await writeFile(join(workspaceRoot, 'audit.json'), `${JSON.stringify({ status: 'failed' })}\n`, 'utf8');
    aggregate.completeRoleRun(initialRun.id, {
      acceptanceKeys: ['audit-finished'],
      evidence: [{ requirementKey: 'audit-report', artifactPath: 'audit.json' }],
    });
    aggregate.proposeFollowupPlan([auditTask, recheckTask]);
    aggregate.confirmPlan(2, ids.leader);

    const record: V3GroupMissionStoreRecord = {
      id: ids.mission,
      prompt: '补救复验仍失败时必须停止。',
      mentionedWakerIds: [ids.frontend],
      workspaceRoot,
      profiles: [
        {
          wakerId: ids.leader,
          name: '后端',
          roleName: 'Leader',
          bio: '统筹验收。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
        {
          wakerId: ids.frontend,
          name: '前端',
          roleName: '前端工程师',
          bio: '执行复验。',
          model: 'gateway-test-model',
          workspaceReferenceId: null,
        },
      ],
      snapshot: aggregate.snapshot(),
    };
    const store: V3GroupMissionStore = {
      get: vi.fn(async () => structuredClone(record)),
      appendSnapshot: vi.fn(async (_missionId, snapshot) => {
        record.snapshot = structuredClone(snapshot);
      }),
    };
    const runAgent = vi.fn(async (input) => {
      if (input.kind !== 'role_run') throw new Error('The remediation budget must stop further planning.');
      await writeFile(
        join(workspaceRoot, 'recheck.json'),
        `${JSON.stringify({ status: 'failed', failedChecks: ['interaction'] })}\n`,
        'utf8',
      );
      return {
        resultText: formatV3RoleRunReport({
          schemaVersion: '3.0.0',
          reportType: 'role_run_completion',
          roleRunId: input.roleRunId,
          taskId: input.taskId,
          planVersion: input.planVersion,
          status: 'completed',
          summary: '复验已执行但仍失败。',
          inputSummary: input.task.description,
          roleResult: '机器可读报告已保存。',
          workPerformed: ['执行真实复验。'],
          changeSet: ['recheck.json'],
          artifacts: [{ path: 'recheck.json', displayName: '复验报告', mediaType: 'application/json' }],
          evidence: [
            {
              requirementKey: 'recheck-report',
              acceptanceKeys: ['recheck-finished'],
              kind: 'verification_report',
              artifactPath: 'recheck.json',
              summary: '复验失败证据。',
            },
          ],
          unresolvedIssues: [],
          nextStepInput: '停止自动补救并报告失败。',
          completion: {
            acceptanceKeys: ['recheck-finished'],
            evidenceRequirementKeys: ['recheck-report'],
            readyForReview: true,
          },
        }),
      };
    });
    const runner = new V3GroupMissionRunner({
      store,
      runAgent,
      sessionRoot: join(root, 'sessions'),
      maxRemediationPlans: 1,
    });

    await expect(runner.run(ids.mission)).rejects.toThrow(
      'Verification remediation exceeded 1 Plan attempts',
    );
    expect(runAgent).toHaveBeenCalledTimes(1);
  });
});
