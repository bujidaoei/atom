/** Official group rename limits bytes; private rename accepts 255 Chinese characters. */
export const TASK_TITLE_MAX_BYTES = 255;

export function validateTaskTitle(title: string, subjectType?: string): void {
  const trimmed = title.trim();
  const length = subjectType === 'waker' ? trimmed.length : new TextEncoder().encode(trimmed).length;
  if (!trimmed || length > TASK_TITLE_MAX_BYTES) {
    throw new Error('INVALID_ARGUMENT');
  }
}
