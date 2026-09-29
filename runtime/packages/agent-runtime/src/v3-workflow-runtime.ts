import type {
  V3WorkflowInputField,
  V3WorkflowNode,
  V3WorkflowRunEvent,
} from '../../product-contracts/src/v3.ts';
import { runFailureDetail } from './run-failure.ts';

export interface V3WorkflowDefinition {
  startNodeId: string;
  inputSchema: V3WorkflowInputField[];
  nodes: V3WorkflowNode[];
}

export interface V3WorkflowExecutionState {
  completedNodeIds: string[];
  outputs: Record<string, unknown>;
  responses: Record<string, unknown>;
  pendingNodeId: string | null;
  skippedInputNodeIds?: string[];
}

export interface V3WorkflowExecutionAdapters {
  replayInput?(nodeId: string): Promise<{ response: unknown; sourceRunId: string } | undefined>;
  runWorker(input: {
    node: Extract<V3WorkflowNode, { type: 'worker' }>;
    instruction: string;
    executionKey: string;
  }): Promise<unknown>;
  runPipelineItem(input: {
    node: Extract<V3WorkflowNode, { type: 'pipeline' }>;
    item: unknown;
    index: number;
    instruction: string;
    executionKey: string;
  }): Promise<unknown>;
  runAction(input: {
    node: Extract<V3WorkflowNode, { type: 'action' }>;
    args: unknown;
    target: string;
    executionKey: string;
  }): Promise<unknown>;
  runSubflow(input: {
    node: Extract<V3WorkflowNode, { type: 'subflow' }>;
    value: Record<string, unknown>;
    executionKey: string;
  }): Promise<unknown>;
  emit(
    type: V3WorkflowRunEvent['type'],
    nodeId: string | null,
    payload: Record<string, unknown>,
  ): Promise<void>;
}

export interface V3WorkflowExecutionResult {
  status: 'completed' | 'awaiting_input' | 'failed';
  state: V3WorkflowExecutionState;
  output: unknown;
  failure: string | null;
}

export class V3WorkflowInputError extends Error {
  constructor(readonly fieldErrors: Record<string, string>) {
    super('Workflow input failed validation.');
    this.name = 'V3WorkflowInputError';
  }
}

function typeMatches(type: V3WorkflowInputField['type'], value: unknown): boolean {
  if (type === 'array') return Array.isArray(value);
  if (type === 'object') return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
  return typeof value === type;
}

export function prepareV3WorkflowArgs(
  inputSchema: readonly V3WorkflowInputField[],
  args: Record<string, unknown>,
): Record<string, unknown> {
  const normalized: Record<string, unknown> = {};
  const fieldErrors: Record<string, string> = {};
  const declared = new Set(inputSchema.map(({ key }) => key));
  for (const key of Object.keys(args)) {
    if (!declared.has(key)) fieldErrors[key] = '未声明的运行参数。';
  }
  for (const field of inputSchema) {
    const supplied = Object.hasOwn(args, field.key);
    const value = supplied ? args[field.key] : field.defaultValue;
    if (value === undefined) {
      if (field.required) fieldErrors[field.key] = '此字段为必填项。';
      continue;
    }
    if (!typeMatches(field.type, value)) {
      fieldErrors[field.key] = `必须是 ${field.type} 类型。`;
      continue;
    }
    normalized[field.key] = value;
  }
  if (Object.keys(fieldErrors).length) throw new V3WorkflowInputError(fieldErrors);
  return normalized;
}

export function validateV3WorkflowDefinition(definition: V3WorkflowDefinition): string[] {
  const errors = new Set<string>();
  const byId = new Map<string, V3WorkflowNode>();
  for (const node of definition.nodes) {
    if (byId.has(node.id)) errors.add(`节点 ID 重复：${node.id}`);
    byId.set(node.id, node);
  }
  if (!byId.has(definition.startNodeId)) errors.add('起始节点不存在。');
  for (const node of definition.nodes) {
    for (const next of node.next) {
      if (!byId.has(next)) errors.add(`节点 ${node.id} 指向不存在的节点 ${next}。`);
    }
    if (node.type === 'return' && node.next.length) errors.add(`返回节点 ${node.id} 不能有后继节点。`);
    if (node.type === 'parallel' && node.next.length < 2) {
      errors.add(`并行节点 ${node.id} 至少需要两个分支。`);
    }
    if (node.type === 'ask_user' && node.next.length !== 1) {
      errors.add(`人工确认节点 ${node.id} 必须有且只有一个后继节点。`);
    }
  }
  const returns = definition.nodes.filter((node) => node.type === 'return');
  if (returns.length > 1) errors.add('工作流最多只能有一个返回节点。');

  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (nodeId: string): void => {
    if (visiting.has(nodeId)) {
      errors.add('工作流不能包含循环依赖。');
      return;
    }
    if (visited.has(nodeId)) return;
    const node = byId.get(nodeId);
    if (!node) return;
    visiting.add(nodeId);
    node.next.forEach(visit);
    visiting.delete(nodeId);
    visited.add(nodeId);
  };
  visit(definition.startNodeId);
  for (const node of definition.nodes) {
    if (!visited.has(node.id)) errors.add(`节点 ${node.id} 无法从起始节点到达。`);
  }

  const predecessors = predecessorMap(definition.nodes);
  for (const node of definition.nodes) {
    if (node.type === 'join' && (predecessors.get(node.id)?.size ?? 0) < 2) {
      errors.add(`汇合节点 ${node.id} 至少需要两个前置分支。`);
    }
  }
  if (returns.length === 1) {
    const canReachReturn = new Set<string>();
    const stack = [returns[0]!.id];
    while (stack.length) {
      const current = stack.pop()!;
      if (canReachReturn.has(current)) continue;
      canReachReturn.add(current);
      stack.push(...(predecessors.get(current) ?? []));
    }
    for (const node of definition.nodes) {
      if (!canReachReturn.has(node.id)) errors.add(`节点 ${node.id} 无法到达返回节点。`);
    }
  }
  return [...errors];
}

