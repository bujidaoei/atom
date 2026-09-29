import type { ReactNode } from "react";
import type { ProjectStatus } from "../../lib/types";
import { STATUS_LABEL, STATUS_TONE, isRunningStatus } from "../../lib/format";

export function Badge({
  children,
  tone = "bg-neutral-12 text-neutral-80",
  className = "",
}: {
  children: ReactNode;
  tone?: string;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-xxs rounded-full px-s py-[2px] text-xs font-medium ${tone} ${className}`}
    >
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: ProjectStatus }) {
  const running = isRunningStatus(status);
  return (
    <Badge tone={STATUS_TONE[status]}>
      {running ? (
        <span className="h-[5px] w-[5px] animate-pulse-soft rounded-full bg-current" />
      ) : null}
      {STATUS_LABEL[status]}
    </Badge>
  );
}
