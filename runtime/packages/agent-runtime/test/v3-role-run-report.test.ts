import { describe, expect, it } from 'vitest';

import {
  formatV3RoleRunReport,
  parseV3RoleRunReport,
  type V3RoleRunReport,
} from '../src/v3-role-run-report.ts';

const expected = {
  roleRunId: '11111111-1111-4111-8111-111111111111',
  taskId: '22222222-2222-4222-8222-222222222222',
  planVersion: 1,
  requiredAcceptanceKeys: ['game-runs', 'browser-opens'],
  requiredEvidenceKeys: ['source-files', 'runtime-check'],
  requiredEvidenceKinds: {
    'source-files': 'artifact',
    'runtime-check': 'verification_report',
  } as const,
};

const report: V3RoleRunReport = {
  schemaVersion: '3.0.0',
  reportType: 'role_run_completion',
  roleRunId: expected.roleRunId,
  taskId: expected.taskId,
  planVersion: expected.planVersion,
  status: 'completed',
  summary: '扫雷已实现并通过本地浏览器验证。',
  inputSummary: '依据产品 PRD 实现可在本地浏览器打开的扫雷游戏。',
  roleResult: '实现完成，服务地址由 Leader 汇总。',
  workPerformed: ['实现游戏规则', '启动并验证本地服务'],
  changeSet: ['index.html', 'server.js'],
  artifacts: [
    { path: 'index.html', displayName: '扫雷游戏', mediaType: 'text/html' },
    { path: 'server.js', displayName: '本地服务', mediaType: 'text/javascript' },
  ],
  evidence: [
    {
      requirementKey: 'source-files',
      acceptanceKeys: ['game-runs'],
      kind: 'artifact',
      artifactPath: 'index.html',
      summary: '游戏源文件存在。',
    },
    {
      requirementKey: 'runtime-check',
      acceptanceKeys: ['browser-opens'],
      kind: 'verification_report',
      artifactPath: 'server.js',
      summary: 'HTTP 服务已启动并返回 200。',
    },
  ],
  unresolvedIssues: [],
  nextStepInput: '可由 Leader 汇总交付。',
  completion: {
    acceptanceKeys: ['game-runs', 'browser-opens'],
    evidenceRequirementKeys: ['source-files', 'runtime-check'],
    readyForReview: true,
  },
};

