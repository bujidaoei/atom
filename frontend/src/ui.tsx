import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "solid" | "line" | "quiet";
};

const variants: Record<NonNullable<ButtonProps["variant"]>, string> = {
  solid: "bg-ink text-paper hover:bg-[#322c26] disabled:hover:bg-ink",
  line: "border border-line bg-raised text-ink hover:border-ink/40",
  quiet: "text-ink hover:bg-ink/5",
};

export function Button({ variant = "solid", className = "", type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

export function Wordmark({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="inline-flex items-center gap-2 text-sm tracking-[0.16em]">
      <span className="h-2.5 w-2.5 rounded-sm bg-copper" aria-hidden="true" />
      ATOM
    </Link>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm">{label}</span>
      {hint ? <span className="mt-1 block text-sm leading-6 text-muted">{hint}</span> : null}
      <div className="mt-2">{children}</div>
    </label>
  );
}

export const inputClass =
  "w-full rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink placeholder:text-muted/70";

export function StatusDot({ tone }: { tone: "wait" | "work" | "ok" | "bad" }) {
  const color = {
    wait: "bg-line",
    work: "bg-copper pulse-dot",
    ok: "bg-sage",
    bad: "bg-clay",
  }[tone];
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} aria-hidden="true" />;
}

export function formatWhen(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export const statusLabel: Record<string, string> = {
  draft: "还没开始",
  planning: "正在写契约",
  awaiting_approval: "等你确认",
  building: "正在写页面",
  ready: "可以预览",
  error: "出错了",
};

export const roleLabel: Record<string, string> = {
  user: "你",
  mike: "Mike · 带队",
  iris: "Iris · 研究",
  emma: "Emma · 契约",
  bob: "Bob · 结构",
  alex: "Alex · 工程",
  system: "系统",
};
