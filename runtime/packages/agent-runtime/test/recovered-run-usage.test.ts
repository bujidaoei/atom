import { expect, it } from 'vitest';
import { recoveredRunUsage } from '../src/recovered-run-usage.ts';

it('counts only persisted model and plugin child usage, excluding unrelated tool data and partial events', () => {
  const usage = {
    inputTokens: 3,
    outputTokens: 2,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
    totalTokens: 5,
    totalCost: 0,
  };
  const result = (toolName: string, value: unknown = usage) => ({
    type: 'message',
    message: { role: 'toolResult', toolName, details: { usage: value } },
  });
  expect(
    recoveredRunUsage([
      result('query_docs'),
      { ...result('plugin_agent'), type: 'custom' },
      result('plugin_agent', { ...usage, totalTokens: -1 }),
      result('plugin_agent', { ...usage, inputTokens: Infinity }),
      result('plugin_agent', null),
      result('plugin_agent'),
      {
        type: 'message',
        message: {
          role: 'assistant',
          usage: { input: 7, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 12, cost: { total: 0 } },
        },
      },
    ]),
  ).toEqual({ ...usage, inputTokens: 10, outputTokens: 7, totalTokens: 17 });
  expect(recoveredRunUsage([])).toBeNull();
});
