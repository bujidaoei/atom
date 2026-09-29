import { qoderJson, downloadQoderPackage } from './qoder-marketplace-transport.ts';
import type { V3SkillMarketplaceInput } from '../../product-contracts/src/v3-ports.ts';
import type {
  V3SkillMarketplaceDetail,
  V3SkillMarketplaceItem,
  V3SkillMarketplacePage,
} from '../../product-contracts/src/v3.ts';

const MAX_SKILL_BYTES = 20 * 1024 * 1024;

const CATEGORY_QUERY: Readonly<
  Record<NonNullable<V3SkillMarketplaceInput['category']>, { key: 'category' | 'output'; value: string }>
> = {
  devops: { key: 'category', value: 'DevOps' },
  productivity: { key: 'category', value: 'Productivity' },
  'research-analysis': { key: 'category', value: 'Knowledge' },
  'content-creation': { key: 'category', value: 'Content Creation' },
  'design-ui': { key: 'category', value: 'Design' },
  'data-ai': { key: 'category', value: 'Database & Analytics' },
  'docs-writing': { key: 'output', value: 'document' },
};

interface QoderCatalogItem {
  tags?: unknown;
  skill_id?: unknown;
  skill_name?: unknown;
  skill_name_cn?: unknown;
  display_name?: unknown;
  description?: unknown;
  description_cn?: unknown;
  author?: unknown;
  author_name?: unknown;
  category?: unknown;
  icon_url?: unknown;
  install_count?: unknown;
  content_updated_at?: unknown;
}

interface QoderCatalogResponse {
  skills?: {
    items?: unknown;
    pages?: {
      current_page?: unknown;
      page_size?: unknown;
      total_size?: unknown;
      last_page?: unknown;
    };
  };
}

interface QoderSkillDetail {
  skill_id?: unknown;
  skill_name?: unknown;
  skill_name_cn?: unknown;
  display_name?: unknown;
  description?: unknown;
  description_cn?: unknown;
  author?: unknown;
  author_name?: unknown;
  category?: unknown;
  icon_url?: unknown;
  install_count?: unknown;
  updated_at?: unknown;
  version?: unknown;
  tags?: unknown;
  readme_content?: unknown;
  download_url?: unknown;
}

function requiredText(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== 'string' || !value.trim() || value.length > maxLength) {
    throw new Error(`Qoder Marketplace ${field} is invalid`);
  }
  return value.trim();
}

function optionalText(value: unknown, field: string, maxLength: number): string {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value !== 'string' || value.length > maxLength) {
    throw new Error(`Qoder Marketplace ${field} is invalid`);
  }
  return value.trim();
}

function integer(value: unknown, field: string, minimum: number): number {
  if (!Number.isInteger(value) || Number(value) < minimum) {
    throw new Error(`Qoder Marketplace ${field} is invalid`);
  }
  return Number(value);
}

function nullableIcon(value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null;
  const url = new URL(value);
  return url.protocol === 'https:' ? url.href : null;
}

function updatedAt(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{10,16}$/u.test(value)) return null;
  const date = new Date(Number(value));
  return Number.isNaN(date.valueOf()) ? null : date.toISOString();
}

function localizedText(value: unknown, field: string, maxLength: number): string | null {
  const text = optionalText(value, field, maxLength);
  return text ? text : null;
}

function catalogItem(
  value: unknown,
): Omit<V3SkillMarketplaceItem, 'recommended'> & { recommended?: boolean } {
  if (!value || typeof value !== 'object') throw new Error('Qoder Marketplace item is invalid');
  const item = value as QoderCatalogItem;
  return {
    id: requiredText(item.skill_id, 'Skill id', 120),
    name: requiredText(item.display_name || item.skill_name, 'Skill name', 160),
    localizedName: localizedText(item.skill_name_cn, 'localized name', 160),
    description: optionalText(item.description, 'description', 20_000),
    localizedDescription: localizedText(item.description_cn, 'localized description', 20_000),
    author:
      typeof item.author_name === 'string' && item.author_name.trim()
        ? optionalText(item.author_name, 'author', 200)
        : optionalText(item.author, 'author', 200),
    category: optionalText(item.category, 'category', 120),
    iconUrl: nullableIcon(item.icon_url),
    installCount: integer(item.install_count ?? 0, 'install count', 0),
    updatedAt: updatedAt(item.content_updated_at),
    ...(item.tags === undefined ? {} : { recommended: recommended(item.tags) }),
  };
}

function recommended(value: unknown): boolean {
  if (value !== undefined && (!Array.isArray(value) || value.length > 50)) {
    throw new Error('Qoder Marketplace tags are invalid');
  }
  return ((value ?? []) as unknown[])
    .map((tag) => requiredText(tag, 'tag', 120))
    .includes('OfficialSelection');
}

