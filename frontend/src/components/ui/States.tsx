import type { ReactNode } from "react";
import { Button } from "./Button";
import { Icon } from "./Icon";
import type { IconName } from "./Icon";
import { Spinner } from "./Spinner";

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`hairline rounded-l border-neutral-12 bg-base-tertiary ${className}`}>
      {children}
    </div>
  );
}

type EmptyStateProps = {
  icon?: IconName;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
};

export function EmptyState({
  icon = "sparkle",
  title,
  description,
  action,
  compact = false,
}: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center text-center ${
        compact ? "gap-s px-l py-xl" : "gap-m px-xl py-xxxl"
      }`}
    >
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-8 text-neutral-60">
        <Icon name={icon} size={16} />
      </span>
      <div className="flex flex-col gap-xxs">
        <p className="text-md font-medium text-neutral-95">{title}</p>
        {description ? (
          <p className="max-w-[46ch] text-base text-neutral-60">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

type ErrorStateProps = {
  title?: string;
  message: string;
  onRetry?: () => void;
  compact?: boolean;
};

export function ErrorState({
  title = "加载失败",
  message,
  onRetry,
  compact = false,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={`flex flex-col items-start gap-s rounded-l bg-danger-surface hairline border-danger-edge ${
        compact ? "px-m py-s" : "p-l"
      }`}
    >
      <p className="flex items-center gap-xs text-base font-medium text-danger-strong">
        <Icon name="alert" size={14} />
        {title}
      </p>
      <p className="text-base text-neutral-80">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          重试
        </Button>
      ) : null}
    </div>
  );
}

export function LoadingState({ label = "加载中" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-s px-l py-xxl text-neutral-60">
      <Spinner size={15} label={label} />
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse-soft rounded-m bg-neutral-12 ${className}`} />;
}

export function InlineNote({ children }: { children: ReactNode }) {
  return <p className="text-sm text-neutral-60">{children}</p>;
}
