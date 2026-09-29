import { createHash } from 'node:crypto';
import { zipSync, strToU8 } from 'fflate';
import { describe, expect, it, vi } from 'vitest';
import { downloadOfficialPlugin } from '../src/v5-plugin-marketplace.ts';
import { inspectMarketPluginPackage } from '../../data-access/src/v3/plugin-package.ts';

const bytes = zipSync({
  '.qoder-plugin/plugin.json': strToU8(
    JSON.stringify({ name: 'design', displayName: 'Design', version: '1.0.0', skills: './skills' }),
  ),
  'skills/design/SKILL.md': strToU8(
    '---\nname: design\ndescription: Design a page.\n---\nUse intentional typography.',
  ),
});
const detail = {
  plugin_id: 'official_design',
  plugin_name: 'design',
  display_name: 'Design',
  display_name_cn: '设计',
  description: 'Design guidance.',
  description_cn: '设计指南。',
  author: 'Example',
  icon_url: 'https://example.com/icon.png',
  version: '1.0.0',
  clients: ['qoderwake'],
  file_size: String(bytes.length),
  file_hash: createHash('sha256').update(bytes).digest('hex'),
  download_url: 'https://qoder-skills.oss-accelerate.aliyuncs.com/public/extensions/plugin/design.zip',
};
function source(changes: Record<string, unknown> = {}, archive: Uint8Array = bytes) {
  return vi.fn<typeof fetch>(async (url, options) => {
    expect(options).toMatchObject({
      method: 'GET',
      credentials: 'omit',
      redirect: 'error',
      referrerPolicy: 'no-referrer',
    });
    expect(options?.headers).not.toHaveProperty('authorization');
    return String(url).endsWith('/detail')
      ? Response.json({ ...detail, ...changes })
      : new Response(Buffer.from(archive));
  });
}

describe('public plugin package acquisition', () => {
  it('downloads a verified immutable package consumable by native resource inspection', async () => {
    const fetcher = source();
    const result = await downloadOfficialPlugin('official_design', fetcher);
    expect(String(fetcher.mock.calls[0]![0])).toBe(
      'https://qoder.com/apphub/api/v1/marketplace/plugins/official_design/detail',
    );
    const inspected = await inspectMarketPluginPackage(result.bytes, {
      ...result.source,
      objectKey: 'plugins/design.zip',
    });
    expect(inspected.skills).toEqual([{ name: 'design', manifestPath: 'skills/design/SKILL.md' }]);
    expect(inspected.package.canonicalId).toBe('design@marketplace');
    expect(inspected.package.presentation).toEqual({
      displayName: 'Design',
      localizedName: '设计',
      description: 'Design guidance.',
      localizedDescription: '设计指南。',
      author: 'Example',
      iconUrl: 'https://example.com/icon.png',
    });
  });
  it.each([
    { description: {} },
    { display_name: false },
    { description_cn: 'x'.repeat(20001) },
    { icon_url: 'javascript:alert(1)' },
    { icon_url: 'https://secret@example.com/icon.png' },
    { plugin_id: 'other' },
    { clients: ['qoder'] },
    { file_hash: 'invalid' },
    { file_size: '-1' },
    { file_size: 51 * 1024 * 1024 },
    { plugin_name: '../escape' },
    { version: '' },
    { download_url: 'https://evil.example/pkg.zip' },
    { download_url: 'https://user:secret@qoder-skills.oss-accelerate.aliyuncs.com/pkg.zip' },
    { download_url: 'https://qoder-skills.oss-accelerate.aliyuncs.com/pkg.tgz' },
  ])('rejects invalid metadata without downloading: %j', async (changes) => {
    const fetcher = source(changes);
    await expect(downloadOfficialPlugin('official_design', fetcher)).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('accepts the second observed official bucket while retaining digest verification', async () => {
    const fetcher = source({
      download_url: 'https://qoder-mind.oss-accelerate.aliyuncs.com/plugins/public/design/latest/design.zip',
    });
    expect((await downloadOfficialPlugin('official_design', fetcher)).source.sha256).toBe(detail.file_hash);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it('rejects corruption, truncation and oversized streams', async () => {
    const corrupt = bytes.slice();
    corrupt[0] = corrupt[0]! ^ 1;
    await expect(downloadOfficialPlugin('official_design', source({}, corrupt))).rejects.toThrow(
      'digest mismatch',
    );
    await expect(downloadOfficialPlugin('official_design', source({}, bytes.slice(1)))).rejects.toThrow(
      'size mismatch',
    );
    await expect(downloadOfficialPlugin('official_design', source({ file_size: '1' }))).rejects.toThrow(
      'size policy',
    );
  });
  it('rejects invalid ids before requests and propagates upstream failure', async () => {
    const fetcher = source();
    await expect(downloadOfficialPlugin('../other', fetcher)).rejects.toThrow('market id');
    expect(fetcher).not.toHaveBeenCalled();
    await expect(
      downloadOfficialPlugin('official_design', async () => new Response('', { status: 503 })),
    ).rejects.toThrow('503');
  });
});
