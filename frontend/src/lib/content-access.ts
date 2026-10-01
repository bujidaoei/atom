export type AccessScope = {
  binding: string; projectId: string; projectTitle: string; releaseId: string;
  revisionId: string; audience: "owner" | "public"; isCurrentRelease: boolean;
  publicationGeneration: number; releaseCreatedAt: number; expiresAt: number; contentOrigin: string;
};

export function accessQuery(search: string): { binding: string; challenge: string } | null {
  if (search.length > 257) return null;
  const entries = [...new URLSearchParams(search).entries()];
  const values = Object.fromEntries(entries);
  if (entries.length !== 2 || Object.keys(values).length !== 2 ||
      !/^[0-9a-f]{32}$/.test(values.binding ?? "") || !/^[0-9a-f]{64}$/.test(values.challenge ?? "")) return null;
  return { binding: values.binding, challenge: values.challenge };
}

export function accessScope(value: unknown, binding: string): AccessScope {
  if (!value || typeof value !== "object") throw new Error("访问范围响应无效。");
  const item = value as Record<string, unknown>;
  if (item.binding !== binding || ["projectId", "projectTitle", "releaseId", "revisionId", "contentOrigin"].some(
      key => typeof item[key] !== "string" || !(item[key] as string).length) ||
      !["owner", "public"].includes(String(item.audience)) || typeof item.isCurrentRelease !== "boolean" ||
      ["expiresAt", "releaseCreatedAt", "publicationGeneration"].some(key => !Number.isSafeInteger(item[key]) || Number(item[key]) < 1)) {
    throw new Error("访问范围响应无效。");
  }
  const target = new URL(item.contentOrigin as string);
  if (target.protocol !== "https:" || target.username || target.password || target.origin !== item.contentOrigin ||
      !target.hostname.startsWith(`r-${binding}.`)) throw new Error("内容地址无效。");
  return item as AccessScope;
}

export function handoffDestination(value: unknown, scope: AccessScope): string {
  if (!value || typeof value !== "object") throw new Error("访问凭据响应无效。");
  const item = value as Record<string, unknown>;
  if (typeof item.url !== "string" || !Number.isSafeInteger(item.expiresAt) || Number(item.expiresAt) * 1000 <= Date.now()) {
    throw new Error("访问凭据已失效，请重新打开项目。");
  }
  const target = new URL(item.url);
  if (target.origin !== scope.contentOrigin || target.username || target.password ||
      target.pathname !== "/_atom/exchange" || target.search || !/^#[0-9a-f]{64}$/.test(target.hash)) {
    throw new Error("内容地址与确认范围不一致。");
  }
  return target.href;
}
