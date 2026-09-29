import { describe, expect, it } from 'vitest';

import { readFile } from 'node:fs/promises';

import {
  resolveV3ResponseLanguage,
  withV3ResponseLanguage,
  withV3ResponseLanguagePrompt,
} from '../src/v3-response-language.ts';

describe('V3 response language', () => {
  it('adds an explicit recoverable system instruction for the selected language', () => {
    expect(withV3ResponseLanguage('Base instructions', 'zh-CN')).toBe(
      'Base instructions\n\n## Default response language\nRespond to the user in Simplified Chinese unless the user explicitly asks for another language.',
    );
    expect(withV3ResponseLanguage('Base instructions', 'en')).toBe(
      'Base instructions\n\n## Default response language\nRespond to the user in English unless the user explicitly asks for another language.',
    );
  });

  it('does not alter the system prompt when no preference was persisted', () => {
    expect(withV3ResponseLanguage('Base instructions', undefined)).toBe('Base instructions');
  });

  it('adds the preference to the invisible execution prompt without changing persisted user content', () => {
    expect(withV3ResponseLanguagePrompt('Original user request', 'zh-CN')).toBe(
      '[Persisted response-language preference: reply in Simplified Chinese unless this message explicitly requests another language.]\n\nOriginal user request',
    );
    expect(withV3ResponseLanguagePrompt('Original user request', undefined)).toBe('Original user request');
  });

  it('treats the predominant supported language of the latest request as an explicit override', () => {
    expect(resolveV3ResponseLanguage('请只回答这个问题，并简要说明原因。', 'en')).toBe('zh-CN');
    expect(
      resolveV3ResponseLanguage('Please answer this question and explain the reason briefly.', 'zh-CN'),
    ).toBe('en');
    expect(resolveV3ResponseLanguage('请为这个 API health endpoint 给出两个改进建议。', 'en')).toBe('zh-CN');
    expect(resolveV3ResponseLanguage('2 + 3 * 4', 'en')).toBe('en');
    expect(resolveV3ResponseLanguage('2 + 3 * 4', 'zh-CN')).toBe('zh-CN');
  });

  it('keeps an explicit supported-language request authoritative over predominance and preference', () => {
    expect(resolveV3ResponseLanguage('请用英文回答这个问题，并说明理由。', 'zh-CN')).toBe('en');
    expect(resolveV3ResponseLanguage('请仅使用简体中文输出最终答案。', 'en')).toBe('zh-CN');
    expect(resolveV3ResponseLanguage('Please answer this question in Simplified Chinese.', 'en')).toBe(
      'zh-CN',
    );
    expect(resolveV3ResponseLanguage('Please reply in English only.', 'zh-CN')).toBe('en');
  });

  it('uses the same resolved language before Cloud and Desktop prompt construction', async () => {
    const [cloud, desktop] = await Promise.all([
      readFile('services/cloud-worker/src/v3-run-worker.ts', 'utf8'),
      readFile('apps/desktop/src/v3-product-host.ts', 'utf8'),
    ]);
    for (const source of [cloud, desktop]) {
      expect(source).toContain('resolveV3ResponseLanguage(work.prompt, work.responseLanguage)');
      expect(source).toContain('withV3ResponseLanguagePrompt(runtimePrompt, effectiveResponseLanguage)');
    }
  });
});
