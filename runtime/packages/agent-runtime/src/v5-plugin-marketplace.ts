import type {
  PluginCatalogInput,
  PluginCatalogPage,
  PluginMarketComposition,
  PluginPresentation,
} from '../../product-contracts/src/v5-plugins.ts';
import { createHash } from 'node:crypto';
import { downloadQoderPackage, qoderJson } from './qoder-marketplace-transport.ts';

const MAX_PLUGIN_BYTES = 50 * 1024 * 1024;

function text(value: unknown, field: string, limit = 160): string {
  if (typeof value !== 'string' || !value.trim() || value.length > limit)
    throw new Error(`Qoder plugin ${field} is invalid`);
  return value.trim();
}

function optionalText(value: unknown, field: string, limit: number): string {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value !== 'string' || value.length > limit) throw new Error(`Qoder plugin ${field} is invalid`);
  return value.trim();
}

function presentation(detail: Record<string, unknown>, pluginName: string): PluginPresentation {
  const icon = optionalText(detail.icon_url, 'icon URL', 2000);
  let iconUrl: string | null = null;
  if (icon) {
    const url = new URL(icon);
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Invalid plugin icon URL');
    iconUrl = url.href;
  }
  return {
    displayName: optionalText(detail.display_name, 'display name', 160) || pluginName,
    localizedName: optionalText(detail.display_name_cn, 'localized name', 160) || null,
    description: optionalText(detail.description, 'description', 20000),
    localizedDescription: optionalText(detail.description_cn, 'localized description', 20000) || null,
    author:
      optionalText(detail.author_name, 'author name', 200) || optionalText(detail.author, 'author', 200),
    iconUrl,
  };
}

// Product distribution adapter only. Pi remains responsible for resource loading
// and execution; downloaded package contents confer no execution authority.
export async function downloadOfficialPlugin(
  marketId: string,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
) {
  if (!/^[A-Za-z0-9_-]{3,120}$/u.test(marketId)) throw new Error('Invalid plugin market id');
  const detail = await qoderJson<Record<string, unknown>>(
    `/apphub/api/v1/marketplace/plugins/${encodeURIComponent(marketId)}/detail`,
    fetchImpl,
  );
  if (!detail || detail.plugin_id !== marketId) throw new Error('Plugin market identity mismatch');
  if (!Array.isArray(detail.clients) || !detail.clients.includes('qoderwake'))
    throw new Error('Plugin does not support QoderWake');
  const pluginName = text(detail.plugin_name, 'name');
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(pluginName)) throw new Error('Invalid plugin name');
  const metadata = presentation(detail, pluginName);
  const version = text(detail.version, 'version', 80);
  const sha256 = text(detail.file_hash, 'digest', 64);
  if (!/^[a-f0-9]{64}$/u.test(sha256)) throw new Error('Invalid plugin digest');
  const size =
    typeof detail.file_size === 'string' && /^\d+$/u.test(detail.file_size)
      ? Number(detail.file_size)
      : detail.file_size;
  if (typeof size !== 'number' || !Number.isSafeInteger(size) || size < 1 || size > MAX_PLUGIN_BYTES)
    throw new Error('Plugin size exceeds policy or is invalid');
  const url = text(detail.download_url, 'download URL', 2000);
  if (!new URL(url).pathname.endsWith('.zip')) throw new Error('Plugin package must be ZIP');
  const downloaded = await downloadQoderPackage(url, size, fetchImpl);
  if (downloaded.bytes.byteLength !== size) throw new Error('Plugin package size mismatch');
  if (createHash('sha256').update(downloaded.bytes).digest('hex') !== sha256)
    throw new Error('Plugin package digest mismatch');
  return {
    ...downloaded,
    source: {
      marketId,
      canonicalId: `${pluginName}@marketplace`,
      pluginName,
      version,
      sha256,
      presentation: metadata,
    },
  };
}

