import { Icon } from "../components/ui/Icon";
import { Spinner } from "../components/ui/Spinner";
import type { ToolStatus } from "./useProjectStream";

type ToolCardProps = {
  toolName: string;
  argSummary: string;
  status: ToolStatus;
  detail: string;
};

/** spinner → check → red X, with the tool call summarised on one line. */
export function ToolCard({ toolName, argSummary, status, detail }: ToolCardProps) {
  return (
    <div
      className={[
        "hairline flex items-start gap-s rounded-m px-s py-xs transition-colors duration-ui ease-ui",
        status === "failed"
          ? "border-danger-edge bg-danger-surface"
          : "border-neutral-12 bg-base-secondary",
      ].join(" ")}
    >
      <span
        className={[
          "mt-[2px] flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
          status === "running"
            ? "text-brand-text"
            : status === "ok"
              ? "bg-success-chip text-success-strong"
              : "bg-danger-chip text-danger-strong",
        ].join(" ")}
      >
        {status === "running" ? (
          <Spinner size={12} />
        ) : (
          <Icon name={status === "ok" ? "check" : "close"} size={11} />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-s font-mono text-xs leading-4">
          <span className="font-medium text-neutral-95">{toolName}</span>
          {argSummary ? <span className="truncate text-neutral-60">{argSummary}</span> : null}
        </p>
        {detail && status === "failed" ? (
          <p className="mt-xxs break-words text-xs leading-4 text-danger-strong">{detail}</p>
        ) : null}
      </div>
    </div>
  );
}
