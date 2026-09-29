import { describe, expect, it } from 'vitest';
import { Value } from 'typebox/value';
import { V3ProjectSourceInputSchema } from '../src/v3.ts';

describe('HTTPS project Git locators', () => {
  it('accepts repository paths with or without a .git suffix and an optional branch', () => {
    for (const locator of [
      'https://github.com/org/repo',
      'https://github.com/org/repo.git',
      'https://gitlab.com/org/group/repo',
    ]) {
      expect(Value.Check(V3ProjectSourceInputSchema, { kind: 'git_repository', locator })).toBe(true);
    }
  });
  it('rejects incomplete paths, whitespace, query strings and fragments', () => {
    for (const locator of [
      'https://github.com/org',
      'https://github.com/',
      'https://github.com/org/re po',
      'https://github.com/org/repo?ref=main',
      'https://github.com/org/repo#main',
    ]) {
      expect(Value.Check(V3ProjectSourceInputSchema, { kind: 'git_repository', locator })).toBe(false);
    }
  });
});
