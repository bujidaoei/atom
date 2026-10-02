import type {
  AcceptanceResult,
  AcceptanceRun,
  LookupResult,
  ProjectDetail,
  ProjectSummary,
  PublishResult,
  RaceHeat,
  RaceSummary,
  Settings,
  Usage,
  User,
  VerifiedPublication,
  PublicationHistory,
  VerificationStatus,
} from "./types";

/**
 * Deployment prefix, e.g. "" at the root or "/atom" behind a reverse proxy
 * that mounts the app on a subpath. Vite bakes this in from `VITE_BASE`.
 *
 * Every absolute path the app requests has to carry it, otherwise the proxy
 * routes /api and /preview to whatever else lives at the root.
 */
const BASE = import.meta.env.BASE_URL.replace(/\/+$/, "");

function commandKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
}

export function withBase(path: string): string {
  return `${BASE}${path}`;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Registered by the auth provider so a 401 anywhere lands on /login. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** Suppressed for the boot-time `GET /api/auth/me` probe, which is expected
 *  to 401 for anonymous visitors on public pages. */
type RequestOptions = {
  method?: string;
  body?: unknown;
  silent401?: boolean;
  accept?: string;
  commandKey?: string;
  intent?: "inspect-private-content" | "open-private-content" | "revoke-account-sessions" | "inspect-verified-release" | "publish-verified-release" | "unpublish-verified-release" | "rollback-verified-release";
  signal?: AbortSignal;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, silent401 = false, accept = "application/json" } = options;

  let response: Response;
  try {
    const send = () => fetch(withBase(path), {
      method,
      credentials: "include",
      signal: options.signal,
      headers: {
        Accept: accept,
        ...(options.intent ? { "X-Atom-Intent": options.intent } : {}),
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(options.commandKey ? { "Idempotency-Key": options.commandKey } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    try { response = await send(); }
    catch (error) {
      if (!options.commandKey) throw error;
      response = await send();
    }
  } catch {
    throw new ApiError(0, "网络连接失败，请检查后端是否已启动。");
  }

  if (response.status === 401) {
    if (!silent401) onUnauthorized?.();
    throw new ApiError(401, "登录态已失效，请重新登录。");
  }

  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string" && data.detail) detail = data.detail;
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  if (accept.startsWith("text/")) return (await response.text()) as T;
  return (await response.json()) as T;
}

export const api = {
  inspectContentAccess: (binding: string, challenge: string, signal: AbortSignal) =>
    request<unknown>("/api/content-access/request?" + new URLSearchParams({ binding, challenge }),
      { intent: "inspect-private-content", signal }),
  issueContentAccess: (binding: string, challenge: string, signal: AbortSignal) =>
    request<unknown>("/api/content-access/handoff",
      { method: "POST", body: { binding, challenge }, intent: "open-private-content", signal }),
  // ---- auth
  lookup: (email: string) =>
    request<LookupResult>("/api/auth/lookup", { method: "POST", body: { email } }),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: { email, password } }),
  register: (email: string, password: string, name?: string) =>
    request<User>("/api/auth/register", {
      method: "POST",
      body: name ? { email, password, name } : { email, password },
    }),
  logout: (signal: AbortSignal) => request<{ ok: true }>("/api/auth/logout", { method: "POST", signal, silent401: true }),
  logoutAll: (signal: AbortSignal) => request<{ ok: true }>("/api/auth/logout-all",
    { method: "POST", signal, silent401: true, intent: "revoke-account-sessions" }),
  me: (silent401 = false, signal?: AbortSignal) => request<User>("/api/auth/me", { silent401, signal }),

  // ---- settings
  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (patch: { baseUrl?: string; apiKey?: string; model?: string }) =>
    request<Settings>("/api/settings", { method: "PUT", body: patch }),
  clearApiKey: () => request<Settings>("/api/settings/api-key", { method: "DELETE" }),

  // ---- projects
  listProjects: () => request<{ projects: ProjectSummary[] }>("/api/projects"),
  createProject: (prompt: string) =>
    request<{ project: ProjectDetail }>("/api/projects", { method: "POST", body: { prompt } }),
  getProject: (id: string) => request<{ project: ProjectDetail }>(`/api/projects/${id}`),
  deleteProject: (id: string) =>
    request<{ ok: true }>(`/api/projects/${id}`, { method: "DELETE" }),
  readFile: (id: string, path: string) =>
    request<string>(`/api/projects/${id}/files/${encodeFilePath(path)}`, {
      accept: "text/plain",
    }),

  // ---- main loop
  plan: (id: string, key = commandKey()) =>
    request<{ runId: string }>(`/api/projects/${id}/plan`, { method: "POST", commandKey: key }),
  approve: (id: string, note?: string) =>
    request<{ runId: string }>(`/api/projects/${id}/approve`, {
      method: "POST",
      body: note ? { note } : {},
      commandKey: commandKey(),
    }),
  revise: (id: string, message: string) =>
    request<{ runId: string }>(`/api/projects/${id}/revise`, {
      method: "POST",
      body: { message },
      commandKey: commandKey(),
    }),
  cancel: (id: string) =>
    request<{ ok: true }>(`/api/projects/${id}/cancel`, { method: "POST" }),

  // ---- publish
  publish: (id: string) =>
    request<PublishResult>(`/api/projects/${id}/publish`, { method: "POST" }),
  unpublish: (id: string) =>
    request<{ ok: true }>(`/api/projects/${id}/unpublish`, { method: "POST" }),
  currentVerifiedRelease: (id: string, signal?: AbortSignal) =>
    request<{ publication: VerifiedPublication | null }>(`/api/projects/${id}/releases/current`,
      { intent: "inspect-verified-release", signal }),
  publicationHistory: (id: string, cursor?: string, signal?: AbortSignal) =>
    request<PublicationHistory>(`/api/projects/${id}/releases/history${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
      { intent: "inspect-verified-release", signal }),
  getVerification: (id: string, requestId: string, signal?: AbortSignal) =>
    request<VerificationStatus>(`/api/projects/${id}/verifications/${requestId}`, { signal }),
  latestVerification: (id: string, signal?: AbortSignal) =>
    request<{ verification: VerificationStatus | null }>(`/api/projects/${id}/verifications/latest`, { signal }),
  reserveVerification: (id: string, requestId: string) =>
    request<VerificationStatus>(`/api/projects/${id}/verifications`,
      { method: "POST", body: { requestId } }),
  runVerification: (id: string, requestId: string) =>
    request<VerificationStatus>(`/api/projects/${id}/verifications/${requestId}/run`,
      { method: "POST" }),
  publishVerifiedRelease: (id: string, command: {
    releaseId: string; verificationId?: string; expectedRevision: string;
    expectedGeneration: number; audience: "owner" | "public"; slug: string;
  }) => request<{ releaseId: string; revisionId: string; generation: number; slug: string }>(
    `/api/projects/${id}/releases`,
    { method: "POST", body: command, intent: "publish-verified-release" }),
  unpublishVerifiedRelease: (id: string, releaseId: string, command: {
    commandId: string; expectedGeneration: number;
  }) => request<{ commandId: string; releaseId: string; generation: number }>(
    `/api/projects/${id}/releases/${releaseId}/unpublish`,
    { method: "POST", body: command, intent: "unpublish-verified-release" }),
  restorePublication: (id: string, releaseId: string, command: {
    commandId: string; newReleaseId: string; sourceReleaseId: string;
    expectedRevision: string; expectedGeneration: number;
  }) => request<{ releaseId: string; generation: number }>(
    `/api/projects/${id}/releases/${releaseId}/rollback`,
    { method: "POST", body: command, intent: "rollback-verified-release" }),

  // ---- acceptance
  postAcceptance: (id: string, results: AcceptanceResult[]) =>
    request<{ acceptance: AcceptanceRun }>(`/api/projects/${id}/acceptance`, {
      method: "POST",
      body: { results },
    }),

  // ---- race
  startRace: (id: string, models: string[], budgetSeconds = 180) =>
    request<{ raceId: string; heats: RaceHeat[] }>(`/api/projects/${id}/race`, {
      method: "POST",
      body: { models, budgetSeconds },
      commandKey: commandKey(),
    }),
  retryHeat: (id: string, heatId: string, budgetSeconds: number) =>
    request<{ runId: string }>(`/api/projects/${id}/race/${heatId}/retry`, {
      method: "POST", body: { budgetSeconds }, commandKey: commandKey(),
    }),
  getRace: (id: string) => request<{ race: RaceSummary | null }>(`/api/projects/${id}/race`),
  adoptHeat: (id: string, heatId: string) =>
    request<{ ok: true }>(`/api/projects/${id}/race/${heatId}/adopt`, { method: "POST" }),

  // ---- usage
  getUsage: () => request<Usage>("/api/usage"),
};

/** Workspace paths are nested, so encode each segment but keep the slashes. */
export function encodeFilePath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

export function previewUrl(projectId: string): string {
  return withBase(`/preview/${projectId}/`);
}

export function racePreviewUrl(projectId: string, heatId: string): string {
  return withBase(`/preview/${projectId}/race/${heatId}/`);
}

export function publishedUrl(slug: string): string {
  return withBase(`/p/${slug}/`);
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return "发生了未知错误。";
}