function integer(value: unknown, field: string, minimum: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum)
    throw new Error(`Invalid plugin catalog ${field}`);
  return value;
}

function constituents(value: unknown, field: string): PluginMarketComposition['skills'] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 100) throw new Error(`Invalid plugin ${field}`);
  return value.map((entry) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry))
      throw new Error(`Invalid plugin ${field}`);
    const record = entry as Record<string, unknown>;
    const name =
      optionalText(record.name, `${field} name`, 160) || optionalText(record.id, `${field} id`, 160);
    if (!name) throw new Error(`Invalid plugin ${field}`);
    const localized = optionalText(record.description_cn, `${field} description`, 20_000);
    return {
      name,
      description: localized || optionalText(record.description, `${field} description`, 20_000),
    };
  });
}

/** Public catalog composition used by the installed-plugin detail dialog. Does not download the package. */
export async function describeOfficialPlugin(
  marketId: string,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<Omit<PluginMarketComposition, 'readme'>> {
  if (!/^[A-Za-z0-9_-]{3,120}$/u.test(marketId)) throw new Error('Invalid plugin market id');
  const detail = await qoderJson<Record<string, unknown>>(
    `/apphub/api/v1/marketplace/plugins/${encodeURIComponent(marketId)}/detail`,
    fetchImpl,
  );
  if (!detail || detail.plugin_id !== marketId) throw new Error('Plugin market identity mismatch');
  if (!Array.isArray(detail.clients) || !detail.clients.includes('qoderwake'))
    throw new Error('Plugin does not support QoderWake');
  return {
    version: text(detail.version, 'version', 80),
    category: optionalText(detail.category, 'category', 120),
    installCount: integer(detail.install_count, 'install count', 0),
    skills: constituents(detail.skills, 'skills'),
    commands: constituents(detail.commands, 'commands'),
    connectors: constituents(detail.connectors, 'connectors'),
  };
}

const CATALOG_FILTERS = new Set(['page', 'pageSize', 'category', 'keyword', 'featured']);

/** Official `/api/plugin-market?featured=true` identities observed 2026-09-22. */
export const officialFeaturedPluginIds = [
  'official_Svz0Sn6W',
  'official_33BiDFUM',
  'qoder-cloud-agents',
  'product-design',
  'product-management',
  'frontend-design',
  'official_r81O9jeW',
  'official_XWePpFwk',
  'official_N5DVzv5m',
  'slidev',
  '1945ab9d-2d90-4f94-b73e-fae24a0f0ac3',
  '3b716517-d46a-4721-a674-c96802b76744',
  'mobile-use',
] as const;

const featuredIds = new Set<string>(officialFeaturedPluginIds);

type CatalogItem = PluginCatalogPage['items'][number];

function matchesOfficialKeyword(item: CatalogItem, keyword: string): boolean {
  const needle = keyword.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    item.marketId,
    item.pluginName,
    item.presentation.displayName,
    item.presentation.localizedName ?? '',
    item.presentation.author,
  ].some((value) => value.toLocaleLowerCase().includes(needle));
}

