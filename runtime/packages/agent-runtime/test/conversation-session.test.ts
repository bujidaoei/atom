import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, expect, it } from 'vitest';
import type { V3ConversationRunPage } from '../../product-contracts/src/v3.ts';
import { previousConversationSession } from '../src/conversation-session.ts';

const roots: string[] = [];
afterEach(async () => {
  await Promise.all(roots.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

function item(id: string, taskId = id, wakerId = 'owner'): V3ConversationRunPage['runs'][number] {
  return {
    wakerId,
    sessionId: null,
    run: {
      id,
      taskId,
      attempt: 1,
      executionTarget: 'local',
      provider: 'gateway',
      model: 'test',
      providerCorrelationId: null,
      status: 'completed',
      usage: null,
      failureCategory: null,
    },
  };
}

it('walks older pages without crossing Waker or retry boundaries and skips absent session files', async () => {
  const root = await mkdtemp(join(tmpdir(), 'conversation-parent-'));
  roots.push(root);
  for (const id of ['other-waker', 'retry', 'valid'])
    await writeFile(join(root, id), 'native session fixture');
  const cursors: string[] = [];
  const selected = await previousConversationSession({
    run: { id: 'current', taskId: 'current-task' },
    wakerId: 'owner',
    sessionPath: (id) => join(root, id),
    readPage: async (cursor) => {
      cursors.push(cursor);
      return cursor === 'cr_v1_current'
        ? {
            runs: [
              item('other-waker', 'other-task', 'other'),
              item('retry', 'current-task'),
              item('missing'),
            ],
            hasMore: true,
            nextCursor: 'older',
          }
        : { runs: [item('valid')], hasMore: false, nextCursor: '' };
    },
  });
  expect(selected).toBe(join(root, 'valid'));
  expect(cursors).toEqual(['cr_v1_current', 'older']);
});

it('does not invent context when the authenticated conversation has no earlier turn', async () => {
  await expect(
    previousConversationSession({
      run: { id: 'new', taskId: 'new-task' },
      wakerId: 'owner',
      sessionPath: (id) => id,
      readPage: async () => ({ runs: [], hasMore: false, nextCursor: '' }),
    }),
  ).resolves.toBeUndefined();
});

it('rejects a repeated pagination cursor instead of looping indefinitely', async () => {
  await expect(
    previousConversationSession({
      run: { id: 'current', taskId: 'task' },
      wakerId: 'owner',
      sessionPath: (id) => id,
      readPage: async () => ({ runs: [], hasMore: true, nextCursor: 'cr_v1_current' }),
    }),
  ).rejects.toThrow('repeated a cursor');
});
