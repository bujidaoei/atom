import { expect, it, vi } from 'vitest';
import { describeOfficialConnector, listOfficialConnectorCatalog } from '../src/v5-connector-marketplace.ts';

const item = {
  connector_id: 'github',
  connector_name: 'GitHub',
  connector_name_cn: 'GitHub',
  description: 'Connect to GitHub through MCP.',
  description_cn: '通过 MCP 连接 GitHub。',
  icon_url: 'https://qoder-skills.oss-accelerate.aliyuncs.com/public/github.svg',
  author: { display_name: 'Github' },
  provider_name: 'GitHub',
  category: 'Coding',
  install_count: 12,
  clients: ['qoderwake'],
};

function catalog(items: unknown[] = [item]) {
  return {
    connectors: {
      items,
      pages: { current_page: 1, page_size: 20, total_size: items.length, last_page: 1 },
      facets: { categories: [{ code: 'Coding', label: 'Coding', count: items.length }] },
    },
  };
}

it('applies verified client/category filters and preserves upstream ordering and facets', async () => {
  const fetcher = vi.fn<typeof fetch>(async (url, options) => {
    const query = new URL(String(url)).searchParams;
    expect(query.get('client')).toBe('qoderwake');
    expect(query.get('extension_types')).toBe('connector');
    expect(query.get('keyword')).toBeNull();
    expect(query.get('category')).toBe('Coding');
    expect(options).toMatchObject({ credentials: 'omit', redirect: 'error' });
    return Response.json(
      catalog([
        item,
        { ...item, connector_id: 'linear', connector_name: 'Linear', connector_name_cn: 'Linear' },
      ]),
    );
  });
  const result = await listOfficialConnectorCatalog({ page: 1, pageSize: 20, category: 'Coding' }, fetcher);
  expect(result.items.map((value) => value.marketId)).toEqual(['github', 'linear']);
  expect(result.categories).toEqual([{ code: 'Coding', label: 'Coding', count: 2 }]);
  expect(result).toMatchObject({ page: 1, pageSize: 20, total: 2, lastPage: 1 });
  expect(result.items[0]?.presentation.localizedName).toBe('GitHub');
});

it('rejects cross-client, duplicate, malformed metadata and mismatched pagination', async () => {
  const wrongPage = catalog();
  wrongPage.connectors.pages.current_page = 2;
  for (const response of [
    catalog([{ ...item, clients: ['qoder'] }]),
    catalog([item, item]),
    catalog([{ ...item, install_count: -1 }]),
    wrongPage,
    {},
  ]) {
    await expect(
      listOfficialConnectorCatalog({ page: 1, pageSize: 20 }, async () => Response.json(response)),
    ).rejects.toThrow();
  }
});

it('rejects invalid filters before network and supports an empty result', async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json(catalog([])));
  for (const input of [
    { page: 0, pageSize: 20 },
    { page: 1, pageSize: 21 },
    { page: 1, pageSize: 20, query: 'GitHub' },
    { page: 1, pageSize: 20, featured: true },
    { page: 1, pageSize: 20, keyword: 'x'.repeat(201) },
  ]) {
    await expect(listOfficialConnectorCatalog(input as never, fetcher)).rejects.toThrow();
  }
  expect(fetcher).not.toHaveBeenCalled();
  expect((await listOfficialConnectorCatalog({ page: 1, pageSize: 20 }, fetcher)).items).toEqual([]);
});

it('filters keyword against official identity fields, not descriptions', async () => {
  const pages = new Map([
    [
      '1',
      catalog([
        item,
        {
          ...item,
          connector_id: 'notion',
          connector_name: 'Notion',
          connector_name_cn: 'Notion',
          author: { display_name: 'Notion' },
          provider_name: 'Notion',
          description: 'GitHub mentions should not match',
        },
      ]),
    ],
  ]);
  const fetcher = vi.fn<typeof fetch>(async (url) => {
    const page = new URL(String(url)).searchParams.get('pagination.current_page') ?? '1';
    return Response.json(pages.get(page) ?? catalog([]));
  });
  const result = await listOfficialConnectorCatalog({ page: 1, pageSize: 20, keyword: 'GitHub' }, fetcher);
  expect(result.items.map((value) => value.marketId)).toEqual(['github']);
  expect(result.total).toBe(1);
});

it('describes a QoderWake connector without proxying official install hosts', async () => {
  const fetcher = vi.fn<typeof fetch>(async (url) => {
    expect(String(url)).toContain('/apphub/api/v1/marketplace/connectors/github/detail');
    return Response.json({
      connector_id: 'github',
      connector_name: 'GitHub',
      connector_name_cn: 'GitHub',
      description: 'Connect to GitHub through MCP.',
      description_cn: '通过 MCP 连接 GitHub。',
      icon_url: 'https://qoder-skills.oss-accelerate.aliyuncs.com/public/github.svg',
      author: { display_name: 'Github' },
      category: 'Coding',
      version: '1.0.1',
      clients: ['qoderwake'],
      config: {
        servers: [
          {
            name: 'GitHub',
            url: 'https://api.githubcopilot.com/mcp/',
            protocol: 'streamable_http',
            auth_type: 'oauth',
            enabled: true,
            qoder_url: 'https://mcp.qoder.com/api/v1/mcp/servers/ignored',
          },
        ],
      },
    });
  });
  const detail = await describeOfficialConnector('github', fetcher);
  expect(detail).toMatchObject({
    marketId: 'github',
    connectorName: 'GitHub',
    category: 'Coding',
    version: '1.0.1',
  });
  expect(detail.servers).toEqual([
    {
      name: 'GitHub',
      url: 'https://api.githubcopilot.com/mcp/',
      protocol: 'streamable_http',
      authType: 'oauth',
      enabled: true,
    },
  ]);
  expect(JSON.stringify(detail)).not.toContain('mcp.qoder.com');
});
