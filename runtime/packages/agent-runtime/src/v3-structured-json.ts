export function unwrapSingleJsonFence(value: string): string | undefined {
  const match = /^```json[\t ]*\r?\n([\s\S]*?)\r?\n```$/iu.exec(value.trim());
  return match?.[1]?.trim();
}
