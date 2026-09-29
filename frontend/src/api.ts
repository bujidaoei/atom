import type { Project, ProjectSummary, RuntimeResult, SettingsView, Usage, User } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function apiUrl(path: string): string {
  const prefix = import.meta.env.BASE_URL.replace(/\/$/, "");
  return `${prefix}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? String(detail[0].msg)
          : "请求失败";
    throw new ApiError(response.status, message);
  }
  return body as T;
}

export const api = {
  me: () => request<User>("/api/auth/me"),
  register: (payload: { name: string; email: string; password: string }) =>
    request<User>("/api/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload: { email: string; password: string }) =>
    request<User>("/api/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  settings: () => request<SettingsView>("/api/settings"),
  saveSettings: (payload: { base_url?: string; api_key?: string; model?: string }) =>
    request<SettingsView>("/api/settings", { method: "PUT", body: JSON.stringify(payload) }),
  clearKey: () => request<SettingsView>("/api/settings/api-key", { method: "DELETE" }),
  projects: () => request<ProjectSummary[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (prompt: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ prompt }) }),
  deleteProject: (id: string) => request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  plan: (id: string) => request<Project>(`/api/projects/${id}/plan`, { method: "POST" }),
  build: (id: string) => request<Project>(`/api/projects/${id}/build`, { method: "POST" }),
  revise: (id: string, instruction: string) =>
    request<Project>(`/api/projects/${id}/revise`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  applyAmendment: (id: string) =>
    request<Project>(`/api/projects/${id}/amendments/apply`, { method: "POST" }),
  discardAmendment: (id: string) =>
    request<Project>(`/api/projects/${id}/amendments/discard`, { method: "POST" }),
  accept: (id: string, runtime: RuntimeResult[]) =>
    request<Project>(`/api/projects/${id}/acceptance`, {
      method: "POST",
      body: JSON.stringify({ runtime }),
    }),
  saveState: (id: string, snapshot: Record<string, string>) =>
    request<{ ok: boolean }>(`/api/projects/${id}/preview-state`, {
      method: "PUT",
      body: JSON.stringify({ snapshot }),
    }),
  usage: () => request<Usage>("/api/usage"),
};

export const PROMPT_KEY = "atom.prompt";

export function readError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "请求失败";
}
