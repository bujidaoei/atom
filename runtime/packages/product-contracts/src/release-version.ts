/** Versions published by the project's stable and beta release channels. */
export function releaseVersionParts(value: string): number[] | undefined {
  const match = /^(?:desktop-v)?(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$/u.exec(value);
  if (!match) return undefined;
  const parts = [
    Number(match[1]),
    Number(match[2]),
    Number(match[3]),
    Number(match[4] ?? Number.MAX_SAFE_INTEGER),
  ];
  return parts.every(Number.isSafeInteger) ? parts : undefined;
}

export function isNewerReleaseVersion(candidate: string, current: string): boolean {
  const left = releaseVersionParts(candidate);
  const right = releaseVersionParts(current);
  if (!left || !right) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return (left[index] ?? 0) > (right[index] ?? 0);
  }
  return false;
}
