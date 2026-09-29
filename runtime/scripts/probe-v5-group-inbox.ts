import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

import { loadV4ServerConfiguration } from '../packages/product-contracts/src/server-configuration.ts';
import { createEnterpriseAiGatewayAuthorizationState } from '../packages/agent-runtime/src/enterprise-ai-gateway.ts';
import { runFailureDetail } from '../packages/agent-runtime/src/run-failure.ts';
import { PostgresExecutionRepository } from '../packages/data-access/src/v3/execution-repository.ts';
import {
  PostgresWakerRepository,
  type V3PostgresPool,
} from '../packages/data-access/src/v3/waker-repository.ts';
import { PostgresGroupRepository } from '../packages/data-access/src/v3/group-repository.ts';
import { PostgresWakerConfigurationRepository } from '../packages/data-access/src/v3/waker-configuration-repository.ts';
import { PostgresPermissionPolicyRepository } from '../packages/data-access/src/v3/permission-policy-repository.ts';
import type { V3MutationContext, V3RequestContext } from '../packages/product-contracts/src/v3-ports.ts';
import { createV3RunProcessor } from '../services/cloud-worker/src/v3-run-worker.ts';
import { startNativePostgresTestDatabase } from '../tests/fixtures/native-postgres.ts';

const probeId = randomUUID();
const root = join(process.cwd(), '.tmp', `v5-live-inbox-${probeId}`);
await mkdir(root, { recursive: true });
const reportPath = join(root, 'report.json');
const dataDir = join(root, 'runtime');
const configuration = loadV4ServerConfiguration(process.env).aiGateway;
assert.equal(new URL(configuration.baseUrl).protocol, 'https:', 'The live model probe requires HTTPS');
const authorization = createEnterpriseAiGatewayAuthorizationState(configuration);
const catalog = await authorization.refreshSnapshot();
const database = await startNativePostgresTestDatabase();
const pool = database.pool as unknown as V3PostgresPool;
const execution = new PostgresExecutionRepository(pool);
const wakers = new PostgresWakerRepository(pool);
const groups = new PostgresGroupRepository(pool);
const context: V3RequestContext = {
  correlationId: `live-inbox-${probeId}`,
  principal: {
    userId: randomUUID(),
    workspaceId: randomUUID(),
    displayName: 'V5 live Inbox probe',
    role: 'owner',
    permissions: ['*'],
  },
};
const mutation = (key: string): V3MutationContext => ({
  ...context,
  idempotency: { key, requestHash: createHash('sha256').update(key).digest('hex') },
});
const running = new Map<string, Promise<void>>();
const notificationCounts: Record<string, number> = {};
let closing = false;
let timeout: ReturnType<typeof setTimeout> | undefined;
let conversationId: string | undefined;
let failed: string | undefined;
const markers = { handoff: `GW-INBOX-HANDOFF-${probeId}`, done: `GW-INBOX-DONE-${probeId}` };
const report: Record<string, unknown> = {
  probeId,
  startedAt: new Date().toISOString(),
  gatewayOrigin: new URL(configuration.baseUrl).origin,
  model: configuration.model,
  boundaries: {
    database: 'isolated local native PostgreSQL',
    runtime: 'production Cloud processor and Pi',
    model: 'real HTTPS gateway',
    notifications: 'local collector',
  },
  releaseAuthority: false,
};

