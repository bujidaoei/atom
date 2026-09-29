import { expect, it, vi } from 'vitest';
import {
  describeOfficialPlugin,
  listOfficialPluginCatalog,
  officialFeaturedPluginIds,
} from '../src/v5-plugin-marketplace.ts';

const item = {
  plugin_id: 'design',
  plugin_name: 'design',
  display_name: 'Design',
  clients: ['qoderwake'],
  install_count: 12,
  category: 'Design',
};
function catalog(items: unknown[] = [item]) {
  return {
    plugins: {
      items,
      pages: { current_page: 1, page_size: 20, total_size: items.length, last_page: 1 },
      facets: { categories: [{ code: 'Design', label: 'Design', count: items.length }] },
    },
  };
}
it('applies verified client/category filters and preserves upstream ordering and facets', async () => {
  const fetcher = vi.fn<typeof fetch>(async (url, options) => {
    const query = new URL(String(url)).searchParams;
    expect(query.get('client')).toBe('qoderwake');
    expect(query.get('extension_types')).toBe('plugin');
    expect(query.get('keyword')).toBeNull();
    expect(query.get('category')).toBe('Design');
    expect(query.get('tag')).toBeNull();
    expect(options).toMatchObject({ credentials: 'omit', redirect: 'error' });
    return Response.json(catalog([item, { ...item, plugin_id: 'another', display_name: 'Another' }]));
  });
  const result = await listOfficialPluginCatalog({ page: 1, pageSize: 20, category: 'Design' }, fetcher);
  expect(result.items.map((value) => value.marketId)).toEqual(['design', 'another']);
  expect(result.categories).toEqual([{ code: 'Design', label: 'Design', count: 2 }]);
  expect(result).toMatchObject({ page: 1, pageSize: 20, total: 2, lastPage: 1 });
});
it('rejects cross-client, duplicate, malformed metadata and mismatched pagination', async () => {
  const wrongPage = catalog();
  wrongPage.plugins.pages.current_page = 2;
  for (const response of [
    catalog([{ ...item, clients: ['qoder'] }]),
    catalog([item, item]),
    catalog([{ ...item, install_count: -1 }]),
    wrongPage,
    {},
  ]) {
    await expect(
      listOfficialPluginCatalog({ page: 1, pageSize: 20 }, async () => Response.json(response)),
    ).rejects.toThrow();
  }
});
it('rejects invalid filters before network and supports an empty result', async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json(catalog([])));
  for (const input of [
    { page: 0, pageSize: 20 },
    { page: 1, pageSize: 21 },
    { page: 1, pageSize: 20, query: 'Frontend' },
    { page: 1, pageSize: 20, featured: true, category: 'Design' },
    { page: 1, pageSize: 20, keyword: 'x'.repeat(201) },
  ]) {
    await expect(listOfficialPluginCatalog(input, fetcher)).rejects.toThrow();
  }
  expect(fetcher).not.toHaveBeenCalled();
  expect((await listOfficialPluginCatalog({ page: 1, pageSize: 20 }, fetcher)).items).toEqual([]);
});

it('filters featured and keyword against official identity fields, not descriptions', async () => {
  const pages = new Map<string, ReturnType<typeof catalog>>([
    [
      '1',
      catalog([
        {
          ...item,
          plugin_id: officialFeaturedPluginIds[0],
          plugin_name: 'superpowers',
          display_name: 'Superpowers',
        },
        {
          ...item,
          plugin_id: 'design-review',
          plugin_name: 'design-review',
          display_name: 'Design Review',
          description: 'Frontend guidance',
        },
        {
          ...item,
          plugin_id: 'frontend-design',
          plugin_name: 'frontend-design',
          display_name: 'Frontend Design',
        },
      ]),
    ],
  ]);
  pages.get('1')!.plugins.pages = { current_page: 1, page_size: 20, total_size: 3, last_page: 1 };
  const fetcher = vi.fn<typeof fetch>(async (url) => {
    const query = new URL(String(url)).searchParams;
    expect(query.get('keyword')).toBeNull();
    expect(query.get('featured')).toBeNull();
    return Response.json(pages.get(query.get('pagination.current_page') ?? '') ?? catalog([]));
  });
  const featured = await listOfficialPluginCatalog({ page: 1, pageSize: 20, featured: true }, fetcher);
  expect(featured.items.map((value) => value.marketId)).toEqual([
    officialFeaturedPluginIds[0],
    'frontend-design',
  ]);
  expect(featured.total).toBe(2);
  expect(featured.items.every((value) => value.recommended)).toBe(true);
  const keyword = await listOfficialPluginCatalog({ page: 1, pageSize: 20, keyword: 'Frontend' }, fetcher);
  expect(keyword.items.map((value) => value.marketId)).toEqual(['frontend-design']);
  expect(keyword.total).toBe(1);
});

it('retains zero-count categories during search and combines the keyword with featured filtering', async () => {
  const response = catalog([
    item,
    {
      ...item,
      plugin_id: 'builder',
      display_name: 'Builder',
      plugin_name: 'builder',
      category: 'Development',
    },
  ]);
  response.plugins.facets.categories[0]!.count = 1;
  response.plugins.facets.categories.push({ code: 'Development', label: 'Development', count: 1 });
  response.plugins.facets.categories.push({ code: 'Unused', label: 'Unused', count: 0 });
  const fetcher = async () => Response.json(response);
  const search = await listOfficialPluginCatalog({ page: 1, pageSize: 20, keyword: 'Design' }, fetcher);
  expect(search.categories).toEqual([
    { code: 'Design', label: 'Design', count: 1 },
    { code: 'Development', label: 'Development', count: 0 },
  ]);
  const featured = await listOfficialPluginCatalog(
    { page: 1, pageSize: 20, keyword: 'Design', featured: true },
    fetcher,
  );
  expect(featured.total).toBe(0);
  expect(featured.categories.map((category) => category.count)).toEqual([0, 0]);
  const empty = await listOfficialPluginCatalog({ page: 1, pageSize: 20, keyword: 'missing' }, fetcher);
  expect(empty.total).toBe(0);
  expect(empty.categories.map((category) => category.code)).toEqual(['Design', 'Development']);
});

it('describes installed plugin composition without downloading the package', async () => {
  const fetcher = vi.fn<typeof fetch>(async (url) => {
    expect(String(url)).toBe('https://qoder.com/apphub/api/v1/marketplace/plugins/frontend-design/detail');
    return Response.json({
      plugin_id: 'frontend-design',
      version: '1.0.0',
      clients: ['qoderwake'],
      category: 'Design',
      install_count: 6077,
      skills: [{ name: 'frontend-design', description: 'Guidance', description_cn: '' }],
      commands: [],
      connectors: [{ id: 'sourcegraph', description: '' }],
    });
  });
  await expect(describeOfficialPlugin('frontend-design', fetcher)).resolves.toEqual({
    version: '1.0.0',
    category: 'Design',
    installCount: 6077,
    skills: [{ name: 'frontend-design', description: 'Guidance' }],
    commands: [],
    connectors: [{ name: 'sourcegraph', description: '' }],
  });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
