import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { inspectGitHubReleaseRun, signGateReceipt, verifyGateReceipt } from './v4-final-authority.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const scriptPath = fileURLToPath(import.meta.url);
const rootEnvFile = resolve(root, '.env');
const optionalRootEnvArguments = existsSync(rootEnvFile) ? ['--env-file=.env'] : [];
if (optionalRootEnvArguments.length > 0) process.loadEnvFile(rootEnvFile);
const npmCli =
  process.env.npm_execpath ?? resolve(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');
const desktopExecutable = 'apps/desktop/out/QoderWake-win32-x64/QoderWake.exe';
const responseRunProject =
  process.env.WORKDUDE_V4_RESPONSE_PROJECT?.trim() || `workdude-v4-response-${process.pid}`;
const responseRunFailurePrefix =
  process.env.WORKDUDE_V4_RESPONSE_FAILURE_PREFIX?.trim() || `${responseRunProject}-failure`;

const gateOrder = ['gateway', 'gateway-integration', 'browser-connector', 'response', 'secret-scan'];
const finalSelectorGateOrder = {
  'final-prepush': [
    'source-static',
    'deterministic',
    'real-infrastructure',
    'gateway-runtime',
    'web-functional',
    'web-visual-accessibility',
  ],
  'final-windows': ['build-package', 'installed-desktop', 'source-artifact', 'windows-native-lifecycle'],
  'final-production': ['production-deploy', 'production-restart', 'production-rollback', 'production-soak'],
};
const finalSelectorOrder = [
  'final-prepush',
  'final-windows',
  'final-native',
  'final-production',
  'final-authority',
];
const receiptAuthorities = {
  'final-prepush': {
    kind: 'prepush',
    pathEnvironment: 'WORKDUDE_V4_PREPUSH_RECEIPT_PATH',
    privateKeyEnvironment: 'WORKDUDE_V4_PREPUSH_RECEIPT_PRIVATE_KEY_BASE64',
    publicKeyEnvironment: 'WORKDUDE_V4_PREPUSH_RECEIPT_PUBLIC_KEY_BASE64',
  },
  'final-windows': {
    kind: 'windows-installed',
    pathEnvironment: 'WORKDUDE_V4_WINDOWS_RECEIPT_PATH',
    privateKeyEnvironment: 'WORKDUDE_V4_WINDOWS_RECEIPT_PRIVATE_KEY_BASE64',
    publicKeyEnvironment: 'WORKDUDE_V4_WINDOWS_RECEIPT_PUBLIC_KEY_BASE64',
  },
  'final-production': {
    kind: 'production',
    pathEnvironment: 'WORKDUDE_V4_PRODUCTION_RECEIPT_PATH',
    privateKeyEnvironment: 'WORKDUDE_V4_PRODUCTION_RECEIPT_PRIVATE_KEY_BASE64',
    publicKeyEnvironment: 'WORKDUDE_V4_PRODUCTION_RECEIPT_PUBLIC_KEY_BASE64',
  },
};
const receiptPrivateKeyEnvironmentNames = Object.values(receiptAuthorities).map(
  ({ privateKeyEnvironment }) => privateKeyEnvironment,
);

const gates = {
  gateway: {
    description: 'Run deterministic V4 gateway, configuration, Runtime, and probe contracts.',
    requiredFiles: [
      'packages/agent-runtime/test/enterprise-ai-gateway.test.ts',
      'packages/agent-runtime/test/v4-runtime.integration.test.ts',
      'packages/agent-runtime/test/v4-knowledge-gateway.test.ts',
      'packages/product-contracts/test/server-configuration.test.ts',
      'tests/contract/v4/gateway-probe.test.ts',
      'tests/contract/v4/response-failure-gateway.test.ts',
      'tests/contract/v4/pi-gateway-runtime.test.ts',
    ],
    command: [
      process.execPath,
      [
        'scripts/run-vitest.mjs',
        'packages/agent-runtime/test/enterprise-ai-gateway.test.ts',
        'packages/agent-runtime/test/v4-runtime.integration.test.ts',
        'packages/agent-runtime/test/v4-knowledge-gateway.test.ts',
        'packages/product-contracts/test/server-configuration.test.ts',
        'tests/contract/v4/gateway-probe.test.ts',
        'tests/contract/v4/response-failure-gateway.test.ts',
        'tests/contract/v4/pi-gateway-runtime.test.ts',
        '--maxWorkers=1',
      ],
    ],
  },
  'gateway-integration': {
    description: 'Run V4 provider migration plus Cloud and Desktop proxy integration.',
    requiredFiles: [
      'tests/integration/v4/ai-gateway-migrations.test.ts',
      'packages/data-access/test/v3-execution.test.ts',
      'packages/data-access/test/v3-wakers-groups.test.ts',
      'packages/data-access/test/v3-automations.test.ts',
      'packages/data-access/test/v3-im.test.ts',
      'services/platform-api/test/v3-wakers-groups.test.ts',
      'services/platform-api/test/v3-conversation-run.test.ts',
      'services/platform-api/test/v3-automations.test.ts',
      'services/platform-api/test/v3-im.test.ts',
      'services/platform-api/test/v3-workflows.test.ts',
      'services/platform-api/test/v3-knowledge.test.ts',
      'services/cloud-worker/test/v3-scheduler.test.ts',
      'services/cloud-worker/test/v3-knowledge-worker.test.ts',
      'services/cloud-worker/test/v3-run-worker.integration.test.ts',
      'services/cloud-worker/test/v3-direct-group-worker.test.ts',
      'services/cloud-worker/test/v3-workflow-worker.integration.test.ts',
      'apps/desktop/test/v3-product-host.test.ts',
      'services/platform-api/test/v4-ai-gateway-proxy.test.ts',
      'services/platform-api/test/v4-ai-gateway-virtual-key.test.ts',
      'services/cloud-worker/test/v4-ai-gateway.integration.test.ts',
      'packages/data-access/test/v4-ai-gateway-virtual-key-vault.test.ts',
      'packages/product-contracts/test/v4-ai-gateway-virtual-key-contracts.test.ts',
      'apps/web/test/ai-gateway-virtual-key.test.ts',
      'packages/features/test/v4-ai-gateway-virtual-key-settings.test.ts',
      'apps/desktop/test/v4-ai-gateway-virtual-key.test.ts',
      'apps/desktop/test/v4-ai-gateway.test.ts',
      'tests/contract/v4/desktop-gateway-cleanup.test.ts',
      'packages/platform-auth/test/feishu-oauth.test.ts',
      'packages/platform-auth/test/feishu-identity-resolver.test.ts',
      'packages/data-access/test/v4-feishu-auth-repository.test.ts',
      'services/platform-api/test/proxy-trust.test.ts',
      'services/platform-api/test/rate-limit-policy.test.ts',
      'services/platform-api/test/v4-feishu-auth.test.ts',
      'services/platform-api/test/v4-feishu-key-claim.test.ts',
      'services/platform-api/test/v5-virtual-key-race.test.ts',
      'services/platform-api/test/v4-feishu-csrf.test.ts',
      'apps/web/test/feishu-auth.test.ts',
      'apps/desktop/test/v4-feishu-auth.test.ts',
    ],
    command: [
      process.execPath,
      [
        'scripts/run-vitest.mjs',
        'tests/integration/v4/ai-gateway-migrations.test.ts',
        'packages/data-access/test/v3-execution.test.ts',
        'packages/data-access/test/v3-wakers-groups.test.ts',
        'packages/data-access/test/v3-automations.test.ts',
        'packages/data-access/test/v3-im.test.ts',
        'services/platform-api/test/v3-wakers-groups.test.ts',
        'services/platform-api/test/v3-conversation-run.test.ts',
        'services/platform-api/test/v3-automations.test.ts',
        'services/platform-api/test/v3-im.test.ts',
        'services/platform-api/test/v3-workflows.test.ts',
        'services/platform-api/test/v3-knowledge.test.ts',
        'services/cloud-worker/test/v3-scheduler.test.ts',
        'services/cloud-worker/test/v3-knowledge-worker.test.ts',
        'services/cloud-worker/test/v3-run-worker.integration.test.ts',
        'services/cloud-worker/test/v3-direct-group-worker.test.ts',
        'services/cloud-worker/test/v3-workflow-worker.integration.test.ts',
        'apps/desktop/test/v3-product-host.test.ts',
        'services/platform-api/test/v4-ai-gateway-proxy.test.ts',
        'services/platform-api/test/v4-ai-gateway-virtual-key.test.ts',
        'services/cloud-worker/test/v4-ai-gateway.integration.test.ts',
        'packages/data-access/test/v4-ai-gateway-virtual-key-vault.test.ts',
        'packages/product-contracts/test/v4-ai-gateway-virtual-key-contracts.test.ts',
        'apps/web/test/ai-gateway-virtual-key.test.ts',
        'packages/features/test/v4-ai-gateway-virtual-key-settings.test.ts',
        'apps/desktop/test/v4-ai-gateway-virtual-key.test.ts',
        'apps/desktop/test/v4-ai-gateway.test.ts',
        'tests/contract/v4/desktop-gateway-cleanup.test.ts',
        'packages/platform-auth/test/feishu-oauth.test.ts',
        'packages/platform-auth/test/feishu-identity-resolver.test.ts',
        'packages/data-access/test/v4-feishu-auth-repository.test.ts',
        'services/platform-api/test/proxy-trust.test.ts',
        'services/platform-api/test/rate-limit-policy.test.ts',
        'services/platform-api/test/v4-feishu-auth.test.ts',
        'services/platform-api/test/v4-feishu-key-claim.test.ts',
        'services/platform-api/test/v5-virtual-key-race.test.ts',
        'services/platform-api/test/v4-feishu-csrf.test.ts',
        'apps/web/test/feishu-auth.test.ts',
        'apps/desktop/test/v4-feishu-auth.test.ts',
        '--maxWorkers=1',
      ],
    ],
  },
  'browser-connector': {
    description:
      'Run the fail-closed Browser Connector contract, persistence, host, Pi adapter, and shared UI matrix.',
    requiredFiles: [
      'apps/desktop/browser-extension/manifest.json',
      'apps/desktop/browser-extension/background.js',
      'apps/desktop/browser-extension/popup.js',
      'apps/desktop/native-host/BrowserNativeHost.cs',
      'packages/product-contracts/test/browser-connector-contract.test.ts',
      'packages/agent-gateway/test/browser-connector-gateways.test.ts',
      'packages/data-access/test/v3-browser-connector-enablement.test.ts',
      'services/platform-api/test/v3-browser-connector-enablement.test.ts',
      'apps/desktop/test/browser-connector-host.test.ts',
      'apps/desktop/test/browser-native-lifecycle.test.ts',
      'apps/desktop/test/browser-native-generation.test.ts',
      'packages/agent-runtime/test/v3-browser-connector.test.ts',
      'apps/desktop/test/v3-product-host.test.ts',
      'apps/desktop/test/v4-desktop-product.test.ts',
      'packages/features/test/v3-browser-connector-actions.test.ts',
      'tests/e2e/v3/skill-connector-visual.spec.ts',
      'tests/e2e/v4/desktop-browser-connector.spec.ts',
      'scripts/run-browser-connector-e2e.mjs',
      'apps/web/vite.config.ts',
    ],
    commands: [
      [
        process.execPath,
        [
          'scripts/run-vitest.mjs',
          'packages/product-contracts/test/browser-connector-contract.test.ts',
          'packages/agent-gateway/test/browser-connector-gateways.test.ts',
          'packages/data-access/test/v3-browser-connector-enablement.test.ts',
          'services/platform-api/test/v3-browser-connector-enablement.test.ts',
          'apps/desktop/test/browser-connector-host.test.ts',
          'apps/desktop/test/browser-native-lifecycle.test.ts',
          'apps/desktop/test/browser-native-generation.test.ts',
          'packages/agent-runtime/test/v3-browser-connector.test.ts',
          'apps/desktop/test/v3-product-host.test.ts',
          'apps/desktop/test/v4-desktop-product.test.ts',
          'packages/features/test/v3-browser-connector-actions.test.ts',
          '--maxWorkers=1',
        ],
      ],
      [process.execPath, ['scripts/run-browser-connector-e2e.mjs']],
      [process.execPath, [npmCli, 'run', 'build:desktop']],
      [
        process.execPath,
        ['scripts/run-playwright.mjs', 'tests/e2e/v4/desktop-browser-connector.spec.ts', '--workers=1'],
      ],
      [process.execPath, ['scripts/smoke-desktop.mjs']],
    ],
  },
  response: {
    description: 'Run no-interception V4 Web Cloud and installed Desktop gateway journeys.',
    requiredFiles: [
      'tests/e2e/v4/web-ai-gateway.spec.ts',
      'tests/e2e/v4/desktop-ai-gateway.spec.ts',
      'tests/e2e/v4/group-ai-gateway.spec.ts',
      'tests/e2e/v4/desktop-group-ai-gateway.spec.ts',
      'scripts/prepare-v4-response-environment.mjs',
      'deploy/compose/compose.response-runtime.yaml',
      'deploy/compose/compose.response.yaml',
      desktopExecutable,
      '.env',
    ],
    commands: [
      [process.execPath, ['--env-file=.env', 'scripts/prepare-v4-response-environment.mjs']],
      ...[
        'tests/e2e/v4/web-ai-gateway.spec.ts',
        'tests/e2e/v4/desktop-ai-gateway.spec.ts',
        'tests/e2e/v4/group-ai-gateway.spec.ts',
        'tests/e2e/v4/desktop-group-ai-gateway.spec.ts',
      ].map((testFile) => [
        process.execPath,
        ['--env-file=.env', 'scripts/run-playwright.mjs', testFile, '--workers=1'],
      ]),
    ],
    environment: {
      WORKDUDE_V4_RESPONSE_PROJECT: responseRunProject,
      WORKDUDE_V4_RESPONSE_FAILURE_PREFIX: responseRunFailurePrefix,
    },
  },
  'secret-scan': {
    description: 'Scan V4 source, generated assets, packages, logs, and evidence.',
    requiredFiles: [
      'scripts/scan-v4-secrets.mjs',
      'tests/contract/v4/no-provider-bypass.test.ts',
      'tests/contract/v4/secret-safety.test.ts',
      'tests/contract/v4/ai-gateway-virtual-key-release.test.ts',
      'tests/contract/v4/v5-release-scan.test.ts',
    ],
    command: [
      process.execPath,
      [
        ...optionalRootEnvArguments,
        'scripts/run-vitest.mjs',
        'tests/contract/v4/no-provider-bypass.test.ts',
        'tests/contract/v4/secret-safety.test.ts',
        'tests/contract/v4/ai-gateway-virtual-key-release.test.ts',
        'tests/contract/v4/v5-release-scan.test.ts',
        '--maxWorkers=1',
      ],
    ],
  },
};

const webFunctionalTests = [
  'tests/e2e/v4/private-message-parity.spec.ts',
  'tests/e2e/v4/group-message-parity.spec.ts',
  'tests/e2e/v4/knowledge-folder-tree.spec.ts',
  'tests/e2e/v4/knowledge-add-source-reference.spec.ts',
  'tests/e2e/v4/full-capability.spec.ts',
  'tests/e2e/v4/gateway-model-menu.spec.ts',
];
const webVisualAccessibilityTests = [
  'tests/e2e/v4/web-official-reference-diff.spec.ts',
  'tests/e2e/v4/web-accessibility-responsive.spec.ts',
];
const installedDesktopTests = [
  'tests/e2e/v4/desktop-browser-shell.spec.ts',
  'tests/e2e/v4/desktop-browser-connector.spec.ts',
  'tests/e2e/v4/desktop-security.spec.ts',
];
const completeResponseEnvironment = [
  'APP_ACCESS_TOKEN',
  'DESKTOP_PLATFORM_ACCESS_TOKEN',
  'LITELLM_MODEL',
  'STORAGE_S3_ENDPOINT',
  'STORAGE_S3_ACCESS_KEY',
  'STORAGE_S3_SECRET_KEY',
  'STORAGE_S3_BUCKET',
  'STORAGE_S3_REGION',
  'STORAGE_S3_PREFIX',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'FEISHU_AUTH_ENCRYPTION_KEY',
];
const finalRevision = process.env.WORKDUDE_V4_FINAL_REVISION ?? '<missing-final-revision>';
const rollbackRevision = process.env.WORKDUDE_V4_ROLLBACK_REVISION ?? '<missing-rollback-revision>';
const feishuResponseEnvironment = {
  FEISHU_APP_ID: process.env.FEISHU_APP_ID || process.env.app_id,
  FEISHU_APP_SECRET: process.env.FEISHU_APP_SECRET || process.env.app_secret,
};

const finalGates = {
  'source-static': {
    description: 'Verify Pi/source/Compose policy, types, lint, and formatting.',
    requiredFiles: [
      'package.json',
      'scripts/verify-pi-source.mjs',
      'scripts/verify-compose-policy.mjs',
      'tsconfig.json',
    ],
    commands: [[process.execPath, [npmCli, 'run', 'check']]],
  },
  deterministic: {
    description: 'Run the complete deterministic unit and contract suite in one worker.',
    requiredFiles: ['scripts/run-vitest.mjs'],
    commands: [[process.execPath, ['scripts/run-vitest.mjs', '--maxWorkers=1']]],
  },
  'real-infrastructure': {
    description: 'Run the managed PostgreSQL, Redis, Docker, and recovery matrix.',
    requiredFiles: ['scripts/run-v3-gates.mjs', 'deploy/compose/compose.test.yaml'],
    commands: [[process.execPath, ['scripts/run-v3-gates.mjs', 'real-infrastructure']]],
  },
  'build-package': {
    description: 'Build the shared Web product plus the packaged Desktop and Windows installer.',
    requiredFiles: ['apps/web/vite.config.ts', 'apps/desktop/forge.config.ts'],
    environment: { WORKDUDE_ENABLE_SQUIRREL: 'true' },
    commands: [
      [process.execPath, [npmCli, 'run', 'build:web']],
      [process.execPath, [npmCli, 'run', 'make:desktop', '--', '--arch=x64']],
    ],
  },
  'gateway-runtime': {
    description: 'Run deterministic, integration, and real-response enterprise-gateway gates.',
    requiredFiles: [
      ...new Set([
        ...gates.gateway.requiredFiles,
        ...gates['gateway-integration'].requiredFiles,
        ...gates.response.requiredFiles.filter((path) => path !== desktopExecutable),
      ]),
    ],
    requiredEnvironment: [
      'APP_ACCESS_TOKEN',
      'DESKTOP_PLATFORM_ACCESS_TOKEN',
      'LITELLM_MODEL',
      'LITELLM_MASTER_KEY',
    ],
    commands: [gates.gateway.command, gates['gateway-integration'].command, ...gates.response.commands],
  },
  'web-functional': {
    description: 'Run the complete current Web functional and gateway-backed journey matrix.',
    requiredFiles: [...webFunctionalTests, '.env'],
    requiredEnvironment: ['APP_ACCESS_TOKEN', 'DESKTOP_PLATFORM_ACCESS_TOKEN', 'LITELLM_MODEL'],
    commands: [
      [
        process.execPath,
        ['--env-file=.env', 'scripts/run-playwright.mjs', ...webFunctionalTests, '--workers=1'],
      ],
    ],
  },
  'web-visual-accessibility': {
    description: 'Run current official visual, responsive, keyboard, scale, and accessibility gates.',
    requiredFiles: [
      ...webVisualAccessibilityTests,
      'tests/visual/v4/reference-states.ts',
      'scripts/run-v3-gates.mjs',
    ],
    environment: { VITE_ENABLE_AI_GATEWAY_VIRTUAL_KEY: 'false' },
    commands: [
      [process.execPath, ['scripts/run-v3-gates.mjs', 'visual']],
      [process.execPath, ['scripts/run-playwright.mjs', ...webVisualAccessibilityTests, '--workers=1']],
    ],
  },
  'installed-desktop': {
    description:
      'Run packaged Desktop smoke, lifecycle journeys, security, and the complete V3/V4 response matrix.',
    requiredFiles: [
      'scripts/smoke-desktop.mjs',
      'scripts/verify-desktop-journeys.mjs',
      'scripts/run-v3-gates.mjs',
      'tests/e2e/v3/resource-roundtrip.spec.ts',
      ...installedDesktopTests,
      '.env',
    ],
    requiredEnvironment: completeResponseEnvironment,
    environment: feishuResponseEnvironment,
    commands: [
      [process.execPath, ['scripts/smoke-desktop.mjs']],
      [process.execPath, ['scripts/verify-desktop-journeys.mjs']],
      [process.execPath, ['scripts/run-v3-gates.mjs', 'response-e2e']],
      [
        process.execPath,
        ['--env-file=.env', 'scripts/run-playwright.mjs', ...installedDesktopTests, '--workers=1'],
      ],
    ],
  },
  'windows-native-lifecycle': {
    description: 'Run the dedicated local Windows install, upgrade, restart, and uninstall lifecycle.',
    requiredFiles: [
      'scripts/verify-windows-standalone-window.mjs',
      'scripts/verify-desktop-v4-lifecycle.mjs',
    ],
    commands: [
      [process.execPath, ['scripts/verify-windows-standalone-window.mjs']],
      [process.execPath, ['scripts/verify-desktop-v4-lifecycle.mjs']],
    ],
  },
  'source-artifact': {
    description: 'Scan the final source, package, container, evidence, and Pi-derived Runtime artifacts.',
    requiredFiles: ['scripts/scan-v4-secrets.mjs'],
    commands: [
      [process.execPath, ['scripts/scan-v4-secrets.mjs', '--required-root', 'package=apps/desktop/out']],
    ],
  },
  'production-deploy': {
    description: 'Deploy the exact accepted revision and run the complete production smoke.',
    requiredFiles: ['deploy/server/v3-operations.sh', 'deploy/server/v4-smoke.ts'],
    requiredEnvironment: ['WORKDUDE_REPOSITORY_DIR', 'WORKDUDE_ENV_FILE'],
    commands: [['sh', ['deploy/server/v3-operations.sh', 'deploy', finalRevision]]],
  },
  'production-restart': {
    description: 'Restart the accepted production revision and repeat its readiness probe.',
    requiredFiles: ['deploy/server/v3-operations.sh'],
    requiredEnvironment: ['WORKDUDE_REPOSITORY_DIR', 'WORKDUDE_ENV_FILE'],
    commands: [['sh', ['deploy/server/v3-operations.sh', 'restart-probe']]],
  },
  'production-rollback': {
    description: 'Rehearse rollback, redeploy the accepted revision, and verify recovery.',
    requiredFiles: ['deploy/server/v3-operations.sh'],
    requiredEnvironment: [
      'WORKDUDE_REPOSITORY_DIR',
      'WORKDUDE_ENV_FILE',
      'WORKDUDE_ROLLBACK_BACKUP',
      'WORKDUDE_V4_ROLLBACK_REVISION',
    ],
    commands: [
      ['sh', ['deploy/server/v3-operations.sh', 'rollback', rollbackRevision]],
      ['sh', ['deploy/server/v3-operations.sh', 'deploy', finalRevision]],
    ],
  },
  'production-soak': {
    description: 'Run the checksummed resumable 24-hour soak for the accepted revision.',
    requiredFiles: ['deploy/server/v3-soak.sh'],
    requiredEnvironment: ['WORKDUDE_REPOSITORY_DIR', 'WORKDUDE_ENV_FILE'],
    environment: { WORKDUDE_TARGET_REVISION: finalRevision },
    commands: [['sh', ['deploy/server/v3-soak.sh']]],
  },
};

function missingFiles(gate) {
  return gate.requiredFiles.filter((relativePath) => {
    const absolutePath = resolve(root, relativePath);
    return !existsSync(absolutePath) || !statSync(absolutePath).isFile();
  });
}

function missingEnvironment(gate) {
  const environment = { ...process.env, ...(gate.environment ?? {}) };
  return (gate.requiredEnvironment ?? []).filter(
    (name) => typeof environment[name] !== 'string' || environment[name].trim().length === 0,
  );
}

function printStatus(id) {
  const missing = missingFiles(gates[id]);
  console.log(`[v4-gates] ${id}: ${missing.length === 0 ? 'READY' : 'BLOCKED'} - ${gates[id].description}`);
  if (missing.length > 0) console.log(`  missing: ${missing.join(', ')}`);
}

function runResponseTeardown(gate, prefix) {
  if (process.env.WORKDUDE_V4_RESPONSE_KEEP === '1') {
    console.log(
      `[${prefix}] response: keeping temporary Compose projects because WORKDUDE_V4_RESPONSE_KEEP=1`,
    );
    return 0;
  }
  const executable = process.execPath;
  const args = ['--env-file=.env', 'scripts/prepare-v4-response-environment.mjs', '--teardown'];
  console.log(`[${prefix}] response: ${executable} ${args.join(' ')}`);
  const result = spawnSync(executable, args, {
    cwd: root,
    env: receiptSafeChildEnvironment(gate.environment),
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  return result.status ?? 1;
}

function runResponseGate(gate, prefix) {
  let status = 0;
  try {
    const commands = gate.commands ?? [gate.command];
    for (const [executable, args] of commands) {
      console.log(`[${prefix}] response: ${executable} ${args.join(' ')}`);
      const result = spawnSync(executable, args, {
        cwd: root,
        env: receiptSafeChildEnvironment(gate.environment),
        stdio: 'inherit',
      });
      if (result.error) throw result.error;
      if (result.status !== 0) {
        status = result.status ?? 1;
        break;
      }
    }
  } finally {
    let cleanupStatus;
    try {
      cleanupStatus = runResponseTeardown(gate, prefix);
    } catch (error) {
      cleanupStatus = 1;
      console.error(`[${prefix}] response teardown failed`, error);
    }
    if (cleanupStatus !== 0) {
      console.error(`[${prefix}] response teardown exited with status ${cleanupStatus}`);
      if (status === 0) status = cleanupStatus;
    }
  }
  return status;
}

function runGate(id, gate = gates[id], prefix = 'v4-gates') {
  if (id === 'response') return runResponseGate(gate, prefix);
  const commands = gate.commands ?? [gate.command];
  if (id === 'gateway-runtime') {
    const responseCommands = gates.response.commands ?? [];
    const setupCommands = commands.slice(0, Math.max(0, commands.length - responseCommands.length));
    for (const [executable, args] of setupCommands) {
      console.log(`[${prefix}] ${id}: ${executable} ${args.join(' ')}`);
      const environment = receiptSafeChildEnvironment(gate.environment);
      const result = spawnSync(executable, args, {
        cwd: root,
        env: environment,
        stdio: 'inherit',
      });
      if (result.error) throw result.error;
      if (result.status !== 0) return result.status ?? 1;
    }
    return runResponseGate(gates.response, prefix);
  }
  for (const [executable, args] of commands) {
    console.log(`[${prefix}] ${id}: ${executable} ${args.join(' ')}`);
    const environment = receiptSafeChildEnvironment(gate.environment);
    const result = spawnSync(executable, args, {
      cwd: root,
      env: environment,
      stdio: 'inherit',
    });
    if (result.error) throw result.error;
    if (result.status !== 0) return result.status ?? 1;
  }
  return 0;
}

function receiptSafeChildEnvironment(additions = {}) {
  const environment = { ...process.env, ...additions };
  for (const name of receiptPrivateKeyEnvironmentNames) delete environment[name];
  return environment;
}

function gitOutput(args) {
  const result = spawnSync('git', args, {
    cwd: root,
    encoding: 'utf8',
    env: receiptSafeChildEnvironment(),
  });
  if (result.error) throw result.error;
  if (result.status !== 0) return { error: String(result.stderr || `git ${args.join(' ')} failed`) };
  return { output: String(result.stdout).trim() };
}

function revisionAuthorityProblems({ requireRollback = false } = {}) {
  const problems = [];
  if (!/^[0-9a-f]{40}$/u.test(finalRevision)) {
    problems.push('WORKDUDE_V4_FINAL_REVISION must be a lowercase 40-character Git SHA');
    return problems;
  }

  const head = gitOutput(['rev-parse', 'HEAD']);
  if (head.error) problems.push('current Git revision is unavailable');
  else if (head.output !== finalRevision) problems.push('WORKDUDE_V4_FINAL_REVISION does not match HEAD');

  const status = gitOutput(['status', '--porcelain', '--untracked-files=normal']);
  if (status.error) problems.push('current Git worktree state is unavailable');
  else if (status.output) problems.push('the final gate requires a clean tracked and untracked worktree');

  if (requireRollback || process.env.WORKDUDE_V4_ROLLBACK_REVISION) {
    if (!/^[0-9a-f]{40}$/u.test(rollbackRevision)) {
      problems.push('WORKDUDE_V4_ROLLBACK_REVISION must be a lowercase 40-character Git SHA');
    } else if (rollbackRevision === finalRevision) {
      problems.push('WORKDUDE_V4_ROLLBACK_REVISION must differ from WORKDUDE_V4_FINAL_REVISION');
    }
  }

  return problems;
}

function selectorManifestSha256(selectorId) {
  const scriptSha256 = createHash('sha256').update(readFileSync(scriptPath)).digest('hex');
  return createHash('sha256')
    .update(
      JSON.stringify({
        selectorId,
        gates: finalSelectorGateOrder[selectorId],
        scriptSha256,
      }),
    )
    .digest('hex');
}

function samePath(first, second) {
  return process.platform === 'win32' ? first.toLowerCase() === second.toLowerCase() : first === second;
}

function receiptPath(environmentName, { mustExist }) {
  const value = process.env[environmentName]?.trim() ?? '';
  if (!value || !isAbsolute(value)) {
    throw new Error(`${environmentName} must be an absolute receipt path`);
  }
  const target = resolve(value);
  const repositoryRelative = relative(root, target);
  if (!repositoryRelative.startsWith('..') && !isAbsolute(repositoryRelative)) {
    throw new Error(`${environmentName} must remain outside the repository`);
  }
  const parent = dirname(target);
  const canonicalParent = realpathSync(parent);
  if (!samePath(parent, canonicalParent)) {
    throw new Error(`${environmentName} parent must not traverse a link`);
  }
  if (mustExist) {
    const metadata = lstatSync(target, { bigint: true });
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1n) {
      throw new Error(`${environmentName} must be a plain single-link file`);
    }
    if (metadata.size > 65_536n) throw new Error(`${environmentName} is oversized`);
    if (!samePath(target, realpathSync(target))) {
      throw new Error(`${environmentName} must not traverse a link`);
    }
  } else if (existsSync(target)) {
    throw new Error(`${environmentName} already exists`);
  }
  return target;
}

function receiptPayload(selectorId, issuedAt = new Date().toISOString()) {
  const authority = receiptAuthorities[selectorId];
  return {
    schemaVersion: 1,
    kind: authority.kind,
    revision: finalRevision,
    rollbackRevision: selectorId === 'final-production' ? rollbackRevision : null,
    gates: [...finalSelectorGateOrder[selectorId]],
    manifestSha256: selectorManifestSha256(selectorId),
    platform: process.platform,
    arch: process.arch,
    issuedAt,
  };
}

function receiptPreflightProblems(selectorId) {
  const authority = receiptAuthorities[selectorId];
  try {
    receiptPath(authority.pathEnvironment, { mustExist: false });
    signGateReceipt({
      payload: receiptPayload(selectorId, '2000-01-01T00:00:00.000Z'),
      privateKeyBase64: process.env[authority.privateKeyEnvironment]?.trim() ?? '',
    });
    return [];
  } catch (error) {
    return [error instanceof Error ? error.message : `${authority.kind} gate receipt preflight failed`];
  }
}

function writeSignedReceipt(selectorId) {
  const authority = receiptAuthorities[selectorId];
  const path = receiptPath(authority.pathEnvironment, { mustExist: false });
  const privateKeyBase64 = process.env[authority.privateKeyEnvironment]?.trim() ?? '';
  const payload = receiptPayload(selectorId);
  const receipt = signGateReceipt({ payload, privateKeyBase64 });
  let descriptor;
  try {
    descriptor = openSync(path, 'wx', 0o600);
    writeFileSync(descriptor, `${JSON.stringify(receipt)}\n`, 'utf8');
    fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
  const metadata = lstatSync(path, { bigint: true });
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1n) {
    throw new Error('Published V4 gate receipt identity is invalid');
  }
  return receipt;
}

function readReceipt(selectorId) {
  const authority = receiptAuthorities[selectorId];
  const path = receiptPath(authority.pathEnvironment, { mustExist: true });
  return JSON.parse(readFileSync(path, 'utf8'));
}

function selectorRequiredEnvironment(selectorId) {
  const revision = ['WORKDUDE_V4_FINAL_REVISION'];
  const rollback = ['WORKDUDE_V4_ROLLBACK_REVISION'];
  if (receiptAuthorities[selectorId]) {
    const authority = receiptAuthorities[selectorId];
    return [
      ...revision,
      ...(selectorId === 'final-production' ? rollback : []),
      authority.pathEnvironment,
      authority.privateKeyEnvironment,
    ];
  }
  if (selectorId === 'final-native') return [...revision, 'WORKDUDE_V4_RELEASE_RUN_ID'];
  if (selectorId === 'final-authority') {
    return [
      ...revision,
      ...rollback,
      'WORKDUDE_V4_RELEASE_RUN_ID',
      ...Object.values(receiptAuthorities).flatMap(({ pathEnvironment, publicKeyEnvironment }) => [
        pathEnvironment,
        publicKeyEnvironment,
      ]),
    ];
  }
  return [];
}

function missingSelectorEnvironment(selectorId) {
  return selectorRequiredEnvironment(selectorId).filter(
    (name) => typeof process.env[name] !== 'string' || process.env[name].trim().length === 0,
  );
}

function selectorPlatformProblems(selectorId) {
  if (selectorId === 'final-windows' && (process.platform !== 'win32' || process.arch !== 'x64')) {
    return ['final-windows requires a native Windows x64 host'];
  }
  if (selectorId === 'final-production' && (process.platform !== 'linux' || process.arch !== 'x64')) {
    return ['final-production requires a native Linux x64 production authority host'];
  }
  return [];
}

function selectorGateBlockers(selectorId) {
  return (finalSelectorGateOrder[selectorId] ?? [])
    .map((id) => ({
      id,
      missing: missingFiles(finalGates[id]),
      environment: missingEnvironment(finalGates[id]),
    }))
    .filter(({ missing, environment }) => missing.length > 0 || environment.length > 0);
}

function selectorDescription(selectorId) {
  return {
    'final-prepush': 'Run host-neutral non-publishing gates for one frozen clean revision.',
    'final-windows': 'Build and exercise the installed Windows product for the same clean revision.',
    'final-native': 'Verify the successful tag-driven cross-platform GitHub Release workflow receipt.',
    'final-production': 'Deploy, restart, rollback/redeploy, and soak the same revision on production.',
    'final-authority':
      'Verify signed host receipts plus the successful native workflow without rerunning them.',
  }[selectorId];
}

function printFinalSelectorStatus(selectorId) {
  const blocked = selectorGateBlockers(selectorId);
  const environment = missingSelectorEnvironment(selectorId);
  const platform = selectorPlatformProblems(selectorId);
  const ready = blocked.length === 0 && environment.length === 0 && platform.length === 0;
  console.log(
    `[v4-final] ${selectorId}: ${ready ? 'READY' : 'BLOCKED'} - ${selectorDescription(selectorId)}`,
  );
  for (const problem of platform) console.log(`  platform: ${problem}`);
  for (const { id, missing, environment: gateEnvironment } of blocked) {
    if (missing.length > 0) console.log(`  ${id} missing files: ${missing.join(', ')}`);
    if (gateEnvironment.length > 0) {
      console.log(`  ${id} missing environment: ${gateEnvironment.join(', ')}`);
    }
  }
  if (environment.length > 0) console.log(`  missing environment: ${environment.join(', ')}`);
}

function failFinalPreflight(selectorId, problems, blocked) {
  console.error('[v4-final] preflight: BLOCKED');
  console.error(`  selector: ${selectorId}`);
  for (const problem of problems) console.error(`  authority: ${problem}`);
  for (const { id, missing, environment } of blocked) {
    if (missing.length > 0) console.error(`  ${id} missing files: ${missing.join(', ')}`);
    if (environment.length > 0) console.error(`  ${id} missing environment: ${environment.join(', ')}`);
  }
  console.error('[v4-final] No final gate ran. BLOCKED is never recorded as PASS.');
}

function runReceiptSelector(selectorId) {
  const requireRollback = selectorId === 'final-production';
  const problems = [
    ...revisionAuthorityProblems({ requireRollback }),
    ...selectorPlatformProblems(selectorId),
  ];
  const missing = missingSelectorEnvironment(selectorId);
  if (missing.length > 0) problems.push(`missing environment: ${missing.join(', ')}`);
  else problems.push(...receiptPreflightProblems(selectorId));
  const blocked = selectorGateBlockers(selectorId);
  if (problems.length > 0 || blocked.length > 0) {
    failFinalPreflight(selectorId, problems, blocked);
    return 2;
  }
  for (const id of finalSelectorGateOrder[selectorId]) {
    const status = runGate(id, finalGates[id], selectorId);
    if (status !== 0) return status;
    console.log(`[v4-final] ${id}: PASS for exact revision ${finalRevision}.`);
  }
  const postGateProblems = revisionAuthorityProblems({ requireRollback });
  if (postGateProblems.length > 0) {
    failFinalPreflight(selectorId, postGateProblems, []);
    return 2;
  }
  writeSignedReceipt(selectorId);
  console.log(`[v4-final] ${selectorId}: PASS; signed same-SHA receipt published.`);
  return 0;
}

function verifyFinalReceipts() {
  const problems = [];
  const publicKeys = Object.values(receiptAuthorities).map(
    ({ publicKeyEnvironment }) => process.env[publicKeyEnvironment]?.trim() ?? '',
  );
  if (new Set(publicKeys).size !== publicKeys.length) {
    problems.push('V4 gate receipt public keys must be distinct per authority');
  }
  for (const selectorId of ['final-prepush', 'final-windows', 'final-production']) {
    const authority = receiptAuthorities[selectorId];
    try {
      problems.push(
        ...verifyGateReceipt({
          receipt: readReceipt(selectorId),
          expected: {
            kind: authority.kind,
            revision: finalRevision,
            rollbackRevision: selectorId === 'final-production' ? rollbackRevision : null,
            gates: [...finalSelectorGateOrder[selectorId]],
            manifestSha256: selectorManifestSha256(selectorId),
            ...(selectorId === 'final-windows' ? { platform: 'win32', arch: 'x64' } : {}),
            ...(selectorId === 'final-production' ? { platform: 'linux', arch: 'x64' } : {}),
          },
          publicKeyBase64: process.env[authority.publicKeyEnvironment]?.trim() ?? '',
        }),
      );
    } catch {
      problems.push(`${authority.kind} gate receipt is unavailable`);
    }
  }
  return problems;
}

const selector = process.argv[2] ?? '--list';

if (selector === '--list') {
  for (const id of gateOrder) printStatus(id);
  console.log('[v4-gates] READY means prerequisites exist; it is not acceptance evidence.');
  process.exit(0);
}

if (selector === '--list-final') {
  for (const id of finalSelectorOrder) printFinalSelectorStatus(id);
  console.log('[v4-final] READY means prerequisites exist; it is not acceptance evidence.');
  process.exit(0);
}

if (receiptAuthorities[selector]) {
  process.exit(runReceiptSelector(selector));
}

if (selector === 'final-native') {
  const problems = revisionAuthorityProblems();
  const missing = missingSelectorEnvironment(selector);
  if (missing.length > 0) problems.push(`missing environment: ${missing.join(', ')}`);
  if (problems.length === 0) {
    problems.push(
      ...inspectGitHubReleaseRun({
        runId: process.env.WORKDUDE_V4_RELEASE_RUN_ID,
        expectedRevision: finalRevision,
        cwd: root,
      }),
    );
  }
  if (problems.length > 0) {
    failFinalPreflight(selector, problems, []);
    process.exit(2);
  }
  console.log(`[v4-final] ${selector}: PASS for exact revision ${finalRevision}.`);
  process.exit(0);
}

if (selector === 'final-authority' || selector === 'final') {
  const problems = revisionAuthorityProblems({ requireRollback: true });
  const missing = missingSelectorEnvironment('final-authority');
  if (missing.length > 0) problems.push(`missing environment: ${missing.join(', ')}`);
  if (problems.length === 0) {
    problems.push(
      ...inspectGitHubReleaseRun({
        runId: process.env.WORKDUDE_V4_RELEASE_RUN_ID,
        expectedRevision: finalRevision,
        cwd: root,
      }),
      ...verifyFinalReceipts(),
    );
  }
  if (problems.length > 0) {
    failFinalPreflight('final-authority', problems, []);
    process.exit(2);
  }
  console.log(
    `[v4-final] final-authority: PASS; all signed host and GitHub receipts bind exact revision ${finalRevision}.`,
  );
  process.exit(0);
}

const selected = selector === 'all' ? gateOrder : [selector];
const unknown = selected.filter((id) => !gates[id]);
if (unknown.length > 0) {
  console.error(`[v4-gates] Unknown gate: ${unknown.join(', ')}`);
  console.error(
    `[v4-gates] Expected one of: all, ${finalSelectorOrder.join(', ')}, final, ${gateOrder.join(', ')}, --list, --list-final`,
  );
  process.exit(2);
}

const blocked = selected
  .map((id) => ({ id, missing: missingFiles(gates[id]) }))
  .filter(({ missing }) => missing.length > 0);
if (blocked.length > 0) {
  for (const { id, missing } of blocked) {
    console.error(`[v4-gates] ${id}: BLOCKED; missing ${missing.join(', ')}`);
  }
  console.error('[v4-gates] No selected gate ran. BLOCKED is never recorded as PASS.');
  process.exit(2);
}

for (const id of selected) {
  const status = runGate(id);
  if (status !== 0) process.exit(status);
  console.log(`[v4-gates] ${id}: PASS for the current working tree; clean-SHA evidence is separate.`);
}
