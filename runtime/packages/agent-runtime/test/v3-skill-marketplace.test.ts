import { describe, expect, it, vi } from 'vitest';
import { strToU8, zipSync } from 'fflate';

import {
  downloadV3OfficialSkill,
  getV3OfficialSkillMarketplaceDetail,
  listV3OfficialSkillMarketplace,
} from '../src/v3-skill-marketplace.ts';

describe('V3 official Skill Marketplace', () => {
  it.each([undefined, null, '', '   '])(
    'accepts absent README while retaining installable metadata: %s',
    async (readme) => {
      const detail = await getV3OfficialSkillMarketplaceDetail(
        'official_Q997tiPP',
        async () =>
          new Response(
            JSON.stringify({
              skill_id: 'official_Q997tiPP',
              skill_name: 'weekly-report-writer',
              version: '1.0.0',
              tags: ['OfficialSelection'],
              readme_content: readme,
            }),
          ),
      );
      expect(detail).toMatchObject({
        id: 'official_Q997tiPP',
        recommended: true,
        version: '1.0.0',
        readmeMarkdown: readme ?? '',
      });
    },
  );
  it.each([17, {}, 'x'.repeat(200001)])('rejects invalid README data: %#', async (readme) => {
    await expect(
      getV3OfficialSkillMarketplaceDetail(
        'official_Q997tiPP',
        async () =>
          new Response(
            JSON.stringify({
              skill_id: 'official_Q997tiPP',
              skill_name: 'weekly-report-writer',
              version: '1.0.0',
              readme_content: readme,
            }),
          ),
      ),
    ).rejects.toThrow('README is invalid');
  });
  it.each([
    { tags: undefined, expected: true },
    { tags: [], expected: false },
    { tags: ['qoder-vibe'], expected: false },
    { tags: ['OfficialSelection'], expected: true },
  ])(
    'keeps absent recommendation metadata distinct from explicit tags: $tags',
    async ({ tags, expected }) => {
      const page = await listV3OfficialSkillMarketplace(
        { page: 1, pageSize: 1, sort: 'hottest' },
        async (input) =>
          new Response(
            JSON.stringify(
              String(input).endsWith('/detail')
                ? {
                    skill_id: 'official_test',
                    tags: ['OfficialSelection'],
                    // Public detail metadata can lack README; badges must not depend on it.
                  }
                : {
                    skills: {
                      items: [{ skill_id: 'official_test', skill_name: 'test', tags }],
                      pages: { current_page: 1, page_size: 1, total_size: 1, last_page: 1 },
                    },
                  },
            ),
          ),
      );
      expect(page.items[0]?.recommended).toBe(expected);
    },
  );
  it('maps a validated Qoder catalog response and forwards dynamic filters', async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      expect(url.origin).toBe('https://qoder.com');
      expect(url.searchParams.get('client')).toBe('qoderwork');
      expect(url.searchParams.get('keyword')).toBe('research');
      expect(url.searchParams.get('category')).toBe('Knowledge');
      expect(url.searchParams.get('pagination.current_page')).toBe('2');
      return new Response(
        JSON.stringify({
          skills: {
            items: [
              {
                skill_id: 'official_beta',
                skill_name: 'beta-skill',
                display_name: 'Beta Skill',
                description: 'Second alphabetically.',
                author: 'Qoder',
                category: 'Knowledge',
                icon_url: '',
                install_count: 20,
                tags: ['OfficialSelection', 'qoder-vibe'],
                content_updated_at: '1786811088786',
              },
              {
                skill_id: 'official_alpha',
                skill_name: 'alpha-skill',
                display_name: 'Alpha Skill',
                description: 'First alphabetically.',
                author_name: 'Official Author',
                tags: [],
                category: 'Knowledge',
                icon_url: 'https://qoder-skills.oss-accelerate.aliyuncs.com/alpha.png',
                install_count: 10,
                content_updated_at: '1786811088787',
              },
            ],
            pages: { current_page: 2, page_size: 2, total_size: 4, last_page: 2 },
          },
        }),
        { headers: { 'content-type': 'application/json' } },
      );
    });

    await expect(
      listV3OfficialSkillMarketplace(
        {
          query: 'research',
          category: 'research-analysis',
          sort: 'name',
          page: 2,
          pageSize: 2,
        },
        fetchImpl,
      ),
    ).resolves.toMatchObject({
      page: 2,
      pageSize: 2,
      total: 4,
      lastPage: 2,
      items: [
        {
          id: 'official_alpha',
          name: 'Alpha Skill',
          author: 'Official Author',
          installCount: 10,
        },
        { id: 'official_beta', name: 'Beta Skill', author: 'Qoder', installCount: 20, recommended: true },
      ],
    });
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it('downloads only the package URL returned by the trusted Qoder detail endpoint', async () => {
    const archive = zipSync({
      'SKILL.md': strToU8('---\nname: verified-skill\ndescription: Verified package\n---\n\n# Verified\n'),
    });
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      if (url.hostname === 'qoder.com') {
        return new Response(
          JSON.stringify({
            skill_id: 'official_verified',
            skill_name: 'verified-skill',
            download_url:
              'https://qoder-skills.oss-accelerate.aliyuncs.com/public/verified-skill/latest/verified-skill.zip',
          }),
        );
      }
      expect(url.hostname).toBe('qoder-skills.oss-accelerate.aliyuncs.com');
      return new Response(archive, {
        headers: { 'content-type': 'application/zip', 'content-length': String(archive.byteLength) },
      });
    });

    const downloaded = await downloadV3OfficialSkill('official_verified', fetchImpl);
    expect(downloaded).toMatchObject({ fileName: 'verified-skill.zip', mediaType: 'application/zip' });
    expect(downloaded.bytes).toEqual(archive);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('maps the official detail metadata and complete README without truncation', async () => {
    const readme = `---\nname: deep-research\n---\n# Deep Research\n\n${'Verified evidence. '.repeat(400)}`;
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response(
          JSON.stringify({
            skill_id: 'official03866510',
            skill_name: 'deep-research',
            display_name: 'deep-research',
            description: 'Conduct systematic deep research with source verification.',
            author: 'Jose-Luis-Nunez',
            author_name: 'Jose-Luis-Nunez',
            category: 'research-analysis',
            icon_url: '',
            install_count: 30_560,
            updated_at: '1786811088786',
            version: '1.0.0',
            tags: ['OfficialSelection'],
            readme_content: readme,
          }),
        ),
    );

    await expect(getV3OfficialSkillMarketplaceDetail('official03866510', fetchImpl)).resolves.toEqual({
      id: 'official03866510',
      name: 'deep-research',
      localizedName: null,
      description: 'Conduct systematic deep research with source verification.',
      localizedDescription: null,
      author: 'Jose-Luis-Nunez',
      authorName: 'Jose-Luis-Nunez',
      category: 'research-analysis',
      iconUrl: null,
      installCount: 30_560,
      updatedAt: new Date(1_786_811_088_786).toISOString(),
      version: '1.0.0',
      recommended: true,
      readmeMarkdown: readme,
    });
  });

  it('rejects a Marketplace detail response that points outside the official package host', async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response(
          JSON.stringify({
            skill_id: 'official_untrusted',
            skill_name: 'untrusted-skill',
            download_url: 'https://example.com/untrusted.zip',
          }),
        ),
    );

    await expect(downloadV3OfficialSkill('official_untrusted', fetchImpl)).rejects.toThrow(
      'download URL is not trusted',
    );
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});
