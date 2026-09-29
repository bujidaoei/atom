import { describe, expect, it, vi } from 'vitest';

import type { V3WorkflowNode } from '../../product-contracts/src/v3.ts';
import {
  V3WorkflowInputError,
  executeV3Workflow,
  prepareV3WorkflowArgs,
  validateV3WorkflowDefinition,
  type V3WorkflowDefinition,
  type V3WorkflowExecutionAdapters,
} from '../src/v3-workflow-runtime.ts';

const wakerId = '00000000-0000-4000-8000-000000000001';

function adapters() {
  const events: Array<{ type: string; nodeId: string | null; payload: Record<string, unknown> }> = [];
  const value: V3WorkflowExecutionAdapters = {
    runWorker: vi.fn(async ({ instruction }) => ({ instruction })),
    runPipelineItem: vi.fn(async ({ item, instruction }) => ({ item, instruction })),
    runAction: vi.fn(async ({ args }) => args),
    runSubflow: vi.fn(async ({ value: input }) => input),
    emit: vi.fn(async (type, nodeId, payload) => {
      events.push({ type, nodeId, payload });
    }),
  };
  return { value, events };
}

function workflow(nodes: V3WorkflowNode[], startNodeId = nodes[0]!.id): V3WorkflowDefinition {
  return {
    startNodeId,
    inputSchema: [
      {
        key: 'request',
        label: '需求',
        description: '',
        type: 'string',
        required: true,
      },
    ],
    nodes,
  };
}