try {
  await database.pool.query('INSERT INTO users (id,display_name) VALUES ($1,$2)', [
    context.principal.userId,
    context.principal.displayName,
  ]);
  await database.pool.query('INSERT INTO workspaces (id,name) VALUES ($1,$2)', [
    context.principal.workspaceId,
    'V5 isolated gateway probe',
  ]);
  await database.pool.query(
    "INSERT INTO workspace_memberships (workspace_id,user_id,role) VALUES ($1,$2,'owner')",
    [context.principal.workspaceId, context.principal.userId],
  );
  const members: Array<Awaited<ReturnType<PostgresWakerRepository['create']>>> = [];
  for (const name of ['qd', 'hd'])
    members.push(
      await wakers.create(mutation(name), {
        name,
        roleName: name === 'qd' ? 'Coordinator' : 'Engineer',
        bio: '仅在当前群对话中处理明确交给自己的文字验证工作，不操作文件或外部服务。',
        environment: 'cloud',
      }),
    );
  const group = await groups.create(
    mutation('group'),
    {
      name: 'V5 HTTPS Inbox protocol probe',
      mission: '',
      leaderWakerId: members[0]!.id,
      memberWakerIds: members.map(({ id }) => id),
      memberConfigurations: members.map(({ id }) => ({
        wakerId: id,
        model: configuration.model,
        workspaceReferenceId: null,
      })),
    },
    catalog,
  );
  const conversation = await execution.create(mutation('conversation'), {
    subjectType: 'group',
    subjectId: group.id,
    title: 'Live directed Inbox handoff',
  });
  conversationId = conversation.id;
  const processRun = createV3RunProcessor({
    repository: execution,
    configurations: new PostgresWakerConfigurationRepository(pool),
    policies: new PostgresPermissionPolicyRepository(pool),
    groups,
    dataDir,
    aiGateway: configuration,
    refreshAiGatewaySnapshot: () => authorization.refreshSnapshot(),
    redis: {
      async publish(_channel, value) {
        const event = JSON.parse(String(value)) as { type: string; runId: string };
        notificationCounts[event.type] = (notificationCounts[event.type] ?? 0) + 1;
        if (['group.message.sent', 'run.completed', 'run.failed'].includes(event.type))
          process.stdout.write(`${JSON.stringify({ event: event.type, runId: event.runId })}\n`);
        return 1;
      },
    },
    async onQueueTransition({ transition }) {
      if (closing) return;
      for (const runId of transition?.dispatchRunIds ?? []) dispatch(runId);
    },
  });
  function dispatch(runId: string) {
    if (running.has(runId)) return;
    if (running.size >= 6) throw new Error('The protocol probe exceeded six participant Runs');
    const pending = processRun({
      runId,
      workspaceId: context.principal.workspaceId,
      userId: context.principal.userId,
      correlationId: context.correlationId,
      dispatchKey: 'initial',
    });
    void pending.catch(() => undefined);
    running.set(runId, pending);
  }
  const accepted = await execution.createMessageRun(
    mutation('prompt'),
    conversation.id,
    {
      content: `请完成一次群内文字协作验证，保持群名和会话标题不变。先由 qd 用 --mention hd 发送正文包含 @hd 的群消息，委托 hd 回复。hd 的回复正文应包含 @qd 和 ${markers.handoff}，同时用 --mention qd 把真实回复交回。qd 必须收到 hd 的真实消息后，再向群里回复 ${markers.done}，不再唤醒其他成员。每位成员只完成自己的步骤，不模拟另一位成员，不读写文件，不访问外部业务服务。按当前 Inbox 协议处理和精确已读，并 fresh claim 至空。`,
    },
    { model: configuration.model, executionTarget: 'cloud', authorizeModel: catalog.assertAuthorized },
  );
  dispatch(accepted.run.id);
  await Promise.race([
    (async () => {
      for (let index = 0; index < running.size; index += 1) await [...running.values()][index];
    })(),
    new Promise<never>((_resolve, reject) => {
      timeout = setTimeout(() => reject(new Error('Live Inbox probe exceeded 180 seconds')), 180_000);
    }),
  ]);
  const events = (await execution.listEvents(context, conversation.id, 0, 1000)).events;
  const messages = events.filter(({ type }) => type === 'assistant.message');
  const hdReply = messages.find(
    ({ payload }) =>
      payload.participantWakerId === members[1]!.id && String(payload.content).includes(markers.handoff),
  );
  const qdFinal = messages.find(
    ({ payload }) =>
      payload.participantWakerId === members[0]!.id &&
      String(payload.content).includes(markers.done) &&
      Array.isArray(payload.mentionedParticipantIds) &&
      payload.mentionedParticipantIds.length === 0,
  );
  assert.ok(hdReply, 'No committed reply from hd');
  assert.ok(
    String(hdReply.payload.content).includes('@qd'),
    'The return message does not name its actual routing target',
  );
  assert.ok(qdFinal && qdFinal.sequence > hdReply.sequence, 'No qd conclusion after the real hd reply');
  for (const runId of running.keys())
    assert.equal(
      (await execution.getRun(context, runId))?.status,
      'completed',
      `Run ${runId} did not finish its Inbox`,
    );
  report.status = 'passed';
} catch (cause) {
  failed = runFailureDetail(cause);
  report.status = 'failed';
  report.detail = failed;
  process.exitCode = 1;
} finally {
  closing = true;
  if (timeout) clearTimeout(timeout);
  for (const runId of running.keys()) {
    const run = await execution.getRun(context, runId);
    if (run && !['completed', 'failed', 'cancelled'].includes(run.status))
      await execution.cancelRun(mutation('stop-' + runId), runId);
  }
  await Promise.allSettled(running.values());
  report.finishedAt = new Date().toISOString();
  report.notifications = notificationCounts;
  report.runs = await Promise.all([...running.keys()].map((id) => execution.getRun(context, id)));
  report.runEvents = await Promise.all(
    [...running.keys()].map(async (runId) => ({
      runId,
      events: (await execution.listRunEvents(context, runId, 0)).map(({ type, sequence, payload }) => ({
        sequence,
        type,
        payload: {
          ...(typeof payload.toolName === 'string' ? { toolName: payload.toolName } : {}),
          ...(typeof payload.toolCallId === 'string' ? { toolCallId: payload.toolCallId } : {}),
          ...(typeof payload.claimId === 'string' ? { claimId: payload.claimId } : {}),
          ...(typeof payload.fingerprint === 'string' ? { fingerprint: payload.fingerprint } : {}),
          ...(typeof payload.delta === 'string' ? { deltaLength: payload.delta.length } : {}),
          ...(typeof payload.text === 'string' ? { textLength: payload.text.length } : {}),
          ...(payload.args &&
          typeof payload.args === 'object' &&
          typeof (payload.args as Record<string, unknown>).command === 'string'
            ? (() => {
                const command = (payload.args as Record<string, unknown>).command as string;
                return {
                  command:
                    command.match(/^\s*qoderwake\s+messages\s+(send|claim|read|list)\b/u)?.[1] ?? 'other',
                  hasMention: /\s--mention\s/u.test(command),
                  commandLength: command.length,
                };
              })()
            : {}),
          ...(payload.result && typeof payload.result === 'object'
            ? { resultKeys: Object.keys(payload.result as Record<string, unknown>) }
            : {}),
        },
      })),
    })),
  );
  if (conversationId)
    report.messages = (await execution.listEvents(context, conversationId, 0, 1000)).events
      .filter(({ type }) => ['user.message', 'assistant.message'].includes(type))
      .map(({ id, sequence, type, payload }) => ({
        id,
        sequence,
        type,
        content: payload.content,
        wakerId: payload.participantWakerId,
        mentionedParticipantIds: payload.mentionedParticipantIds,
      }));
  report.claims = (
    await database.pool.query(
      'SELECT run_id,ordinal,state,jsonb_array_length(snapshot_ids) AS candidates,jsonb_array_length(returned_ids) AS returned FROM group_inbox_claims ORDER BY created_at,ordinal',
    )
  ).rows;
  await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
  await database.close();
  await rm(dataDir, { recursive: true, force: true });
  process.stdout.write(
    `${JSON.stringify({ status: report.status, reportPath, ...(failed ? { detail: failed } : {}) })}\n`,
  );
}
