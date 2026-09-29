import { describe, expect, it } from 'vitest';

import {
  buildV3GroupLeaderSystemPrompt,
  buildV3GroupRoleRunSystemPrompt,
  formatV3GroupPlanProposal,
  parseV3GroupPlanProposal,
  type V3GroupPlanProposal,
} from '../src/v3-group-prompts.ts';

const ids = {
  mission: '11111111-1111-4111-8111-111111111111',
  leader: '22222222-2222-4222-8222-222222222222',
  product: '33333333-3333-4333-8333-333333333333',
  frontend: '44444444-4444-4444-8444-444444444444',
  roleRun: '55555555-5555-4555-8555-555555555555',
  task: '66666666-6666-4666-8666-666666666666',
};

const memberExecution = { model: 'gateway-test-model', workspaceReferenceId: null } as const;
const members = [
  { wakerId: ids.leader, name: '后端', roleName: '后端工程师', bio: '负责统筹和后端。', ...memberExecution },
  { wakerId: ids.product, name: '产品', roleName: '产品经理', bio: '负责产品设计。', ...memberExecution },
  { wakerId: ids.frontend, name: '前端', roleName: '前端工程师', bio: '负责网页实现。', ...memberExecution },
];

const proposal: V3GroupPlanProposal = {
  schemaVersion: '3.0.0',
  reportType: 'group_plan_proposal',
  missionId: ids.mission,
  goal: '交付可在本地浏览器打开的扫雷游戏。',
  scope: ['产品设计', '网页实现', '本地运行验证'],
  outOfScope: ['公网部署'],
  constraints: ['使用共享项目根目录', '最后提供真实可访问链接'],
  tasks: [
    {
      taskKey: 'product-design',
      title: '扫雷游戏产品设计',
      description: '产出规则、交互与验收标准。',
      ownerWakerId: ids.product,
      reviewerWakerIds: [ids.leader],
      dependsOnTaskKeys: [],
      acceptanceCriteria: [{ key: 'prd-complete', description: 'PRD 可直接指导开发。' }],
      evidenceRequirements: [{ key: 'prd-artifact', kind: 'artifact', description: '提交 PRD 文件。' }],
      recommendedSkillIds: [],
    },
    {
      taskKey: 'game-implementation',
      title: '扫雷网页实现与本地运行',
      description: '依据 PRD 实现、启动并验证游戏。',
      ownerWakerId: ids.frontend,
      reviewerWakerIds: [ids.leader, ids.product],
      dependsOnTaskKeys: ['product-design'],
      acceptanceCriteria: [
        { key: 'game-playable', description: '游戏规则和交互可用。' },
        { key: 'local-url', description: '真实本地链接可打开。' },
      ],
      evidenceRequirements: [
        { key: 'source-artifact', kind: 'artifact', description: '提交实现文件。' },
        {
          key: 'runtime-verification',
          kind: 'verification_report',
          description: '提交本地 HTTP 验证。',
        },
      ],
      recommendedSkillIds: [],
    },
  ],
  risks: ['浏览器端交互需要完整回归。'],
  completionPolicy: '所有任务及其验收和证据要求通过后，由 Leader 汇总。',
};

