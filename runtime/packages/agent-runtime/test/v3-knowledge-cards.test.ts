import { describe, expect, it, vi } from 'vitest';

import { generateKnowledgeCards } from '../src/v3-knowledge-cards.ts';
import { createEnterpriseAiGatewayClient } from '../src/enterprise-ai-gateway.ts';

const options = (fetcher: typeof fetch) => ({
  gateway: createEnterpriseAiGatewayClient(
    {
      baseUrl: 'https://gateway.test/v1',
      masterKey: 'test-api-key',
      model: 'gateway-model',
      requestTimeoutMs: 5_000,
    },
    fetcher,
  ),
});

describe('V3 Knowledge card generation', () => {
  it('asks the enterprise gateway for source-grounded JSON and parses dynamic cards', async () => {
    const fetcher = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as {
        messages: Array<{ role: string; content: string }>;
      };
      expect(body.messages[0]?.content).toContain('introduce no facts that are absent');
      expect(body.messages[1]?.content).toContain('Dynamic hypertension guidance');
      expect(body.messages[1]?.content).toContain('Measure blood pressure twice');
      return new Response(
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  cards: [
                    {
                      title: 'Dynamic measurement protocol',
                      keywords: ['blood pressure', 'measurement'],
                      contentMarkdown: '## Protocol\n\nMeasure blood pressure twice.',
                    },
                  ],
                }),
              },
            },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }) as unknown as typeof fetch;

    await expect(
      generateKnowledgeCards(
        'Dynamic hypertension guidance',
        'Measure blood pressure twice.',
        options(fetcher),
      ),
    ).resolves.toEqual({
      cards: [
        {
          title: 'Dynamic measurement protocol',
          keywords: ['blood pressure', 'measurement'],
          contentMarkdown: '## Protocol\n\nMeasure blood pressure twice.',
        },
      ],
      usage: null,
      providerCorrelationId: null,
    });
    expect(fetcher).toHaveBeenCalledWith(
      'https://gateway.test/v1/chat/completions',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('applies the persisted compilation template before owner instructions', async () => {
    const requests: Array<{ messages: Array<{ role: string; content: string }> }> = [];
    const fetcher = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      requests.push(
        JSON.parse(String(init?.body)) as {
          messages: Array<{ role: string; content: string }>;
        },
      );
      return new Response(
        JSON.stringify({
          choices: [
            {
              message: {
                content:
                  '{"cards":[{"title":"Grounded","keywords":["source"],"contentMarkdown":"## Evidence\\n\\nGrounded."}]}',
              },
            },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }) as unknown as typeof fetch;

    for (const compilationTemplate of ['llm_wiki', 'multi_repo_wiki', 'custom'] as const) {
      await generateKnowledgeCards('Source', 'Grounded.', {
        ...options(fetcher),
        compilationTemplate,
        appendPrompt: 'OWNER-EVIDENCE-0825',
      });
    }

    const systems = requests.map(({ messages }) => messages[0]!.content);
    expect(systems[0]).toContain('TEMPLATE INSTRUCTIONS (LLM Wiki)');
    expect(systems[1]).toContain('TEMPLATE INSTRUCTIONS (Multi repo Wiki)');
    expect(systems[1]).toContain('Summary, Relation type, Direction, Repositories');
    expect(systems[2]).toContain('TEMPLATE INSTRUCTIONS (Custom)');
    for (const system of systems) {
      expect(system.indexOf('TEMPLATE INSTRUCTIONS')).toBeLessThan(
        system.indexOf('OWNER COMPILATION INSTRUCTIONS'),
      );
      expect(system).toContain('OWNER-EVIDENCE-0825');
    }
    expect(requests.every(({ messages }) => !messages[1]!.content.includes('OWNER-EVIDENCE-0825'))).toBe(
      true,
    );
  });

  it('accepts a fenced JSON response but rejects duplicate or incomplete cards', async () => {
    const response = (content: string) =>
      vi.fn(
        async () =>
          new Response(JSON.stringify({ choices: [{ message: { content } }] }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
      ) as unknown as typeof fetch;

    await expect(
      generateKnowledgeCards(
        'Source',
        'Content',
        options(
          response(
            '```json\n{"cards":[{"title":"One","keywords":["source"],"contentMarkdown":"Grounded"}]}\n```',
          ),
        ),
      ),
    ).resolves.toMatchObject({ cards: [expect.objectContaining({ title: 'One' })] });

    await expect(
      generateKnowledgeCards(
        'Source',
        'Content',
        options(
          response(
            '{"cards":[{"title":"Same","keywords":["a"],"contentMarkdown":"First"},{"title":"same","keywords":["b"],"contentMarkdown":"Second"}]}',
          ),
        ),
      ),
    ).rejects.toThrow('incomplete or duplicate');
  });

  it('surfaces model and transport failures without manufacturing fallback cards', async () => {
    const malformed = vi.fn(
      async () =>
        new Response(JSON.stringify({ choices: [{ message: { content: '{bad' } }] }), { status: 200 }),
    ) as unknown as typeof fetch;
    await expect(generateKnowledgeCards('Source', 'Content', options(malformed))).rejects.toThrow(
      'malformed JSON',
    );

    const unavailable = vi.fn(
      async () => new Response('unavailable', { status: 503 }),
    ) as unknown as typeof fetch;
    await expect(generateKnowledgeCards('Source', 'Content', options(unavailable))).rejects.toThrow(
      'HTTP 503',
    );
  });
});
