import { createHash } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import type { V3RequestContext } from '../../product-contracts/src/v3-ports.ts';
import { createV3KnowledgeTools } from '../src/v3-knowledge-tools.ts';

function fixture(text = '# Synthetic email\n\n正文测试代号 EMAIL-HTML-0925\n') {
  const content = Buffer.from(text);
  const context = { principal: { workspaceId: 'workspace', userId: 'owner' } } as V3RequestContext;
  const objects = [
    {
      knowledgeBaseId: 'base',
      knowledgeBaseName: 'Test knowledge',
      materialId: 'email',
      materialTitle: 'Synthetic email',
      version: 3,
      objectKey: 'compiled/email',
      contentSha256: createHash('sha256').update(content).digest('hex'),
      characterCount: text.length,
    },
  ];
  const base = {
    id: 'base',
    name: 'Test knowledge',
    ownerUserId: 'owner',
    description: '',
    status: 'ready' as const,
    currentCompilationVersion: 3,
    sourceCount: 1,
    createdAt: '2026-09-25T00:00:00Z',
    updatedAt: '2026-09-25T00:00:00Z',
  };
  const repository = {
    listCompiledKnowledge: vi.fn(async () => objects),
    listBases: vi.fn(async () => ({ items: [base], hasMore: false, nextCursor: null as string | null })),
    listBindings: vi.fn(async () => [
      {
        versionId: 'binding-v3',
        knowledgeBaseId: 'base',
        wakerId: 'waker',
        knowledgeVersion: 3,
        createdBy: 'owner',
        createdAt: base.createdAt,
      },
    ]),
  };
  const storage = { get: vi.fn(async () => content) };
  const assertActive = vi.fn();
  const tools = createV3KnowledgeTools({
    repository,
    storage,
    context,
    bindingVersionIds: ['binding-v3'],
    assertActive,
  });
  return { tools, repository, storage, context, objects, assertActive };
}

describe('authorized knowledge Pi tools', () => {
  it('discovers accessible empty and unbound bases across pages without granting retrieval access', async () => {
    const f = fixture();
    const first = await f.repository.listBases();
    const empty = {
      ...first.items[0]!,
      id: 'empty',
      name: 'Empty test base',
      sourceCount: 0,
      currentCompilationVersion: 0,
    };
    f.repository.listBases
      .mockResolvedValueOnce({ ...first, hasMore: true, nextCursor: 'page-2' })
      .mockResolvedValueOnce({ items: [empty], hasMore: false, nextCursor: null });
    const list = await f.tools[0]!.execute('list', {}, undefined);
    expect(list.details).toMatchObject({
      total: 2,
      boundCount: 1,
      notebooks: [
        { notebookId: 'base', bound: true },
        { notebookId: 'empty', bound: false, bindingStatus: 'not_bound' },
      ],
    });
    expect(f.repository.listBases).toHaveBeenLastCalledWith(f.context, { limit: 200, cursor: 'page-2' });
    expect(f.storage.get).not.toHaveBeenCalled();
    await expect(
      f.tools[1]!.execute('query', { notebookId: 'empty', query: 'EMAIL' }, undefined),
    ).rejects.toThrow('unavailable');
    expect(f.storage.get).not.toHaveBeenCalled();
  });
  it('stops catalog enumeration after cancellation and rejects repeated cursors', async () => {
    const f = fixture();
    f.repository.listBases.mockResolvedValue({ items: [], hasMore: true, nextCursor: 'same' });
    await expect(f.tools[0]!.execute('list', {}, undefined)).rejects.toThrow('pagination');
    const controller = new AbortController();
    controller.abort();
    f.repository.listBases.mockClear();
    await expect(f.tools[0]!.execute('list', {}, controller.signal)).rejects.toThrow();
    expect(f.repository.listBases).not.toHaveBeenCalled();
  });
  it('finds evidence beyond a long single-line prefix without returning an unrelated prefix', async () => {
    const f = fixture('x'.repeat(4500) + ' UNIQUE-EVIDENCE-0925');
    const result = await f.tools[1]!.execute(
      'q',
      { notebookId: 'base', query: 'UNIQUE-EVIDENCE-0925' },
      undefined,
    );
    expect(result.details).toMatchObject({
      sourceLinks: [{ lineStart: 1, lineEnd: 1, content: expect.stringContaining('UNIQUE-EVIDENCE-0925') }],
    });
  });
  it('retrieves Chinese/English evidence with source identity and real line ranges', async () => {
    const f = fixture();
    const list = await f.tools[0]!.execute('list', {}, undefined);
    expect(list.details).toMatchObject({ notebooks: [{ notebookId: 'base', bound: true }] });
    const result = await f.tools[1]!.execute(
      'query',
      { notebookId: 'base', query: '正文测试代号 EMAIL' },
      undefined,
    );
    expect(result.details).toMatchObject({
      sourceLinks: [
        {
          sourceId: 'email',
          version: 3,
          lineStart: 1,
          lineEnd: 4,
          content: expect.stringContaining('EMAIL-HTML-0925'),
        },
      ],
    });
    expect(f.repository.listCompiledKnowledge).toHaveBeenCalledWith(f.context, ['binding-v3']);
    expect(f.storage.get).toHaveBeenCalledWith('compiled/email');
  });
  it('rejects unbound sources, revoked access, altered bytes and cancellation', async () => {
    const f = fixture();
    const query = () => f.tools[1]!.execute('query', { notebookId: 'base', query: 'EMAIL' }, undefined);
    await expect(
      f.tools[1]!.execute('q', { notebookId: 'other', query: 'EMAIL' }, undefined),
    ).rejects.toThrow('unavailable');
    expect(f.storage.get).not.toHaveBeenCalled();
    f.storage.get.mockResolvedValueOnce(Buffer.from('altered'));
    await expect(query()).rejects.toThrow('integrity');
    f.repository.listCompiledKnowledge.mockResolvedValueOnce(f.objects).mockResolvedValueOnce([]);
    await expect(query()).rejects.toThrow('access changed');
    const controller = new AbortController();
    controller.abort();
    f.storage.get.mockClear();
    await expect(
      f.tools[1]!.execute('q', { notebookId: 'base', query: 'EMAIL' }, controller.signal),
    ).rejects.toThrow();
    expect(f.storage.get).not.toHaveBeenCalled();
  });
  it('returns no fabricated result on a nonmatching query and validates input', async () => {
    const f = fixture();
    const result = await f.tools[1]!.execute('q', { notebookId: 'base', query: 'NO_MATCH_54321' }, undefined);
    expect(result.details).toMatchObject({ sourceLinks: [], total: 0 });
    await expect(
      f.tools[1]!.execute('q', { notebookId: 'base', query: 'EMAIL', maxResults: 10000 }, undefined),
    ).rejects.toThrow('Invalid');
  });
});
