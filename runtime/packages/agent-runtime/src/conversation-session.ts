import { stat } from 'node:fs/promises';
import type { V3ConversationRunPage, V3Run } from '../../product-contracts/src/v3.ts';

/** Select only an earlier completed turn from the authenticated conversation.
 * Each Run retains its own Pi file so retry and recovery never overwrite another turn.
 * Pi itself forks and restores the complete branch, including compaction and tool messages.
 */
export async function previousConversationSession(input: {
  run: Pick<V3Run, 'id' | 'taskId'>;
  wakerId: string;
  readPage: (cursor: string) => Promise<V3ConversationRunPage>;
  sessionPath: (runId: string) => string;
}): Promise<string | undefined> {
  let cursor = `cr_v1_${input.run.id}`;
  const visited = new Set<string>();
  while (!visited.has(cursor)) {
    visited.add(cursor);
    const page = await input.readPage(cursor);
    for (const item of page.runs) {
      if (
        item.wakerId !== input.wakerId ||
        item.run.taskId === input.run.taskId ||
        item.run.status !== 'completed'
      )
        continue;
      const path = input.sessionPath(item.run.id);
      const file = await stat(path).catch((error: NodeJS.ErrnoException) => {
        if (error.code === 'ENOENT') return undefined;
        throw error;
      });
      if (file?.isFile()) return path;
    }
    if (!page.hasMore || !page.nextCursor) return undefined;
    cursor = page.nextCursor;
  }
  throw new Error('Conversation Run history repeated a cursor');
}
