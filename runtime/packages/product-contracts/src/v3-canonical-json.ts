/**
 * Serialize JSON with PostgreSQL jsonb's deterministic object-key ordering and
 * whitespace. Configuration hashes use this representation so PostgreSQL,
 * SQLite, Web and Desktop verify the same bytes.
 */
export function canonicalV3JsonbText(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('Canonical JSON cannot contain a non-finite number');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalV3JsonbText(item)).join(', ')}]`;
  }
  if (typeof value === 'object') {
    const utf8 = new TextEncoder();
    const compareKeys = (left: string, right: string): number => {
      const leftBytes = utf8.encode(left);
      const rightBytes = utf8.encode(right);
      if (leftBytes.length !== rightBytes.length) return leftBytes.length - rightBytes.length;
      for (let index = 0; index < leftBytes.length; index += 1) {
        const difference = (leftBytes[index] ?? 0) - (rightBytes[index] ?? 0);
        if (difference !== 0) return difference;
      }
      return 0;
    };
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => compareKeys(left, right));
    return `{${entries
      .map(([key, item]) => `${JSON.stringify(key)}: ${canonicalV3JsonbText(item)}`)
      .join(', ')}}`;
  }
  throw new TypeError(`Canonical JSON cannot contain ${typeof value}`);
}
