import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reduceEvent } from '../src/workspace/stream-state.ts';

test('validation failure retracts streamed completion and shows diagnostic recovery', () => {
  const state: any = { items: [{ kind: 'message', runId: 'r', text: '已完成全部功能', streaming: false }],
    runIds: ['r'], activeRole: 'alex', inputTokens: 11, outputTokens: 7, heatActivity: {} };
  const failed = reduceEvent(state, {seq:1, runId:'r', role:'alex', type:'run.failed',
    payload:{validationError:true, message:'app.js:13 SyntaxError'}, at:''});
  assert.equal((failed.items[0] as any).text, '生成文件未通过平台检查。');
  const recovering = reduceEvent(failed, {seq:2,runId:null,role:'alex',type:'generation.repair_started',
    payload:{message:'正在自动修复（1/2）'},at:''});
  assert.equal((recovering.items.at(-1) as any).text, '正在自动修复（1/2）');
  assert.equal(recovering.inputTokens, 11);
});

test('authoritative terminal snapshots clear role, thinking and unfinished tools', () => {
  const state: any = { items: [
    { kind: 'message', runId: 'r', streaming: true, thinkingActive: true },
    { kind: 'tool', status: 'running' },
  ], runIds: ['r'], activeRole: 'alex', inputTokens: 0, outputTokens: 0, heatActivity: {} };
  for (const status of ['ready','cancelled','timed_out','interrupted','error']) {
    const next = reduceEvent(state,{seq:1,runId:null,role:null,type:'project.updated',payload:{status:status as any},at:''});
    assert.equal(next.activeRole,null);
    assert.equal((next.items[0] as any).streaming,false);
    assert.equal((next.items[1] as any).status,'failed');
  }
});

test('race terminal events never terminate the main role', () => {
  const state: any = {items:[],runIds:[],activeRole:'alex',inputTokens:0,outputTokens:0,heatActivity:{}};
  const next=reduceEvent(state,{seq:1,runId:'heat-run',role:'alex',type:'run.failed',payload:{heatId:'heat',message:'failed'},at:''});
  assert.equal(next.activeRole,'alex');
  assert.equal(next.items.length,0);
  assert.equal(next.heatActivity.heat.label,'failed');
});
