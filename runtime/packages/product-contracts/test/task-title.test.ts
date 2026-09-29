import { expect, it } from 'vitest';
import { Value } from 'typebox/value';
import { validateTaskTitle } from '../src/task-title.ts';
import { V3RenameTaskSchema, V3ConversationSchema, V3TaskSchema } from '../src/v3.ts';

it('accepts the observed ASCII and multibyte limits through rename and read contracts', () => {
  for (const title of ['A'.repeat(255), '测'.repeat(85), '😀'.repeat(63) + 'ABC']) {
    expect(() => validateTaskTitle(title)).not.toThrow();
    expect(Value.Check(V3RenameTaskSchema, { title, expectedUpdatedAt: '2026-09-25T00:00:00.000Z' })).toBe(
      true,
    );
    expect(Value.Check(V3ConversationSchema.properties.title, title)).toBe(true);
    expect(Value.Check(V3TaskSchema.properties.title, title)).toBe(true);
    expect(Value.Check(V3TaskSchema.properties.conversationTitle, title)).toBe(true);
  }
});
it('rejects overlong UTF8 content and empty trimmed names', () => {
  for (const title of ['A'.repeat(256), '测'.repeat(86), '😀'.repeat(64), '   '])
    expect(() => validateTaskTitle(title)).toThrow('INVALID_ARGUMENT');
});

it('uses the observed private input length without relaxing group byte validation', () => {
  const title = '测'.repeat(255);
  expect(() => validateTaskTitle(title, 'waker')).not.toThrow();
  expect(() => validateTaskTitle(title, 'group')).toThrow('INVALID_ARGUMENT');
  expect(() => validateTaskTitle(title + '测', 'waker')).toThrow('INVALID_ARGUMENT');
});
