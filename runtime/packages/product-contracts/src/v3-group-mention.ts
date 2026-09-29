/** Visible member token used by the official composer (whitespace is removed). */
export function v3GroupMentionTokenName(name: string): string {
  return name.replace(/\s+/gu, '');
}