async function fetchOfficialCatalogPage(
  input: { page: number; pageSize: number; category?: string },
  fetchImpl: typeof fetch,
): Promise<PluginCatalogPage> {
  const parameters = new URLSearchParams({
    extension_types: 'plugin',
    client: 'qoderwake',
    sort: 'hot',
    include_facets: 'true',
    'pagination.current_page': String(input.page),
    'pagination.page_size': String(input.pageSize),
  });
  const category = optionalText(input.category, 'category', 120);
  if (category) parameters.set('category', category);
  const response = await qoderJson<{
    plugins?: {
      items?: unknown;
      pages?: Record<string, unknown>;
      facets?: { categories?: unknown };
    };
  }>(`/apphub/api/v1/marketplace/catalog/extensions?${parameters}`, fetchImpl);
  const catalog = response?.plugins;
  if (
    !catalog ||
    !Array.isArray(catalog.items) ||
    !catalog.pages ||
    !Array.isArray(catalog.facets?.categories)
  )
    throw new Error('Invalid plugin catalog response');
  const items = catalog.items.map((value: unknown) => {
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('Invalid plugin catalog item');
    const item = value as Record<string, unknown>;
    if (!Array.isArray(item.clients) || !item.clients.includes('qoderwake'))
      throw new Error('Plugin catalog client mismatch');
    const marketId = text(item.plugin_id, 'market id', 120);
    if (!/^[A-Za-z0-9_-]{3,120}$/u.test(marketId)) throw new Error('Invalid plugin market id');
    const pluginName = text(item.plugin_name, 'name');
    return {
      marketId,
      pluginName,
      presentation: presentation(item, pluginName),
      category: optionalText(item.category, 'category', 120),
      installCount: integer(item.install_count, 'install count', 0),
      recommended: featuredIds.has(marketId),
    };
  });
  if (items.length > input.pageSize || new Set(items.map((item) => item.marketId)).size !== items.length)
    throw new Error('Invalid plugin catalog item count or duplicate identity');
  const categories = catalog.facets.categories.map((value: unknown) => {
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('Invalid plugin category');
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
    throw new Error('Plugin catalog pagination mismatch');
  return {
    items,
    // The public service includes taxonomy entries unused by this client.
    // Keep the active market facets; keyword filtering may later make them zero.
    categories: categories.filter((facet) => facet.count > 0),
    page,
    pageSize,
    total: integer(catalog.pages.total_size, 'total size', 0),
    lastPage: integer(catalog.pages.last_page, 'last page', 1),
  };
}

async function fetchOfficialCatalogItems(
  category: string | undefined,
  fetchImpl: typeof fetch,
): Promise<{ items: CatalogItem[]; categories: PluginCatalogPage['categories'] }> {
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
    throw new Error('Invalid plugin catalog item count or duplicate identity');
  return { items, categories: first.categories };
}

function paginateCatalog(
  items: CatalogItem[],
  categories: PluginCatalogPage['categories'],
  input: PluginCatalogInput,
): PluginCatalogPage {
  const total = items.length;
  const lastPage = Math.max(1, Math.ceil(total / input.pageSize) || 1);
  if (input.page > lastPage && total > 0) throw new Error('Plugin catalog pagination mismatch');
  return {
    items: items.slice((input.page - 1) * input.pageSize, input.page * input.pageSize),
    categories,
    page: input.page,
    pageSize: input.pageSize,
    total,
    lastPage,
  };
}

export async function listOfficialPluginCatalog(
  input: PluginCatalogInput,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<PluginCatalogPage> {
  if (Object.keys(input).some((key) => !CATALOG_FILTERS.has(key)))
    throw new Error('Unsupported plugin catalog filter');
  integer(input.page, 'page', 1);
  integer(input.pageSize, 'page size', 1);
  if (input.pageSize > 20) throw new Error('Invalid plugin catalog page size');
  const keyword = optionalText(input.keyword, 'keyword', 200);
  if (keyword.length > 200) throw new Error('Invalid plugin catalog keyword');
  const category = optionalText(input.category, 'category', 120);
  if (input.featured && category) throw new Error('Unsupported plugin catalog filter');
  if (!input.featured && !keyword) {
    return fetchOfficialCatalogPage(
      { page: input.page, pageSize: input.pageSize, ...(category ? { category } : {}) },
      fetchImpl,
    );
  }
  const catalog = await fetchOfficialCatalogItems(
    input.featured ? undefined : category || undefined,
    fetchImpl,
  );
  let items = catalog.items;
  if (input.featured) items = items.filter((item) => featuredIds.has(item.marketId));
  if (keyword) items = items.filter((item) => matchesOfficialKeyword(item, keyword));
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
  const categories = catalog.categories.map((facet) => ({ ...facet, count: counts.get(facet.code) ?? 0 }));
  return paginateCatalog(items, categories, input);
}
