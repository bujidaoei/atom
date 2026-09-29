const USER_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export const AI_GATEWAY_VIRTUAL_KEY_PURPOSE_PREFIX = 'ai-gateway-virtual-key:';

export function isAiGatewayVirtualKey(value: unknown): value is string {
  if (typeof value !== 'string' || value.length < 8 || value.length > 512 || /\s/u.test(value)) {
    return false;
  }
  for (const character of value) {
    const codePoint = character.codePointAt(0)!;
    if (codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f)) return false;
  }
  return true;
}

/**
 * Return the only user-facing representation allowed for a gateway key.
 * Keep the first and last two characters for recognition and replace every
 * interior character with a star.  The minimum four-star interior preserves
 * a stable, non-reversible shape even for the shortest accepted key.
 */
export function maskAiGatewayVirtualKey(value: string): string {
  if (!isAiGatewayVirtualKey(value)) throw new Error('invalid AI gateway virtual key');
  return `${value.slice(0, 2)}${'*'.repeat(Math.max(value.length - 4, 4))}${value.slice(-2)}`;
}

export function aiGatewayVirtualKeyPurpose(userId: string): string {
  if (!USER_ID_PATTERN.test(userId)) throw new Error('authenticated user id is invalid');
  return `${AI_GATEWAY_VIRTUAL_KEY_PURPOSE_PREFIX}${userId.toLowerCase()}`;
}
