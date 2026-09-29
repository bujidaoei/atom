import type {
  ConnectorCatalogInput,
  ConnectorCatalogPage,
  ConnectorMarketDetail,
  ConnectorMarketServer,
} from '../../product-contracts/src/v5-connectors.ts';
import type { PluginPresentation } from '../../product-contracts/src/v5-plugins.ts';
import { qoderJson } from './qoder-marketplace-transport.ts';

const CATALOG_FILTERS = new Set(['page', 'pageSize', 'category', 'keyword']);
const MARKET_ID = /^[A-Za-z0-9_-]{3,120}$/u;

function text(value: unknown, field: string, limit = 160): string {
  if (typeof value !== 'string' || !value.trim() || value.length > limit)
    throw new Error(`Qoder connector ${field} is invalid`);
  return value.trim();
}

function optionalText(value: unknown, field: string, limit: number): string {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value !== 'string' || value.length > limit)
    throw new Error(`Qoder connector ${field} is invalid`);
  return value.trim();
}

function integer(value: unknown, field: string, minimum: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum)
    throw new Error(`Invalid connector catalog ${field}`);
  return value;
}

function httpsIcon(value: unknown): string | null {
  const icon = optionalText(value, 'icon URL', 2000);
  if (!icon) return null;
  const url = new URL(icon);
  if (url.protocol !== 'https:' || url.username || url.password)
    throw new Error('Invalid connector icon URL');
  return url.href;
}

function httpsUrl(value: unknown): string | null {
  const raw = optionalText(value, 'server URL', 2000);
  if (!raw) return null;
  const url = new URL(raw);
  if (url.protocol !== 'https:' || url.username || url.password)
    throw new Error('Invalid connector server URL');
  return url.href;
}

function presentation(item: Record<string, unknown>, connectorName: string): PluginPresentation {
  const authorRecord =
    item.author && typeof item.author === 'object' && !Array.isArray(item.author)
      ? (item.author as Record<string, unknown>)
      : undefined;
  return {
    displayName: optionalText(item.connector_name, 'display name', 160) || connectorName,
    localizedName: optionalText(item.connector_name_cn, 'localized name', 160) || null,
    description: optionalText(item.description, 'description', 20_000),
    localizedDescription: optionalText(item.description_cn, 'localized description', 20_000) || null,
    author:
      optionalText(authorRecord?.display_name, 'author', 200) ||
      optionalText(item.provider_name, 'provider', 200),
    iconUrl: httpsIcon(item.icon_url),
  };
}

function marketId(value: unknown): string {
  const id = text(value, 'market id', 120);
  if (!MARKET_ID.test(id)) throw new Error('Invalid connector market id');
  return id;
}

type CatalogItem = ConnectorCatalogPage['items'][number];

function matchesOfficialKeyword(item: CatalogItem, keyword: string): boolean {
  const needle = keyword.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    item.marketId,
    item.connectorName,
    item.presentation.displayName,
    item.presentation.localizedName ?? '',
    item.presentation.author,
  ].some((value) => value.toLocaleLowerCase().includes(needle));
}

function protocol(value: unknown): ConnectorMarketServer['protocol'] {
  const raw = optionalText(value, 'protocol', 40).toLocaleLowerCase();
  if (raw === 'sse') return 'sse';
  if (raw === 'stdio') return 'stdio';
  return 'streamable_http';
}

function servers(value: unknown): ConnectorMarketServer[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || value.length > 20) throw new Error('Invalid connector servers');
  return value.map((entry) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry))
      throw new Error('Invalid connector server');
    const record = entry as Record<string, unknown>;
    const name = optionalText(record.name, 'server name', 160) || 'connector';
    return {
      name,
      url: httpsUrl(record.url),
      protocol: protocol(record.protocol ?? record.type),
      authType: optionalText(record.auth_type, 'auth type', 40),
      enabled: record.enabled !== false,
    };
  });
}

