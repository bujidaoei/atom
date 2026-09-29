import { describe, expect, it } from 'vitest';
import { resolveV3SkillReferencePrompt } from '../src/v3-skill-references.ts';
import {
  v3PluginReferenceToken,
  v3SkillReferenceSource,
  v3SkillReferenceToken,
  v3SkillReferences,
} from '../../product-contracts/src/v3-skill-reference.ts';

describe('menu Skill display references', () => {
  const source = v3SkillReferenceSource('bound-version');
  const token = v3SkillReferenceToken(source, 'Display Name');
  const resources = new Map([[source, { name: 'native-skill', filePath: '/bound/one/SKILL.md' }]]);

  it('resolves the bound source rather than trusting an editable display name', () => {
    const forged = v3SkillReferenceToken(source, 'Another Installed Skill');
    const prompt = resolveV3SkillReferencePrompt(`Language preference\n${forged} user request`, resources);
    expect(prompt).toContain('Language preference\n/native-skill user request');
    expect(prompt).toContain('/bound/one/SKILL.md');
    expect(prompt).not.toContain('Another Installed Skill');
  });

  it('preserves ordered multiple references, surrounding text and recovery/language context', () => {
    const second = v3SkillReferenceSource('second-version');
    const catalog = new Map([
      ...resources,
      [second, { name: 'second', filePath: '/bound/two/SKILL.md' }] as const,
    ]);
    const input = `Continue unfinished request\nLanguage: Chinese\n${token} first ${v3SkillReferenceToken(second, 'Second')} last`;
    const output = resolveV3SkillReferencePrompt(input, catalog);
    expect(output).toContain(
      'Continue unfinished request\nLanguage: Chinese\n/native-skill first /second last',
    );
    expect(output.indexOf('- native-skill:')).toBeLessThan(output.indexOf('- second:'));
    expect(v3SkillReferences(input).map(({ name }) => name)).toEqual(['Display Name', 'Second']);
  });

  it('refuses unavailable bound identities instead of falling back to a matching label', () => {
    expect(() =>
      resolveV3SkillReferencePrompt(v3SkillReferenceToken('unbound', 'native-skill'), resources),
    ).toThrow('not available in this Run');
  });

  it('resolves one loaded plugin skill from the official plugin capability token', () => {
    const token = v3PluginReferenceToken('frontend-design', 'Frontend Design');
    const prompt = resolveV3SkillReferencePrompt(
      `请使用 ${token}`,
      resources,
      new Map([
        [
          'frontend-design',
          [{ name: 'frontend-design:frontend-design', filePath: '/plugins/frontend-design/SKILL.md' }],
        ],
      ]),
    );
    expect(prompt).toContain('@frontend-design');
    expect(prompt).toContain('/plugins/frontend-design/SKILL.md');
    expect(prompt).not.toContain('[[capability:');
  });
  it('resolves a multi-skill plugin without choosing an arbitrary first skill', () => {
    const prompt = resolveV3SkillReferencePrompt(
      v3PluginReferenceToken('design', 'Forged label'),
      new Map(),
      new Map([
        [
          'design',
          [
            { name: 'design:research', filePath: '/verified/research/SKILL.md' },
            { name: 'design:review', filePath: '/verified/review/SKILL.md' },
          ],
        ],
      ]),
    );
    expect(prompt).toContain('@design');
    expect(prompt).toContain('/verified/research/SKILL.md');
    expect(prompt).toContain('/verified/review/SKILL.md');
    expect(prompt).not.toContain('Forged label');
    expect(() =>
      resolveV3SkillReferencePrompt(v3PluginReferenceToken('disabled', 'Design'), new Map(), new Map()),
    ).toThrow('not available');
  });

  it('preserves ordinary slash commands, malformed references and other capability kinds', () => {
    const input =
      '/native-skill /unknown [[capability:%]] [[capability:%5B%22plugin%22%2C%22id%22%2C%22name%22%5D]]';
    expect(resolveV3SkillReferencePrompt(input, resources)).toBe(input);
  });
});
