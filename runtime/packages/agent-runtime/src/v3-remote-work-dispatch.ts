import { Value } from 'typebox/value';

import {
  buildV3EffectiveSystemPrompt,
  resolveV3EffectiveConfiguration,
} from './v3-effective-configuration.ts';
import { withV3ResponseLanguage } from './v3-response-language.ts';
import type {
  PostgresRemoteWorkRepository,
  V3RemoteConversationDispatch,
} from '../../data-access/src/v3/remote-work-repository.ts';
import type {
  V3RequestContext,
  V3WakerConfigurationRepository,
} from '../../product-contracts/src/v3-ports.ts';
import {
  V3RemoteConversationRunWorkDataSchema,
  V3RemoteConversationSnapshotSchema,
  type V3Conversation,
  type V3Run,
  type V3SendMessage,
  type V3Task,
} from '../../product-contracts/src/v3.ts';

interface V3RemoteDispatchRunWork {
  run: Pick<
    V3Run,
    'id' | 'taskId' | 'executionTarget' | 'effectiveConfigurationVersionId' | 'model' | 'status'
  >;
  conversationId: string;
  prompt: string;
  attachmentIds: string[];
  responseLanguage?: V3SendMessage['responseLanguage'];
  deviceId: string | null;
  triggerMessageIds: string[];
}

export interface V3RemoteWorkDispatchOptions {
  execution: {
    getRunWorkItem(context: V3RequestContext, runId: string): Promise<V3RemoteDispatchRunWork | undefined>;
    getTask(
      context: V3RequestContext,
      taskId: string,
    ): Promise<Pick<V3Task, 'type' | 'assigneeWakerId'> | undefined>;
    get(
      context: V3RequestContext,
      conversationId: string,
    ): Promise<Pick<V3Conversation, 'id' | 'subjectType' | 'title'> | undefined>;
  };
  wakers: {
    get(
      context: V3RequestContext,
      wakerId: string,
    ): Promise<{ id: string; environment: 'local' | 'cloud'; deviceId?: string | null } | undefined>;
  };
  configurations: V3WakerConfigurationRepository;
  remoteWork: Pick<PostgresRemoteWorkRepository, 'enqueueConversationRun'>;
}

export async function dispatchV3LocalConversationRun(
  options: V3RemoteWorkDispatchOptions,
  context: V3RequestContext,
  runId: string,
  dispatchKey: string,
): Promise<string> {
  const work = await options.execution.getRunWorkItem(context, runId);
  if (!work || work.run.id !== runId) throw new Error(`Remote conversation Run not found: ${runId}`);
  if (work.run.executionTarget !== 'local') {
    throw new Error(`Remote conversation Run is not local: ${runId}`);
  }
  if (!work.triggerMessageIds.length) {
    throw new Error('Remote conversation trigger message is unavailable');
  }
  const task = await options.execution.getTask(context, work.run.taskId);
  if (!task || !task.assigneeWakerId) {
    throw new Error('Remote conversation requires an assigned Waker task');
  }
  const conversation = await options.execution.get(context, work.conversationId);
  if (
    !conversation ||
    conversation.id !== work.conversationId ||
    !(conversation.subjectType === 'waker'
      ? task.type === 'individual'
      : conversation.subjectType === 'group' && ['group_leader', 'group_child'].includes(task.type))
  ) {
    throw new Error('Remote conversation task binding is invalid');
  }
  const waker = await options.wakers.get(context, task.assigneeWakerId);
  if (!waker || !work.deviceId) throw new Error('Remote conversation machine binding is unavailable');
  const configurationVersionId = work.run.effectiveConfigurationVersionId;
  if (!configurationVersionId) throw new Error('Remote conversation has no effective Waker configuration');
  const resolved = await resolveV3EffectiveConfiguration(
    options.configurations,
    context,
    configurationVersionId,
  );
  if (resolved.configuration.wakerId !== waker.id) {
    throw new Error('Remote conversation Waker configuration binding is invalid');
  }
  const profile = resolved.configuration.effectiveSnapshot.profile;
  const systemPrompt = withV3ResponseLanguage(buildV3EffectiveSystemPrompt(resolved), work.responseLanguage);
  const data: V3RemoteConversationDispatch['data'] = {
    type: 'conversation_run',
    run_id: runId,
    conversation_id: conversation.id,
    participant_id: waker.id,
    waker_ref: { kind: 'waker', id: waker.id },
    waker_snapshot: {
      name: profile.name,
      role_name: profile.roleName,
      bio: profile.bio,
      system_prompt: systemPrompt,
    },
    employee_id: waker.id,
    config_revision: resolved.configuration.id,
    trigger_message_ids: work.triggerMessageIds,
    resolved_model: work.run.model,
  };
  const snapshot: V3RemoteConversationDispatch['snapshot'] = {
    conversation: {
      id: conversation.id,
      kind: conversation.subjectType === 'group' ? 'group_conversation' : 'direct_conversation',
      title: conversation.title,
    },
    execution: {
      prompt: work.prompt,
      system_prompt: systemPrompt,
      model: work.run.model,
      ...(work.responseLanguage ? { response_language: work.responseLanguage } : {}),
    },
  };
  if (
    !Value.Check(V3RemoteConversationRunWorkDataSchema, {
      ...data,
      epoch: 1,
      lease_token: 'a'.repeat(43),
      run_credential: 'b'.repeat(43),
    })
  ) {
    throw new Error('Remote conversation Work payload is invalid');
  }
  if (!Value.Check(V3RemoteConversationSnapshotSchema, snapshot)) {
    throw new Error('Remote conversation snapshot is invalid');
  }
  return options.remoteWork.enqueueConversationRun(context, {
    machineId: work.deviceId,
    runId,
    dispatchKey,
    data,
    snapshot,
  });
}