async function fetchOfficialCatalogPage(
  input: { page: number; pageSize: number; category?: string },
  fetchImpl: typeof fetch,
): Promise<ConnectorCatalogPage> {
  const parameters = new URLSearchParams({
    extension_types: 'connector',
    client: 'qoderwake',
    sort: 'hot',
    include_facets: 'true',
    'pagination.current_page': String(input.page),
    'pagination.page_size': String(input.pageSize),
  });
  const category = optionalText(input.category, 'category', 120);
  if (category) parameters.set('category', category);
  const response = await qoderJson<{
    connectors?: {
      items?: unknown;
      pages?: Record<string, unknown>;
      facets?: { categories?: unknown };
    };
  }>(`/apphub/api/v1/marketplace/catalog/extensions?${parameters}`, fetchImpl);
  const catalog = response?.connectors;
  if (
    !catalog ||
    !Array.isArray(catalog.items) ||
    !catalog.pages ||
    !Array.isArray(catalog.facets?.categories)
  )
    throw new Error('Invalid connector catalog response');
  const items = catalog.items.map((value: unknown) => {
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('Invalid connector catalog item');
    const item = value as Record<string, unknown>;
    if (!Array.isArray(item.clients) || !item.clients.includes('qoderwake'))
      throw new Error('Connector catalog client mismatch');
    const id = marketId(item.connector_id);
    const connectorName = text(item.connector_name, 'name');
    return {
      marketId: id,
      connectorName,
      presentation: presentation(item, connectorName),
      category: optionalText(item.category, 'category', 120),
      installCount: integer(item.install_count, 'install count', 0),
    };
  });
  if (items.length > input.pageSize || new Set(items.map((item) => item.marketId)).size !== items.length)
    throw new Error('Invalid connector catalog item count or duplicate identity');
  const categories = catalog.facets.categories.map((value: unknown) => {
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('Invalid connector category');
    const facet = value as Record<string, unknown>;
    return {
      code: text(facet.code, 'category code', 120),
      label: text(facet.label, 'category label', 160),
      count: integer(facet.count, 'category count', 0),
    };
  });
  const page = integer(catalog.pages.current_page, 'current page', 1);
  const pageSize = integer(catalog.pages.page_size, 'page size', 1);
  if (page !== input.page || pageSize !== input.pageSize)
    throw new Error('Connector catalog pagination mismatch');
  return {
    items,
    categories,
    page,
    pageSize,
    total: integer(catalog.pages.total_size, 'total size', 0),
    lastPage: integer(catalog.pages.last_page, 'last page', 1),
  };
}

async function fetchOfficialCatalogItems(
  category: string | undefined,
  fetchImpl: typeof fetch,
): Promise<{ items: CatalogItem[]; categories: ConnectorCatalogPage['categories'] }> {
  const first = await fetchOfficialCatalogPage(
    { page: 1, pageSize: 20, ...(category ? { category } : {}) },
    fetchImpl,
  );
  const items = [...first.items];
  for (let page = 2; page <= first.lastPage; page += 1) {
    const next = await fetchOfficialCatalogPage(
      { page, pageSize: 20, ...(category ? { category } : {}) },
      fetchImpl,
    );
    items.push(...next.items);
  }
  if (new Set(items.map((item) => item.marketId)).size !== items.length)
    throw new Error('Invalid connector catalog item count or duplicate identity');
  return { items, categories: first.categories };
}

function paginateCatalog(
  items: CatalogItem[],
  categories: ConnectorCatalogPage['categories'],
  input: ConnectorCatalogInput,
): ConnectorCatalogPage {
  const total = items.length;
  const lastPage = Math.max(1, Math.ceil(total / input.pageSize) || 1);
  if (input.page > lastPage && total > 0) throw new Error('Connector catalog pagination mismatch');
  return {
    items: items.slice((input.page - 1) * input.pageSize, input.page * input.pageSize),
    categories,
    page: input.page,
    pageSize: input.pageSize,
    total,
    lastPage,
  };
}

export async function listOfficialConnectorCatalog(
  input: ConnectorCatalogInput,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<ConnectorCatalogPage> {
  if (Object.keys(input).some((key) => !CATALOG_FILTERS.has(key)))
    throw new Error('Unsupported connector catalog filter');
  integer(input.page, 'page', 1);
  integer(input.pageSize, 'page size', 1);
  if (input.pageSize > 20) throw new Error('Invalid connector catalog page size');
  const keyword = optionalText(input.keyword, 'keyword', 200);
  const category = optionalText(input.category, 'category', 120);
  if (!keyword) {
    return fetchOfficialCatalogPage(
      { page: input.page, pageSize: input.pageSize, ...(category ? { category } : {}) },
      fetchImpl,
    );
  }
  const catalog = await fetchOfficialCatalogItems(category || undefined, fetchImpl);
  const items = catalog.items.filter((item) => matchesOfficialKeyword(item, keyword));
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
  const categories = catalog.categories
    .map((facet) => ({ ...facet, count: counts.get(facet.code) ?? 0 }))
    .filter((facet) => facet.count > 0);
  return paginateCatalog(items, categories, input);
}

export async function describeOfficialConnector(
  marketId: string,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<ConnectorMarketDetail> {
  const id = text(marketId, 'market id', 120);
  if (!MARKET_ID.test(id)) throw new Error('Invalid connector market id');
  const detail = await qoderJson<Record<string, unknown>>(
    `/apphub/api/v1/marketplace/connectors/${encodeURIComponent(id)}/detail`,
    fetchImpl,
  );
  if (!detail || detail.connector_id !== id) throw new Error('Connector market identity mismatch');
  if (!Array.isArray(detail.clients) || !detail.clients.includes('qoderwake'))
    throw new Error('Connector does not support QoderWake');
  const connectorName = text(detail.connector_name, 'name');
  const config =
    detail.config && typeof detail.config === 'object' && !Array.isArray(detail.config)
      ? (detail.config as Record<string, unknown>)
      : {};
  return {
    marketId: id,
    connectorName,
    presentation: presentation(detail, connectorName),
    category: optionalText(detail.category, 'category', 120),
    version: optionalText(detail.version, 'version', 80) || '1.0.0',
    servers: servers(config.servers),
  };
}