function predecessorMap(nodes: readonly V3WorkflowNode[]): Map<string, Set<string>> {
  const predecessors = new Map(nodes.map((node) => [node.id, new Set<string>()]));
  for (const node of nodes) {
    for (const next of node.next) predecessors.get(next)?.add(node.id);
  }
  return predecessors;
}

function safePath(root: Record<string, unknown>, path: string): unknown {
  let current: unknown = root;
  for (const segment of path.split('.')) {
    if (segment === '__proto__' || segment === 'prototype' || segment === 'constructor') return undefined;
    if (!current || typeof current !== 'object' || !Object.hasOwn(current, segment)) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function resolveTemplate(value: unknown, context: Record<string, unknown>): unknown {
  if (typeof value === 'string') {
    const exact = /^\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}$/u.exec(value);
    if (exact) return safePath(context, exact[1]!);
    return value.replaceAll(/\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/gu, (_, path: string) => {
      const resolved = safePath(context, path);
      return resolved === undefined ? '' : typeof resolved === 'string' ? resolved : JSON.stringify(resolved);
    });
  }
  if (Array.isArray(value)) return value.map((item) => resolveTemplate(item, context));
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        resolveTemplate(item, context),
      ]),
    );
  }
  return value;
}

async function mapLimit<T, R>(
  values: readonly T[],
  concurrency: number,
  operation: (value: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(values.length);
  let cursor = 0;
  const workers = Array.from({ length: Math.min(concurrency, values.length) }, async () => {
    while (cursor < values.length) {
      const index = cursor++;
      results[index] = await operation(values[index]!, index);
    }
  });
  await Promise.all(workers);
  return results;
}

function cloneState(state?: Partial<V3WorkflowExecutionState>): V3WorkflowExecutionState {
  return {
    completedNodeIds: [...(state?.completedNodeIds ?? [])],
    outputs: { ...(state?.outputs ?? {}) },
    responses: { ...(state?.responses ?? {}) },
    pendingNodeId: state?.pendingNodeId ?? null,
    ...(state?.skippedInputNodeIds ? { skippedInputNodeIds: [...state.skippedInputNodeIds] } : {}),
  };
}

export async function executeV3Workflow(
  runId: string,
  definition: V3WorkflowDefinition,
  args: Record<string, unknown>,
  adapters: V3WorkflowExecutionAdapters,
  priorState?: Partial<V3WorkflowExecutionState>,
): Promise<V3WorkflowExecutionResult> {
  const definitionErrors = validateV3WorkflowDefinition(definition);
  if (definitionErrors.length) throw new Error(`Invalid workflow: ${definitionErrors.join(' ')}`);
  const normalizedArgs = prepareV3WorkflowArgs(definition.inputSchema, args);
  const state = cloneState(priorState);
  const byId = new Map(definition.nodes.map((node) => [node.id, node]));
  const predecessors = predecessorMap(definition.nodes);
  const completed = new Set(state.completedNodeIds);
  const context = () => ({ args: normalizedArgs, results: state.outputs, responses: state.responses });

  if (state.pendingNodeId) {
    const pending = byId.get(state.pendingNodeId);
    if (!pending || pending.type !== 'ask_user')
      throw new Error('Persisted pending workflow node is invalid.');
    if (!Object.hasOwn(state.responses, pending.responseKey)) {
      return { status: 'awaiting_input', state, output: null, failure: null };
    }
    await adapters.emit('input.resolved', pending.id, {
      responseKey: pending.responseKey,
      response: state.responses[pending.responseKey],
      ...(state.skippedInputNodeIds?.includes(pending.id) ? { skipped: true } : {}),
    });
    completed.add(pending.id);
    state.completedNodeIds = [...completed];
    state.pendingNodeId = null;
    await adapters.emit('node.completed', pending.id, { output: state.responses[pending.responseKey] });
  }

  while (completed.size < definition.nodes.length) {
    const ready = definition.nodes.filter(
      (node) =>
        !completed.has(node.id) &&
        [...(predecessors.get(node.id) ?? [])].every((predecessor) => completed.has(predecessor)),
    );
    if (!ready.length) throw new Error('Workflow execution reached an invalid persisted state.');
    const pendingInput = ready.find((node) => node.type === 'ask_user');
    const executable = ready.filter((node) => node.type !== 'ask_user');

    try {
      await Promise.all(
        executable.map(async (node) => {
          await adapters.emit('node.started', node.id, { nodeType: node.type, name: node.name });
          const executionKey = `${runId}:${node.id}`;
          let output: unknown = null;
          if (node.type === 'worker') {
            output = await adapters.runWorker({
              node,
              instruction: String(resolveTemplate(node.instruction, context()) ?? ''),
              executionKey,
            });
          } else if (node.type === 'pipeline') {
            const items = resolveTemplate(node.itemsExpression, context());
            if (!Array.isArray(items))
              throw new Error(`Pipeline ${node.id} itemsExpression did not resolve to an array.`);
            output = await mapLimit(items, node.concurrency, async (item, index) => {
              const instruction = String(
                resolveTemplate(node.instruction, { ...context(), item, index }) ?? '',
              );
              await adapters.emit('pipeline.item.started', node.id, { index, instruction });
              let result: unknown;
              try {
                result = await adapters.runPipelineItem({
                  node,
                  item,
                  index,
                  instruction,
                  executionKey: `${executionKey}:${index}`,
                });
              } catch (error) {
                // Official pipelines settle failed items as null and continue.
                // Persistence/ownership errors from emit must still escape.
                await adapters.emit('pipeline.item.failed', node.id, {
                  index,
                  failure: runFailureDetail(error),
                });
                return null;
              }
              await adapters.emit('pipeline.item.completed', node.id, { index, output: result });
              return result;
            });
          } else if (node.type === 'action') {
            const target = String(
              resolveTemplate(
                node.actionType === 'http'
                  ? node.url
                  : node.actionType === 'script'
                    ? node.command
                    : node.actionId,
                context(),
              ) ?? '',
            );
            const startedAt = Date.now();
            await adapters.emit('action.dispatched', node.id, {
              actionId: node.actionId,
              label: node.name,
              type: node.actionType,
              target,
            });
            try {
              output = await adapters.runAction({
                node,
                args: resolveTemplate(node.args, context()),
                target,
                executionKey,
              });
              await adapters.emit('action.completed', node.id, {
                durationMs: Date.now() - startedAt,
              });
            } catch (error) {
              const message = runFailureDetail(error);
              await adapters.emit('action.failed', node.id, {
                error: { code: 'ACTION_FAILED', message },
              });
              throw error;
            }
          } else if (node.type === 'subflow') {
            output = await adapters.runSubflow({
              node,
              value: resolveTemplate(node.input, context()) as Record<string, unknown>,
              executionKey,
            });
          } else if (node.type === 'log') {
            const message = String(resolveTemplate(node.message, context()) ?? '');
            await adapters.emit('log', node.id, { level: node.level, message });
            output = message;
          } else if (node.type === 'return') {
            output = resolveTemplate(node.value, context());
          }
          state.outputs[node.id] = output;
          completed.add(node.id);
          await adapters.emit('node.completed', node.id, { output });
        }),
      );
    } catch (error) {
      const failure = runFailureDetail(error);
      const failedNode = executable.find((node) => !completed.has(node.id));
      await adapters.emit('node.failed', failedNode?.id ?? null, { failure });
      state.completedNodeIds = [...completed];
      await adapters.emit('run.failed', null, { failure });
      return { status: 'failed', state, output: null, failure };
    }

    state.completedNodeIds = [...completed];
    const returnNode = executable.find((node) => node.type === 'return');
    if (returnNode) {
      const output = state.outputs[returnNode.id];
      await adapters.emit('run.completed', null, { output });
      return { status: 'completed', state, output, failure: null };
    }
    if (pendingInput && !completed.has(pendingInput.id)) {
      const replay = await adapters.replayInput?.(pendingInput.id);
      if (replay) {
        state.responses[pendingInput.responseKey] = replay.response;
        await adapters.emit('input.resolved', pendingInput.id, {
          responseKey: pendingInput.responseKey,
          response: replay.response,
          fromCache: true,
          sourceRunId: replay.sourceRunId,
        });
        await adapters.emit('node.completed', pendingInput.id, { output: replay.response });
        completed.add(pendingInput.id);
        state.completedNodeIds = [...completed];
        continue;
      }
      state.pendingNodeId = pendingInput.id;
      await adapters.emit('input.requested', pendingInput.id, {
        question: String(resolveTemplate(pendingInput.question, context()) ?? ''),
        responseKey: pendingInput.responseKey,
        choices: pendingInput.choices,
        timeoutSeconds: pendingInput.timeoutSeconds,
      });
      return { status: 'awaiting_input', state, output: null, failure: null };
    }
  }
  await adapters.emit('run.completed', null, { output: null });
  return { status: 'completed', state, output: null, failure: null };
}