describe('V3 group PI prompts and Leader Plan contract', () => {
  it('parses a schema-bound Leader proposal and validates membership, mention ownership, and DAG', () => {
    const result = parseV3GroupPlanProposal(formatV3GroupPlanProposal(proposal), {
      missionId: ids.mission,
      missionGoal: proposal.goal,
      leaderWakerId: ids.leader,
      members,
      requiredOwnerWakerIds: [ids.product],
    });

    expect(result).toEqual({ ok: true, proposal });
  });

  it('accepts one strict raw or fenced JSON proposal when the model omits protocol markers', () => {
    const expected = {
      missionId: ids.mission,
      missionGoal: proposal.goal,
      leaderWakerId: ids.leader,
      members,
      requiredOwnerWakerIds: [ids.product],
    };

    expect(parseV3GroupPlanProposal(JSON.stringify(proposal), expected)).toEqual({ ok: true, proposal });
    expect(parseV3GroupPlanProposal(`\`\`\`json\n${JSON.stringify(proposal)}\n\`\`\``, expected)).toEqual({
      ok: true,
      proposal,
    });
    expect(
      parseV3GroupPlanProposal(`Here is the plan:\n${JSON.stringify(proposal)}`, expected),
    ).toMatchObject({ ok: false, category: 'invalid_plan_proposal' });
  });

  it('rejects a Plan assigned to a model-invented Waker', () => {
    const result = parseV3GroupPlanProposal(
      formatV3GroupPlanProposal({
        ...proposal,
        tasks: [
          {
            ...proposal.tasks[0]!,
            ownerWakerId: '77777777-7777-4777-8777-777777777777',
          },
        ],
      }),
      {
        missionId: ids.mission,
        missionGoal: proposal.goal,
        leaderWakerId: ids.leader,
        members,
        requiredOwnerWakerIds: [ids.product],
      },
    );

    expect(result).toMatchObject({
      ok: false,
      category: 'invalid_plan_proposal',
      detail: expect.stringContaining('active group member'),
    });
  });

  it('returns an actionable schema path when the Leader uses structured risk objects', () => {
    const malformed = {
      ...proposal,
      risks: [{ risk: '端口占用', mitigation: '改用空闲端口' }],
    };
    const result = parseV3GroupPlanProposal(
      `QODER_TEAM_PLAN_PROPOSAL\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_PLAN_PROPOSAL`,
      {
        missionId: ids.mission,
        missionGoal: proposal.goal,
        leaderWakerId: ids.leader,
        members,
        requiredOwnerWakerIds: [ids.product],
      },
    );

    expect(result).toMatchObject({
      ok: false,
      category: 'invalid_plan_proposal',
      detail: expect.stringContaining('/risks/0'),
    });
  });

  it('returns the exact completionPolicy path for the observed structured object output', () => {
    const malformed = {
      ...proposal,
      completionPolicy: {
        criteria: ['所有任务通过验收。'],
        finalDelivery: '向用户提供真实预览链接。',
      },
    };
    const result = parseV3GroupPlanProposal(
      `QODER_TEAM_PLAN_PROPOSAL\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_PLAN_PROPOSAL`,
      {
        missionId: ids.mission,
        missionGoal: proposal.goal,
        leaderWakerId: ids.leader,
        members,
        requiredOwnerWakerIds: [ids.product],
      },
    );

    expect(result).toMatchObject({
      ok: false,
      category: 'invalid_plan_proposal',
      detail: expect.stringContaining('/completionPolicy'),
    });
  });

  it('returns the exact tasks path when a Leader proposes no executable tasks', () => {
    const malformed = { ...proposal, tasks: [] };
    const result = parseV3GroupPlanProposal(
      `QODER_TEAM_PLAN_PROPOSAL\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_PLAN_PROPOSAL`,
      {
        missionId: ids.mission,
        missionGoal: proposal.goal,
        leaderWakerId: ids.leader,
        members,
        requiredOwnerWakerIds: [ids.product],
      },
    );

    expect(result).toMatchObject({
      ok: false,
      category: 'invalid_plan_proposal',
      detail: expect.stringContaining('/tasks'),
    });
  });

  it('normalizes one fenced JSON Plan with the exact terminal marker and no surrounding prose', () => {
    const result = parseV3GroupPlanProposal(
      `\`\`\`json\n${JSON.stringify(proposal)}\n\`\`\`\nEND_QODER_TEAM_PLAN_PROPOSAL`,
      {
        missionId: ids.mission,
        missionGoal: proposal.goal,
        leaderWakerId: ids.leader,
        members,
        requiredOwnerWakerIds: [ids.product],
      },
    );

    expect(result).toEqual({ ok: true, proposal });
  });

  it('does not normalize fenced Plan JSON when it is accompanied by free-form prose', () => {
    const result = parseV3GroupPlanProposal(
      `Here is the plan:\n\`\`\`json\n${JSON.stringify(proposal)}\n\`\`\`\nEND_QODER_TEAM_PLAN_PROPOSAL`,
      {
        missionId: ids.mission,
        missionGoal: proposal.goal,
        leaderWakerId: ids.leader,
        members,
        requiredOwnerWakerIds: [ids.product],
      },
    );

    expect(result).toMatchObject({ ok: false, category: 'invalid_plan_proposal' });
  });

  it('injects the real Waker roster into Leader PI and the immutable task/evidence contract into member PI', () => {
    const leaderPrompt = buildV3GroupLeaderSystemPrompt({
      missionId: ids.mission,
      leaderWakerId: ids.leader,
      members,
      requiredOwnerWakerIds: [ids.product],
    });
    const rolePrompt = buildV3GroupRoleRunSystemPrompt({
      missionId: ids.mission,
      roleRunId: ids.roleRun,
      taskId: ids.task,
      planVersion: 1,
      member: members[1]!,
      task: proposal.tasks[0]!,
      dependencyHandoffs: [],
    });

    expect(leaderPrompt).toContain(`产品 (${ids.product})`);
    expect(leaderPrompt).toContain('group_plan_proposal');
    expect(leaderPrompt).toContain('risks must be a JSON array of strings');
    expect(leaderPrompt).toContain('completionPolicy must be one JSON string');
    expect(rolePrompt).toContain(`roleRunId must equal ${ids.roleRun}`);
    expect(rolePrompt).toContain('prd-artifact');
    expect(rolePrompt).toContain('sandbox_exec');
    expect(rolePrompt).toContain('workdude-browser-verify');
    expect(rolePrompt).toContain('never install or download a browser package');
    expect(rolePrompt).toContain('do not create a custom Playwright or Chromium harness');
    expect(rolePrompt).toContain('diagnose and fix the application code');
    expect(rolePrompt).toContain('roleResult must be a string');
    expect(rolePrompt).toContain('acceptanceKeys must contain at least one');
    expect(rolePrompt).toContain('report status blocked');
    expect(rolePrompt).toContain('Authoritative evidence mapping');
    expect(rolePrompt).toContain('The only legal evidence kinds are artifact, handoff_package');
    expect(rolePrompt).toContain('"requirementKey": "prd-artifact"');
    expect(rolePrompt).toContain('"kind": "artifact"');
    expect(rolePrompt).toContain(`"roleRunId": "${ids.roleRun}"`);
    expect(rolePrompt).toContain('QODER_TEAM_ROLE_RUN_REPORT');
  });
});
