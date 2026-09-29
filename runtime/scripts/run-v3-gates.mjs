import { existsSync, readFileSync, statSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createEvidenceRecord, writeEvidenceRecord } from './v3-evidence.mjs';
import { resolveStableV3EvidenceDirectory } from './v3-evidence-path.mjs';
import { parseV3ReferenceStateIds, parseV3SpecificationInventory } from './v3-verification.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const npmCli =
  process.env.npm_execpath ?? resolve(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');

const gateOrder = ['test', 'build', 'real-infrastructure', 'response-e2e', 'visual', 'secret-scan'];
const specificationInventory = parseV3SpecificationInventory(
  readFileSync(resolve(root, 'specs/003-workdude-v3-rebuild/spec.md'), 'utf8'),
);
const referenceStateIds = parseV3ReferenceStateIds(
  readFileSync(resolve(root, 'tests/visual/v3/reference-states.ts'), 'utf8'),
);
const numberedRange = (prefix, start, end) =>
  Array.from(
    { length: end - start + 1 },
    (_, index) => `${prefix}-${String(start + index).padStart(3, '0')}`,
  );
const acceptanceForStories = (...stories) =>
  specificationInventory.acceptanceScenarios.filter((id) =>
    stories.some((story) => id.startsWith(`US${story}/`)),
  );
const gateEvidence = {
  test: {
    taskIds: ['T002', 'T005', 'T012', 'T023', 'T183', 'T184', 'T185'],
    requirements: [...numberedRange('FR', 1, 24), 'FR-030'],
    successCriteria: ['SC-001', 'SC-004', 'SC-005', 'SC-008', 'SC-009', 'SC-012'],
    acceptanceScenarios: acceptanceForStories(1, 2, 3, 4, 5, 6, 7),
    referenceStates: [],
  },
  build: {
    taskIds: ['T004', 'T023', 'T179', 'T184', 'T185'],
    requirements: ['FR-010', 'FR-011', 'FR-023', 'FR-028', 'FR-029'],
    successCriteria: ['SC-009', 'SC-011'],
    acceptanceScenarios: acceptanceForStories(3, 8),
    referenceStates: [],
  },
  'real-infrastructure': {
    taskIds: ['T017', 'T057', 'T095', 'T109', 'T129', 'T161', 'T184'],
    requirements: numberedRange('FR', 3, 24),
    successCriteria: ['SC-001', 'SC-004', 'SC-005', 'SC-008', 'SC-010'],
    acceptanceScenarios: acceptanceForStories(1, 2, 5, 6, 7, 8),
    referenceStates: [],
  },
  'response-e2e': {
    taskIds: ['T057', 'T147', 'T153', 'T162', 'T182', 'T184', 'T185'],
    requirements: [
      'FR-005',
      'FR-006',
      'FR-007',
      'FR-008',
      'FR-009',
      'FR-017',
      'FR-021',
      'FR-022',
      'FR-023',
      'FR-024',
    ],
    successCriteria: ['SC-002', 'SC-003', 'SC-004', 'SC-005', 'SC-009'],
    acceptanceScenarios: acceptanceForStories(2, 3, 5, 6),
    referenceStates: [],
  },
  visual: {
    taskIds: ['T006', 'T060', 'T068', 'T134', 'T163', 'T169', 'T183', 'T185'],
    requirements: ['FR-003', 'FR-004', ...numberedRange('FR', 10, 27)],
    successCriteria: ['SC-006', 'SC-007'],
    acceptanceScenarios: acceptanceForStories(1, 2, 3, 4, 5, 6, 7),
    referenceStates: referenceStateIds,
  },
  'secret-scan': {
    taskIds: ['T018', 'T128', 'T165'],
    requirements: ['FR-023', 'FR-028', 'FR-029', 'FR-030'],
    successCriteria: ['SC-009', 'SC-012'],
    acceptanceScenarios: acceptanceForStories(8),
    referenceStates: [],
  },
};
const gates = {
  test: {
    description: 'Run the implemented V3 contract and Phase 2 foundation tests.',
    requiredFiles: [
      'tests/contract/v3/source-integrity.test.ts',
      'tests/contract/v3/security-gate-matrix.test.ts',
      'tests/contract/v3/secret-safety.test.ts',
      'packages/agent-runtime/test/v3-policy.test.ts',
      'packages/agent-runtime/test/v3-project-preparation.test.ts',
    ],
    commands: [
      [
        process.execPath,
        [
          'scripts/run-vitest.mjs',
          'tests/contract/v3',
          'packages/product-contracts/test',
          'packages/data-access/test/v3-foundation.test.ts',
          'packages/data-access/test/v3-wakers-groups.test.ts',
          'packages/data-access/test/v3-avatars.test.ts',
          'packages/data-access/test/v3-deletion-cleanup.test.ts',
          'packages/data-access/test/v3-execution.test.ts',
          'packages/data-access/test/v3-exports.test.ts',
          'packages/data-access/test/v3-waker-configuration.test.ts',
          'packages/data-access/test/v3-permission-policy.test.ts',
          'packages/data-access/test/v3-automations.test.ts',
          'packages/data-access/test/v3-workflows.test.ts',
          'packages/data-access/test/v3-projects.test.ts',
          'packages/data-access/test/v3-knowledge.test.ts',
          'packages/data-access/test/v3-knowledge-file-cleanup.test.ts',
          'packages/data-access/test/v3-files.test.ts',
          'packages/data-access/test/v3-knowledge-context.test.ts',
          'packages/data-access/test/v3-skills-connectors.test.ts',
          'packages/data-access/test/v3-im.test.ts',
          'packages/data-access/test/v3-skill-package.test.ts',
          'packages/data-access/test/v3-skill-context.test.ts',
          'packages/data-access/test/object-storage.test.ts',
          'packages/agent-gateway/test/v3-gateways.test.ts',
          'packages/agent-gateway/test/v3-resource-gateways.test.ts',
          'packages/agent-runtime/test',
          'packages/features/test',
          'apps/desktop/test/v3-product-host.test.ts',
          'apps/desktop/test/automation-api-server.test.ts',
          'apps/desktop/test/ipc-security.test.ts',
          'apps/desktop/test/preview-server.test.ts',
          'apps/desktop/test/local-broker-host.test.ts',
          'services/sandbox-broker/test/security.test.ts',
          'services/platform-api/test/v3-plugin.test.ts',
          'services/platform-api/test/rate-limit-policy.test.ts',
          'services/platform-api/test/v3-wakers-groups.test.ts',
          'services/platform-api/test/v3-avatars.test.ts',
          'services/platform-api/test/v3-conversation-run.test.ts',
          'services/platform-api/test/v3-waker-configuration.test.ts',
          'services/platform-api/test/v3-permission-policy.test.ts',
          'services/platform-api/test/v3-automations.test.ts',
          'services/platform-api/test/v3-workflows.test.ts',
          'services/platform-api/test/v3-projects.test.ts',
          'services/platform-api/test/v3-knowledge.test.ts',
          'services/platform-api/test/v3-skills-connectors.test.ts',
          'services/platform-api/test/v3-im.test.ts',
          'services/cloud-worker/test/v3-deletion-cleanup-worker.test.ts',
          'services/cloud-worker/test/v3-knowledge-file-cleanup-worker.test.ts',
          'services/cloud-worker/test/v3-knowledge-worker.test.ts',
          'services/cloud-worker/test/v3-project-worker.test.ts',
          'tests/integration/v3/migrations.test.ts',
          'tests/integration/v3/harness.test.ts',
          'tests/integration/v3/event-recovery.test.ts',
          'tests/integration/v3/sandbox-policy.test.ts',
        ],
      ],
    ],
  },
  build: {
    description: 'Type-check, lint, format-check, and build the repository with the V3 product source.',
    requiredFiles: ['packages/features/src/v3/client.tsx', 'packages/features/src/v3/product.tsx'],
    commands: [
      [process.execPath, [npmCli, 'run', 'check']],
      [process.execPath, [npmCli, 'run', 'build']],
    ],
  },
  'real-infrastructure': {
    description: 'Run V3 tests against the real PostgreSQL, Redis, and Docker harness.',
    requiredFiles: [
      'tests/integration/v3/harness.ts',
      'tests/integration/v3/task-board-benchmark.test.ts',
      'deploy/compose/compose.test.yaml',
    ],
    commands: [
      [
        process.execPath,
        [
          'scripts/run-vitest.mjs',
          'tests/integration/v3',
          'packages/data-access/test/v3-wakers-groups.test.ts',
          'packages/data-access/test/v3-avatars.test.ts',
          'packages/data-access/test/v3-deletion-cleanup.test.ts',
          'packages/data-access/test/v3-postgres-execution.test.ts',
          'packages/data-access/test/v3-exports.test.ts',
          'packages/data-access/test/v3-waker-configuration.test.ts',
          'packages/data-access/test/v3-permission-policy.test.ts',
          'packages/data-access/test/v3-automations.test.ts',
          'packages/data-access/test/v3-workflows.test.ts',
          'packages/data-access/test/v3-projects.test.ts',
          'packages/data-access/test/v3-knowledge.test.ts',
          'packages/data-access/test/v3-knowledge-file-cleanup.test.ts',
          'packages/data-access/test/v3-files.test.ts',
          'packages/data-access/test/v3-skills-connectors.test.ts',
          'packages/data-access/test/v3-im.test.ts',
          'services/cloud-worker/test/v3-run-worker.integration.test.ts',
          'services/cloud-worker/test/v3-scheduler.integration.test.ts',
          'services/cloud-worker/test/v3-workflow-worker.integration.test.ts',
          'services/platform-api/test/v3-event-stream.integration.test.ts',
          'services/platform-api/test/v3-cloud-journey.integration.test.ts',
          'services/platform-api/test/v3-export-journey.integration.test.ts',
          '--maxWorkers=1',
        ],
      ],
    ],
  },
  'response-e2e': {
    description:
      'Run no-interception real COS exports, Knowledge/OCR, Qoder Marketplace, Feishu, and enterprise AI gateway Web/Desktop reload, restart, and failure journeys.',
    requiredFiles: [
      'tests/e2e/v3/resource-roundtrip.spec.ts',
      'tests/e2e/v3/web-response-stream.spec.ts',
      'tests/e2e/v3/response-timing.ts',
      'tests/e2e/v3/desktop-wakers-groups.spec.ts',
      'tests/e2e/v3/desktop-group-mission.spec.ts',
      'tests/e2e/v3/desktop-ipc-security.spec.ts',
      'tests/e2e/v3/automations.spec.ts',
      'tests/e2e/v3/group-task-shell.spec.ts',
      'tests/e2e/v3/wakerflow.spec.ts',
      'tests/e2e/v3/desktop-automation.spec.ts',
      'apps/desktop/out/QoderWake-win32-x64/QoderWake.exe',
      '.env',
    ],
    commands: [
      [process.execPath, ['scripts/prepare-v3-response-environment.mjs']],
      [
        process.execPath,
        ['scripts/run-playwright.mjs', 'tests/e2e/v3/desktop-ipc-security.spec.ts', '--workers=1'],
      ],
      [
        process.execPath,
        [
          '--env-file=.env',
          'scripts/run-playwright.mjs',
          'tests/e2e/v3/resource-roundtrip.spec.ts',
          '--workers=1',
        ],
      ],
      [process.execPath, ['scripts/run-playwright.mjs', 'tests/e2e/v3/automations.spec.ts', '--workers=1']],
      [process.execPath, ['scripts/run-playwright.mjs', 'tests/e2e/v3/wakerflow.spec.ts', '--workers=1']],
      [
        process.execPath,
        [
          '--env-file=.env',
          'scripts/run-playwright.mjs',
          'tests/e2e/v3/group-task-shell.spec.ts',
          '--workers=1',
        ],
      ],
      [
        process.execPath,
        [
          '--env-file=.env',
          'scripts/run-playwright.mjs',
          'tests/e2e/v3/desktop-automation.spec.ts',
          '--workers=1',
        ],
      ],
      [
        process.execPath,
        [
          '--env-file=.env',
          'scripts/run-playwright.mjs',
          'tests/e2e/v3/web-response-stream.spec.ts',
          '--workers=1',
        ],
      ],
      [
        process.execPath,
        [
          '--env-file=.env',
          'scripts/run-playwright.mjs',
          'tests/e2e/v3/desktop-wakers-groups.spec.ts',
          '--grep',
          'consecutive clean profiles|streams and recovers|three consecutive randomized|provider authentication',
          '--workers=1',
        ],
      ],
      [
        process.execPath,
        [
          '--env-file=.env',
          'scripts/run-playwright.mjs',
          'tests/e2e/v3/desktop-group-mission.spec.ts',
          '--workers=1',
        ],
      ],
    ],
  },
  visual: {
    description: 'Run the deterministic V3 reference-state visual and geometry suite.',
    requiredFiles: [
      'tests/e2e/v3/visual-shell.spec.ts',
      'tests/e2e/v3/accessibility-shell.spec.ts',
      'tests/e2e/v3/desktop-accessibility-scale.spec.ts',
      'tests/e2e/v3/desktop-builtin-connector-lifecycle.spec.ts',
      'tests/e2e/v3/desktop-role-details-drawer.spec.ts',
      'tests/e2e/v3/settings-preferences-visual.spec.ts',
      'tests/e2e/v3/role-details-drawer.spec.ts',
      'tests/e2e/v3/state-failures-visual.spec.ts',
      'tests/e2e/v3/group-conversation-visual.spec.ts',
      'tests/e2e/v3/group-execution-log-visual.spec.ts',
      'tests/e2e/v3/group-plan-confirmation-visual.spec.ts',
      'tests/e2e/v3/group-remediation-visual.spec.ts',
      'tests/e2e/v3/response-surface-visual.spec.ts',
      'tests/e2e/v3/waker-settings-visual.spec.ts',
      'tests/e2e/v3/waker-task-visual.spec.ts',
      'tests/e2e/v3/task-board-visual.spec.ts',
      'tests/e2e/v3/project-visual.spec.ts',
      'tests/e2e/v3/knowledge-visual.spec.ts',
      'tests/e2e/v3/loading-states-visual.spec.ts',
      'tests/e2e/v3/skill-connector-visual.spec.ts',
      'tests/e2e/v3/im-visual.spec.ts',
      'tests/e2e/v3/waker-memory-visual.spec.ts',
      'tests/e2e/v3/waker-permission-visual.spec.ts',
      'tests/e2e/v3/automation-visual.spec.ts',
      'tests/e2e/v3/visual-harness.ts',
    ],
    commands: [
      [
        process.execPath,
        [
          'scripts/run-playwright.mjs',
          'tests/e2e/v3/visual-shell.spec.ts',
          'tests/e2e/v3/accessibility-shell.spec.ts',
          'tests/e2e/v3/desktop-accessibility-scale.spec.ts',
          'tests/e2e/v3/desktop-builtin-connector-lifecycle.spec.ts',
          'tests/e2e/v3/desktop-role-details-drawer.spec.ts',
          'tests/e2e/v3/settings-preferences-visual.spec.ts',
          'tests/e2e/v3/role-details-drawer.spec.ts',
          'tests/e2e/v3/state-failures-visual.spec.ts',
          'tests/e2e/v3/group-conversation-visual.spec.ts',
          'tests/e2e/v3/group-execution-log-visual.spec.ts',
          'tests/e2e/v3/group-plan-confirmation-visual.spec.ts',
          'tests/e2e/v3/group-remediation-visual.spec.ts',
          'tests/e2e/v3/response-surface-visual.spec.ts',
          'tests/e2e/v3/waker-settings-visual.spec.ts',
          'tests/e2e/v3/waker-task-visual.spec.ts',
          'tests/e2e/v3/task-board-visual.spec.ts',
          'tests/e2e/v3/project-visual.spec.ts',
          'tests/e2e/v3/knowledge-visual.spec.ts',
          'tests/e2e/v3/loading-states-visual.spec.ts',
          'tests/e2e/v3/skill-connector-visual.spec.ts',
          'tests/e2e/v3/im-visual.spec.ts',
          'tests/e2e/v3/waker-memory-visual.spec.ts',
          'tests/e2e/v3/waker-permission-visual.spec.ts',
          'tests/e2e/v3/automation-visual.spec.ts',
          '--workers=1',
        ],
      ],
    ],
  },
  'secret-scan': {
    description: 'Scan V3 tracked files and generated artifacts for credential canaries.',
    requiredFiles: ['scripts/scan-v3-secrets.mjs'],
    commands: [[process.execPath, ['scripts/scan-v3-secrets.mjs']]],
  },
};

function missingFiles(gate) {
  return gate.requiredFiles.filter((relativePath) => {
    const absolutePath = resolve(root, relativePath);
    return !existsSync(absolutePath) || !statSync(absolutePath).isFile();
  });
}

function printStatus(id) {
  const missing = missingFiles(gates[id]);
  const state = missing.length === 0 ? 'READY' : 'BLOCKED';
  console.log(`[v3-gates] ${id}: ${state} - ${gates[id].description}`);
  if (missing.length > 0) console.log(`  missing: ${missing.join(', ')}`);
}

function runCommand(id, executable, args) {
  console.log(`[v3-gates] ${id}: ${executable} ${args.join(' ')}`);
  const environment =
    id === 'real-infrastructure'
      ? {
          ...process.env,
          WORKDUDE_V3_REAL_INFRASTRUCTURE: '1',
          WORKDUDE_V3_MANAGE_COMPOSE: '1',
        }
      : id === 'visual'
        ? {
            ...process.env,
            // The visual harness has no settings endpoint; keep its official
            // reference snapshots stable. Production Web builds leave this
            // unset (enabled by default), and the dedicated virtual-key tests
            // opt in explicitly.
            VITE_ENABLE_AI_GATEWAY_VIRTUAL_KEY: 'false',
          }
        : process.env;
  const result = spawnSync(executable, args, {
    cwd: root,
    env: environment,
    stdio: 'inherit',
  });

  if (result.error) throw result.error;
  if (result.status !== 0) {
    console.error(`[v3-gates] ${id}: command failed with exit code ${result.status ?? 1}.`);
    return result.status ?? 1;
  }

  return 0;
}

function gitOutput(args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(String(result.stderr || `git ${args.join(' ')} failed`));
  return String(result.stdout).trim();
}

async function recordGateEvidence(id, startedAt, finishedAt) {
  const outputDirectory = process.env.WORKDUDE_V3_EVIDENCE_DIR;
  if (!outputDirectory) return;
  const stableOutputDirectory = resolveStableV3EvidenceDirectory(root, outputDirectory);
  const revision = gitOutput(['rev-parse', 'HEAD']);
  const dirty = gitOutput(['status', '--porcelain']).length > 0;
  const metadata = gateEvidence[id];
  const record = createEvidenceRecord({
    evidenceId: `${id}-${revision.slice(0, 12)}`,
    gateId: id,
    taskIds: metadata.taskIds,
    claims: {
      requirements: metadata.requirements,
      successCriteria: metadata.successCriteria,
      acceptanceScenarios: metadata.acceptanceScenarios,
      referenceStates: metadata.referenceStates,
    },
    source: { revision, dirty },
    command: { argv: [process.execPath, 'scripts/run-v3-gates.mjs', id] },
    environment: {
      platform: process.platform,
      arch: process.arch,
      nodeVersion: process.version,
      ci: Boolean(process.env.CI),
    },
    startedAt,
    finishedAt,
    exitCode: 0,
    mocked: false,
    skipped: false,
    partial: false,
    metrics: { commandCount: gates[id].commands.length },
    artifacts: [],
  });
  await writeEvidenceRecord(resolve(stableOutputDirectory, `${id}.json`), record);
  console.log(
    `[v3-gates] ${id}: wrote source-bound evidence to ${resolve(stableOutputDirectory, `${id}.json`)}`,
  );
}

const selector = process.argv[2] ?? '--list';

if (process.env.WORKDUDE_V3_EVIDENCE_DIR) {
  resolveStableV3EvidenceDirectory(root, process.env.WORKDUDE_V3_EVIDENCE_DIR);
}

if (selector === '--list') {
  for (const id of gateOrder) printStatus(id);
  console.log('[v3-gates] READY means only that prerequisites exist; it is not PASS evidence.');
  process.exit(0);
}

const selected = selector === 'all' ? gateOrder : [selector];
const unknown = selected.filter((id) => !gates[id]);
if (unknown.length > 0) {
  console.error(`[v3-gates] Unknown gate: ${unknown.join(', ')}`);
  console.error(`[v3-gates] Expected one of: all, ${gateOrder.join(', ')}, --list`);
  process.exit(2);
}

const blocked = selected
  .map((id) => ({ id, missing: missingFiles(gates[id]) }))
  .filter(({ missing }) => missing.length > 0);

if (blocked.length > 0) {
  for (const { id, missing } of blocked) {
    console.error(`[v3-gates] ${id}: BLOCKED; missing ${missing.join(', ')}`);
  }
  console.error('[v3-gates] No selected gate was run. BLOCKED is never recorded as PASS.');
  process.exit(2);
}

for (const id of selected) {
  const startedAt = new Date().toISOString();
  for (const [executable, args] of gates[id].commands) {
    const exitCode = runCommand(id, executable, args);
    if (exitCode !== 0) process.exit(exitCode);
  }
  await recordGateEvidence(id, startedAt, new Date().toISOString());
  console.log(`[v3-gates] ${id}: commands completed; release evidence is evaluated separately.`);
}
