import type { ProjectStatus } from "./types";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatNumber(value: number): string {
  return value.toLocaleString("zh-CN");
}

export function formatElapsed(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diff = Date.now() - date.getTime();
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} 天前`;
  return formatDateTime(iso).slice(0, 10);
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export const STATUS_LABEL: Record<ProjectStatus, string> = {
  draft: "草稿",
  planning: "规划中",
  awaiting_approval: "待确认契约",
  building: "构建中",
  ready: "已生成",
  error: "出错",
  cancelled: "已停止",
  timed_out: "已超时",
  interrupted: "已中断",
};

/** Tone classes per status, all drawn from the semantic layer. */
export const STATUS_TONE: Record<ProjectStatus, string> = {
  draft: "bg-neutral-12 text-neutral-60",
  planning: "bg-brand-alpha-soft text-brand-text",
  awaiting_approval: "bg-brand-alpha-strong text-brand-text",
  building: "bg-brand-alpha-soft text-brand-text",
  ready: "bg-success-surface text-success-strong",
  error: "bg-danger-surface text-danger-strong",
  cancelled: "bg-neutral-12 text-neutral-60",
  timed_out: "bg-danger-surface text-danger-strong",
  interrupted: "bg-danger-surface text-danger-strong",
};

export function isRunningStatus(status: ProjectStatus): boolean {
  return status === "planning" || status === "building";
}

/** Mirrors the contract's masking rule; used for optimistic local previews. */
export function maskKey(plain: string): string {
  if (plain.length <= 4) return "*".repeat(plain.length);
  return `${plain.slice(0, 2)}${"*".repeat(plain.length - 4)}${plain.slice(-2)}`;
}