describe('V3 RoleRun structured report', () => {
  it('accepts only a delimited report bound to the current RoleRun, task, Plan, and evidence contract', () => {
    const parsed = parseV3RoleRunReport(formatV3RoleRunReport(report), expected);

    expect(parsed).toEqual({ ok: true, report });
  });

  it('accepts one strict raw or fenced JSON report when the model omits protocol markers', () => {
    expect(parseV3RoleRunReport(JSON.stringify(report), expected)).toEqual({ ok: true, report });
    expect(parseV3RoleRunReport(`\`\`\`json\n${JSON.stringify(report)}\n\`\`\``, expected)).toEqual({
      ok: true,
      report,
    });
  });

  it('accepts multiple persisted evidence files for one official evidence requirement', () => {
    const withSupportingEvidence: V3RoleRunReport = {
      ...report,
      evidence: [
        ...report.evidence,
        {
          requirementKey: 'runtime-check',
          acceptanceKeys: ['game-runs', 'browser-opens'],
          kind: 'verification_report',
          artifactPath: 'evidence/browser.json',
          summary: '真实浏览器加载与交互均通过。',
        },
      ],
    };

    const parsed = parseV3RoleRunReport(formatV3RoleRunReport(withSupportingEvidence), expected);

    expect(parsed).toEqual({ ok: true, report: withSupportingEvidence });
  });

  it('canonicalizes a known requirement to the authoritative Plan evidence kind', () => {
    const malformed = {
      ...report,
      evidence: report.evidence.map((item) => ({ ...item, kind: 'file' })),
    };
    const parsed = parseV3RoleRunReport(
      `QODER_TEAM_ROLE_RUN_REPORT\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toEqual({ ok: true, report });
  });

  it('rejects a mismatched RoleRun identity with the official failure category', () => {
    const parsed = parseV3RoleRunReport(
      formatV3RoleRunReport({
        ...report,
        roleRunId: '33333333-3333-4333-8333-333333333333',
      }),
      expected,
    );

    expect(parsed).toMatchObject({
      ok: false,
      category: 'invalid_structured_report',
      detail: expect.stringContaining('roleRunId mismatch'),
    });
  });

  it('rejects completion when any acceptance or evidence requirement is unproven', () => {
    const parsed = parseV3RoleRunReport(
      formatV3RoleRunReport({
        ...report,
        evidence: report.evidence.slice(0, 1),
      }),
      expected,
    );

    expect(parsed).toMatchObject({
      ok: false,
      category: 'invalid_structured_report',
      detail: expect.stringContaining('runtime-check'),
    });
  });

  it('does not accept free-form success text as a completion transition', () => {
    const parsed = parseV3RoleRunReport('已完成，链接是 http://localhost:3000/', expected);

    expect(parsed).toMatchObject({
      ok: false,
      category: 'invalid_structured_report',
      detail: expect.stringContaining('not valid JSON'),
    });
  });

  it('rejects artifact references that can escape the shared workspace', () => {
    const parsed = parseV3RoleRunReport(
      formatV3RoleRunReport({
        ...report,
        artifacts: [{ ...report.artifacts[0]!, path: '../outside.txt' }],
      }),
      expected,
    );

    expect(parsed).toMatchObject({
      ok: false,
      category: 'invalid_structured_report',
      detail: expect.stringContaining('workspace-relative'),
    });
  });

  it('returns the exact schema path when roleResult is emitted as an object', () => {
    const malformed = { ...report, roleResult: { document: 'docs/PRD.md' } };
    const parsed = parseV3RoleRunReport(
      `QODER_TEAM_ROLE_RUN_REPORT\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toMatchObject({
      ok: false,
      category: 'invalid_structured_report',
      detail: expect.stringContaining('/roleResult'),
    });
  });

  it('returns actionable paths for missing and additional report properties', () => {
    const malformed = { ...report, taskKey: 'product-design' } as Record<string, unknown>;
    delete malformed.nextStepInput;
    const parsed = parseV3RoleRunReport(
      `QODER_TEAM_ROLE_RUN_REPORT\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toMatchObject({
      ok: false,
      category: 'invalid_structured_report',
      detail: expect.stringContaining('/nextStepInput'),
    });
    expect(parsed.ok ? '' : parsed.detail).toContain('/taskKey');
  });

  it('returns the allowed values for invalid report discriminator fields', () => {
    const malformed = {
      ...report,
      schemaVersion: '1.0.0',
      reportType: 'completion',
      status: 'done',
    };
    const parsed = parseV3RoleRunReport(
      `QODER_TEAM_ROLE_RUN_REPORT\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toMatchObject({ ok: false, category: 'invalid_structured_report' });
    expect(parsed.ok ? '' : parsed.detail).toContain('/schemaVersion: must equal "3.0.0"');
    expect(parsed.ok ? '' : parsed.detail).toContain('/reportType: must equal "role_run_completion"');
    expect(parsed.ok ? '' : parsed.detail).toContain('/status: must be one of "completed", "blocked"');
  });

  it('returns the nested schema path when submitted evidence has no acceptance key', () => {
    const malformed = {
      ...report,
      evidence: [{ ...report.evidence[0]!, acceptanceKeys: [] }],
    };
    const parsed = parseV3RoleRunReport(
      `QODER_TEAM_ROLE_RUN_REPORT\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toMatchObject({
      ok: false,
      category: 'invalid_structured_report',
      detail: expect.stringContaining('/evidence/0/acceptanceKeys'),
    });
  });

  it('reports nested extra properties and detectable evidence gaps in one rejection', () => {
    const malformed = {
      ...report,
      evidence: [
        {
          ...report.evidence[0]!,
          description: 'This property is not part of the RoleRun evidence contract.',
        },
      ],
    };
    const parsed = parseV3RoleRunReport(
      `QODER_TEAM_ROLE_RUN_REPORT\n${JSON.stringify(malformed)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toMatchObject({ ok: false, category: 'invalid_structured_report' });
    expect(parsed.ok ? '' : parsed.detail).toContain('/evidence/0/description');
    expect(parsed.ok ? '' : parsed.detail).toContain('browser-opens');
    expect(parsed.ok ? '' : parsed.detail).toContain('runtime-check');
    expect(parsed.ok ? '' : parsed.detail).toContain('/evidence[].requirementKey');
    expect(parsed.ok ? '' : parsed.detail).toContain('/evidence[].acceptanceKeys');
  });

  it('rejects a completed report that still declares unresolved issues', () => {
    const parsed = parseV3RoleRunReport(
      formatV3RoleRunReport({ ...report, unresolvedIssues: ['共享工作区不可写。'] }),
      expected,
    );

    expect(parsed).toMatchObject({
      ok: false,
      detail: expect.stringContaining('unresolved issues'),
    });
  });

  it('normalizes one Markdown JSON fence inside the exact RoleRun markers', () => {
    const parsed = parseV3RoleRunReport(
      `QODER_TEAM_ROLE_RUN_REPORT\n\`\`\`json\n${JSON.stringify(report)}\n\`\`\`\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toEqual({ ok: true, report });
  });

  it('accepts one trailing report when DeepSeek joins the start marker and JSON after status prose', () => {
    const parsed = parseV3RoleRunReport(
      `All tests pass. I will now deliver the final structured report.\n\nQODER_TEAM_ROLE_RUN_REPORT${JSON.stringify(report)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toEqual({ ok: true, report });
  });

  it('accepts the observed DeepSeek marker line with one trailing ASCII colon', () => {
    const parsed = parseV3RoleRunReport(
      `Task complete.\n\nQODER_TEAM_ROLE_RUN_REPORT:\n${JSON.stringify(report)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toEqual({ ok: true, report });
  });

  it('accepts the observed DeepSeek angle-wrapped start marker', () => {
    const parsed = parseV3RoleRunReport(
      `Task complete.\n\n<QODER_TEAM_ROLE_RUN_REPORT>\n${JSON.stringify(report)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toEqual({ ok: true, report });
  });

  it('still rejects duplicate plain and angle-wrapped report blocks', () => {
    const parsed = parseV3RoleRunReport(
      `${formatV3RoleRunReport(report)}\n<QODER_TEAM_ROLE_RUN_REPORT>\n${JSON.stringify(report)}\nEND_QODER_TEAM_ROLE_RUN_REPORT`,
      expected,
    );

    expect(parsed).toMatchObject({ ok: false, category: 'invalid_structured_report' });
  });

  it('reports every actionable completion issue from one rejected response', () => {
    const parsed = parseV3RoleRunReport(
      formatV3RoleRunReport({
        ...report,
        evidence: [report.evidence[0]!, report.evidence[0]!, report.evidence[1]!],
        unresolvedIssues: ['浏览器进程需要清理。'],
      }),
      expected,
    );

    expect(parsed).toMatchObject({ ok: false, category: 'invalid_structured_report' });
    expect(parsed.ok ? '' : parsed.detail).toContain('cannot contain unresolved issues');
  });
});