export async function listV3OfficialSkillMarketplace(
  input: V3SkillMarketplaceInput,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<V3SkillMarketplacePage> {
  if (!Number.isInteger(input.page) || input.page < 1) throw new Error('Marketplace page is invalid');
  if (!Number.isInteger(input.pageSize) || input.pageSize < 1 || input.pageSize > 24) {
    throw new Error('Marketplace page size is invalid');
  }
  if (input.query && input.query.length > 200) throw new Error('Marketplace search is invalid');
  const parameters = new URLSearchParams({
    extension_types: 'skill',
    client: 'qoderwork',
    sort: input.sort === 'newest' ? 'latest' : 'hot',
    'pagination.current_page': String(input.page),
    'pagination.page_size': String(input.pageSize),
  });
  if (input.query?.trim()) parameters.set('keyword', input.query.trim());
  if (input.category) {
    const category = CATEGORY_QUERY[input.category];
    parameters.set(category.key, category.value);
  }
  const response = await qoderJson<QoderCatalogResponse>(
    `/apphub/api/v1/marketplace/catalog/extensions?${parameters}`,
    fetchImpl,
  );
  if (!response.skills || !Array.isArray(response.skills.items) || !response.skills.pages) {
    throw new Error('Qoder Marketplace catalog response is invalid');
  }
  const items = await Promise.all(
    response.skills.items.map(async (value) => {
      const item = catalogItem(value);
      if (item.recommended !== undefined) return { ...item, recommended: item.recommended };
      const detail = await skillDetail(item.id, fetchImpl);
      return { ...item, recommended: recommended(detail.tags) };
    }),
  );
  if (input.sort === 'name') items.sort((left, right) => left.name.localeCompare(right.name, 'en'));
  const pages = response.skills.pages;
  return {
    items,
    page: integer(pages.current_page, 'current page', 1),
    pageSize: integer(pages.page_size, 'page size', 1),
    total: integer(pages.total_size, 'total size', 0),
    lastPage: integer(pages.last_page, 'last page', 1),
  };
}

async function skillDetail(marketplaceSkillId: string, fetchImpl: typeof fetch): Promise<QoderSkillDetail> {
  if (!/^[A-Za-z0-9_-]{3,120}$/u.test(marketplaceSkillId)) {
    throw new Error('Qoder Marketplace Skill id is invalid');
  }
  const detail = await qoderJson<QoderSkillDetail>(
    `/apphub/api/v1/marketplace/skills/${encodeURIComponent(marketplaceSkillId)}/detail`,
    fetchImpl,
  );
  if (detail.skill_id !== marketplaceSkillId) throw new Error('Qoder Marketplace Skill identity mismatch');
  return detail;
}

export async function getV3OfficialSkillMarketplaceDetail(
  marketplaceSkillId: string,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<V3SkillMarketplaceDetail> {
  const detail = await skillDetail(marketplaceSkillId, fetchImpl);
  const readme = detail.readme_content ?? '';
  if (typeof readme !== 'string' || readme.length > 200_000) {
    throw new Error('Qoder Marketplace README is invalid');
  }
  return {
    id: requiredText(detail.skill_id, 'Skill id', 120),
    name: requiredText(detail.display_name || detail.skill_name, 'Skill name', 160),
    localizedName: localizedText(detail.skill_name_cn, 'localized name', 160),
    description: optionalText(detail.description, 'description', 20_000),
    localizedDescription: localizedText(detail.description_cn, 'localized description', 20_000),
    author: optionalText(detail.author, 'author', 200),
    authorName:
      typeof detail.author_name === 'string' && detail.author_name.trim()
        ? optionalText(detail.author_name, 'author name', 200)
        : optionalText(detail.author, 'author', 200),
    category: optionalText(detail.category, 'category', 120),
    iconUrl: nullableIcon(detail.icon_url),
    installCount: integer(detail.install_count ?? 0, 'install count', 0),
    updatedAt: updatedAt(detail.updated_at),
    version: requiredText(detail.version, 'version', 80),
    recommended: recommended(detail.tags),
    readmeMarkdown: readme,
  };
}

export async function downloadV3OfficialSkill(
  marketplaceSkillId: string,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<{
  fileName: string;
  mediaType: 'application/zip' | 'application/gzip';
  bytes: Uint8Array;
}> {
  const detail = await skillDetail(marketplaceSkillId, fetchImpl);
  requiredText(detail.skill_name, 'Skill name', 160);
  return downloadQoderPackage(
    requiredText(detail.download_url, 'download URL', 2_000),
    MAX_SKILL_BYTES,
    fetchImpl,
  );
}
