type SpinnerProps = {
  size?: number;
  className?: string;
  label?: string;
};

export function Spinner({ size = 14, className = "", label }: SpinnerProps) {
  return (
    <span
      className={`inline-flex items-center gap-xs ${className}`}
      role="status"
      aria-live="polite"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className="animate-spin"
      >
        <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2" />
        <path
          d="M14.5 8a6.5 6.5 0 0 0-6.5-6.5"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      {label ? <span>{label}</span> : <span className="sr-only">加载中</span>}
    </span>
  );
}

export function FullPageSpinner({ label = "加载中" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-base-default">
      <Spinner size={18} label={label} className="text-neutral-60" />
    </div>
  );
}