describe('V3 WakerFlow runtime', () => {
  it('validates required typed inputs and rejects undeclared values', () => {
    expect(
      prepareV3WorkflowArgs(
        [
          { key: 'count', label: '数量', description: '', type: 'number', required: true },
          {
            key: 'enabled',
            label: '启用',
            description: '',
            type: 'boolean',
            required: false,
            defaultValue: true,
          },
        ],
        { count: 3 },
      ),
    ).toEqual({ count: 3, enabled: true });
    expect(() => prepareV3WorkflowArgs([], { extra: true })).toThrow(V3WorkflowInputError);
    expect(() =>
      prepareV3WorkflowArgs(
        [{ key: 'count', label: '数量', description: '', type: 'number', required: true }],
        { count: '3' },
      ),
    ).toThrow(V3WorkflowInputError);
  });

  it('rejects cycles, unreachable branches, invalid joins, and missing return paths', () => {
    const definition = workflow([
      { id: 'start', name: '开始', type: 'phase', next: ['loop'] },
      { id: 'loop', name: '循环', type: 'join', next: ['start'] },
      { id: 'orphan', name: '孤立', type: 'return', next: [], value: null },
    ]);
    expect(validateV3WorkflowDefinition(definition)).toEqual(
      expect.arrayContaining([
        '工作流不能包含循环依赖。',
        '节点 orphan 无法从起始节点到达。',
        '汇合节点 loop 至少需要两个前置分支。',
      ]),
    );
  });

  it('executes parallel branches, joins them, and returns real worker results', async () => {
    const definition = workflow([
      { id: 'start', name: '开始', type: 'phase', next: ['parallel'] },
      { id: 'parallel', name: '并行', type: 'parallel', next: ['product', 'engineering'] },
      {
        id: 'product',
        name: '产品',
        type: 'worker',
        next: ['join'],
        wakerId,
        instruction: '规划 {{args.request}}',
      },
      {
        id: 'engineering',
        name: '工程',
        type: 'worker',
        next: ['join'],
        wakerId,
        instruction: '实现 {{args.request}}',
      },
      { id: 'join', name: '汇合', type: 'join', next: ['done'] },
      {
        id: 'done',
        name: '返回',
        type: 'return',
        next: [],
        value: { product: '{{results.product}}', engineering: '{{results.engineering}}' },
      },
    ]);
    const testAdapters = adapters();
    const result = await executeV3Workflow('run-1', definition, { request: '扫雷' }, testAdapters.value);
    expect(result.status).toBe('completed');
    expect(result.output).toEqual({
      product: { instruction: '规划 扫雷' },
      engineering: { instruction: '实现 扫雷' },
    });
    expect(testAdapters.value.runWorker).toHaveBeenCalledTimes(2);
    expect(testAdapters.events.at(-1)?.type).toBe('run.completed');
  });

  it('completes with null when the script has no explicit return', async () => {
    const definition = workflow([
      { id: 'start', name: '开始', type: 'phase', next: ['log'] },
      {
        id: 'log',
        name: '记录',
        type: 'log',
        next: [],
        level: 'info',
        message: '已处理 {{args.request}}',
      },
    ]);
    const testAdapters = adapters();
    const result = await executeV3Workflow(
      'run-no-return',
      definition,
      { request: '扫雷' },
      testAdapters.value,
    );
    expect(result).toMatchObject({ status: 'completed', output: null, failure: null });
    expect(testAdapters.events.map(({ type }) => type)).toEqual([
      'node.started',
      'node.completed',
      'node.started',
      'log',
      'node.completed',
      'run.completed',
    ]);
  });

  it('returns builtin JavaScript Action data and records its action identity', async () => {
    const definition = workflow([
      {
        id: 'acceptance',
        name: 'Return acceptance result',
        type: 'action',
        next: ['done'],
        actionId: 'return-acceptance-result',
        actionType: 'builtin',
        handlerSource: "return 'ACTION-BUILTIN-OK';",
        args: {},
      },
      { id: 'done', name: 'Return', type: 'return', next: [], value: '{{results.acceptance.data}}' },
    ]);
    const testAdapters = adapters();
    vi.mocked(testAdapters.value.runAction).mockResolvedValue({ data: 'ACTION-BUILTIN-OK' });
    const result = await executeV3Workflow(
      'builtin-run',
      definition,
      { request: '验收' },
      testAdapters.value,
    );
    expect(result).toMatchObject({ status: 'completed', output: 'ACTION-BUILTIN-OK' });
    expect(testAdapters.value.runAction).toHaveBeenCalledWith(
      expect.objectContaining({ target: 'return-acceptance-result' }),
    );
    expect(testAdapters.events.find(({ type }) => type === 'action.dispatched')?.payload).toMatchObject({
      type: 'builtin',
      target: 'return-acceptance-result',
    });
  });

  it('pauses for Ask User and resumes without repeating completed workers', async () => {
    const definition = workflow([
      {
        id: 'worker',
        name: '执行',
        type: 'worker',
        next: ['approval'],
        wakerId,
        instruction: '处理 {{args.request}}',
      },
      {
        id: 'approval',
        name: '确认',
        type: 'ask_user',
        next: ['done'],
        question: '确认 {{results.worker}}？',
        responseKey: 'decision',
        choices: ['通过', '拒绝'],
        timeoutSeconds: null,
      },
      { id: 'done', name: '返回', type: 'return', next: [], value: '{{responses.decision}}' },
    ]);
    const testAdapters = adapters();
    const first = await executeV3Workflow('run-2', definition, { request: '扫雷' }, testAdapters.value);
    expect(first.status).toBe('awaiting_input');
    expect(first.state.pendingNodeId).toBe('approval');
    expect(testAdapters.value.runWorker).toHaveBeenCalledTimes(1);

    const stillWaiting = await executeV3Workflow(
      'run-2',
      definition,
      { request: '扫雷' },
      testAdapters.value,
      first.state,
    );
    expect(stillWaiting.status).toBe('awaiting_input');
    expect(testAdapters.value.runWorker).toHaveBeenCalledTimes(1);

    const resumed = await executeV3Workflow('run-2', definition, { request: '扫雷' }, testAdapters.value, {
      ...first.state,
      responses: { decision: '通过' },
    });
    expect(resumed.status).toBe('completed');
    expect(resumed.output).toBe('通过');
    expect(testAdapters.value.runWorker).toHaveBeenCalledTimes(1);
  });

  it('limits Pipeline concurrency, preserves item order, and uses stable execution keys', async () => {
    const definition: V3WorkflowDefinition = {
      startNodeId: 'pipeline',
      inputSchema: [{ key: 'items', label: '项目', description: '', type: 'array', required: true }],
      nodes: [
        {
          id: 'pipeline',
          name: '批处理',
          type: 'pipeline',
          next: ['done'],
          wakerId,
          itemsExpression: '{{args.items}}',
          instruction: '处理 {{item}} / {{index}}',
          concurrency: 2,
        },
        { id: 'done', name: '返回', type: 'return', next: [], value: '{{results.pipeline}}' },
      ],
    };
    const testAdapters = adapters();
    let active = 0;
    let peak = 0;
    testAdapters.value.runPipelineItem = vi.fn(async ({ item, executionKey }) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      return { item, executionKey };
    });
    const result = await executeV3Workflow(
      'run-3',
      definition,
      { items: ['a', 'b', 'c'] },
      testAdapters.value,
    );
    expect(peak).toBe(2);
    expect(result.output).toEqual([
      { item: 'a', executionKey: 'run-3:pipeline:0' },
      { item: 'b', executionKey: 'run-3:pipeline:1' },
      { item: 'c', executionKey: 'run-3:pipeline:2' },
    ]);
  });

  it('settles failed pipeline items as null, continues later items and persists individual receipts', async () => {
    const definition: V3WorkflowDefinition = {
      startNodeId: 'pipe',
      inputSchema: [{ key: 'items', label: 'Items', description: '', type: 'array', required: true }],
      nodes: [
        {
          id: 'pipe',
          name: 'Pipeline',
          type: 'pipeline',
          wakerId,
          itemsExpression: '{{args.items}}',
          instruction: '{{item}}',
          concurrency: 1,
          next: ['done'],
        },
        { id: 'done', name: 'Return', type: 'return', value: '{{results.pipe}}', next: [] },
      ],
    };
    const testAdapters = adapters();
    testAdapters.value.runPipelineItem = vi.fn(async ({ item }) => {
      if (item === 'bad') throw new Error('ITEM-FAILED');
      return item;
    });
    const result = await executeV3Workflow(
      'mixed',
      definition,
      { items: ['first', 'bad', 'last'] },
      testAdapters.value,
    );
    expect(result).toMatchObject({ status: 'completed', output: ['first', null, 'last'] });
    expect(testAdapters.value.runPipelineItem).toHaveBeenCalledTimes(3);
    expect(testAdapters.events.filter((e) => e.type.startsWith('pipeline.item.'))).toEqual([
      { type: 'pipeline.item.started', nodeId: 'pipe', payload: { index: 0, instruction: 'first' } },
      { type: 'pipeline.item.completed', nodeId: 'pipe', payload: { index: 0, output: 'first' } },
      { type: 'pipeline.item.started', nodeId: 'pipe', payload: { index: 1, instruction: 'bad' } },
      { type: 'pipeline.item.failed', nodeId: 'pipe', payload: { index: 1, failure: 'ITEM-FAILED' } },
      { type: 'pipeline.item.started', nodeId: 'pipe', payload: { index: 2, instruction: 'last' } },
      { type: 'pipeline.item.completed', nodeId: 'pipe', payload: { index: 2, output: 'last' } },
    ]);
    // An item must not be acknowledged if its receipt could not be persisted.
    testAdapters.value.emit = vi.fn(async (type) => {
      if (type === 'pipeline.item.completed') throw new Error('PERSISTENCE-FAILED');
    });
    expect(
      await executeV3Workflow('receipt-failure', definition, { items: ['first'] }, testAdapters.value),
    ).toMatchObject({ status: 'failed', failure: 'PERSISTENCE-FAILED' });
  });

  it('resolves and executes official Script Action fields with durable action events', async () => {
    const definition = workflow([
      {
        id: 'notify',
        name: 'Notify delivery',
        type: 'action',
        next: ['done'],
        actionId: 'notify-script',
        actionType: 'script',
        command: 'node scripts/{{args.request}}.mjs',
        args: ['{{args.request}}', { prior: '{{results.missing}}' }],
      },
      { id: 'done', name: '返回', type: 'return', next: [], value: '{{results.notify}}' },
    ]);
    const testAdapters = adapters();
    testAdapters.value.runAction = vi.fn(async ({ args, target }) => ({ args, target }));
    const result = await executeV3Workflow(
      'run-action',
      definition,
      { request: 'deliver' },
      testAdapters.value,
    );
    expect(result.output).toEqual({
      target: 'node scripts/deliver.mjs',
      args: ['deliver', {}],
    });
    expect(testAdapters.events.map(({ type }) => type)).toEqual([
      'node.started',
      'action.dispatched',
      'action.completed',
      'node.completed',
      'node.started',
      'node.completed',
      'run.completed',
    ]);
    expect(testAdapters.events[1]?.payload).toEqual({
      actionId: 'notify-script',
      label: 'Notify delivery',
      type: 'script',
      target: 'node scripts/deliver.mjs',
    });
  });

  it('returns a durable failed state and never emits completion after an adapter failure', async () => {
    const definition = workflow([
      {
        id: 'worker',
        name: '执行',
        type: 'worker',
        next: ['done'],
        wakerId,
        instruction: '处理 {{args.request}}',
      },
      { id: 'done', name: '返回', type: 'return', next: [], value: null },
    ]);
    const testAdapters = adapters();
    testAdapters.value.runWorker = vi.fn(async () => {
      throw new Error('provider unavailable');
    });
    const result = await executeV3Workflow('run-4', definition, { request: '扫雷' }, testAdapters.value);
    expect(result).toMatchObject({ status: 'failed', failure: 'provider unavailable' });
    expect(testAdapters.events.map(({ type }) => type)).toEqual([
      'node.started',
      'node.failed',
      'run.failed',
    ]);
  });

  it('records the official Action failure event before the node and run failures', async () => {
    const definition = workflow([
      {
        id: 'webhook',
        name: 'Delivery webhook',
        type: 'action',
        next: ['done'],
        actionId: 'delivery-webhook',
        actionType: 'http',
        url: 'https://actions.example.test/{{args.request}}',
        method: 'POST',
        args: { delivery: '{{args.request}}' },
      },
      { id: 'done', name: '返回', type: 'return', next: [], value: null },
    ]);
    const testAdapters = adapters();
    testAdapters.value.runAction = vi.fn(async () => {
      throw new Error('webhook unavailable');
    });
    const result = await executeV3Workflow(
      'run-action-failed',
      definition,
      { request: 'D-42' },
      testAdapters.value,
    );
    expect(result).toMatchObject({ status: 'failed', failure: 'webhook unavailable' });
    expect(testAdapters.events.map(({ type }) => type)).toEqual([
      'node.started',
      'action.dispatched',
      'action.failed',
      'node.failed',
      'run.failed',
    ]);
    expect(testAdapters.events[2]?.payload).toEqual({
      error: { code: 'ACTION_FAILED', message: 'webhook unavailable' },
    });
  });
});
