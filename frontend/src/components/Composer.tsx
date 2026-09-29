import { useEffect, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Icon } from "./ui/Icon";
import { Spinner } from "./ui/Spinner";

type ComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  submitting?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  error?: string | null;
  autoFocus?: boolean;
  /** Left-aligned slot under the textarea, e.g. a model hint or file count. */
  meta?: ReactNode;
  submitLabel?: string;
  minRows?: number;
};

const MAX_HEIGHT = 208;

export function Composer({
  value,
  onChange,
  onSubmit,
  placeholder = "描述你想要的产品，一句话就够。",
  submitting = false,
  disabled = false,
  disabledReason,
  error = null,
  autoFocus = false,
  meta,
  submitLabel = "开始",
  minRows = 2,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canSubmit = value.trim().length > 0 && !submitting && !disabled;

  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSubmit) onSubmit();
    }
  }

  return (
    <div className="flex w-full flex-col gap-xs">
      <div className={`composer-shell ${disabled ? "opacity-70" : ""}`}>
        <textarea
          ref={textareaRef}
          value={value}
          rows={minRows}
          autoFocus={autoFocus}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          aria-label="需求输入框"
          className="w-full resize-none bg-transparent text-base leading-6 text-neutral-95 outline-none placeholder:text-neutral-40 disabled:cursor-not-allowed"
        />

        <div className="mt-s flex items-end justify-between gap-m">
          <div className="min-w-0 text-sm text-neutral-60">
            {disabled && disabledReason ? (
              <span className="text-danger-strong">{disabledReason}</span>
            ) : (
              (meta ?? (
                <span className="hidden sm:inline">
                  Enter 发送 · Shift + Enter 换行
                </span>
              ))
            )}
          </div>

          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit}
            aria-label={submitLabel}
            className="inline-flex h-8 items-center gap-xs rounded-full bg-brand px-m text-base font-medium text-white shadow-flat transition-[background-color,opacity,transform] duration-ui ease-ui hover:bg-brand-secondary focus-visible:outline-none active:translate-y-[0.5px] disabled:cursor-not-allowed disabled:bg-neutral-20 disabled:text-neutral-40 disabled:shadow-none"
          >
            {submitting ? <Spinner size={13} /> : <Icon name="arrow-up" size={14} />}
            <span>{submitLabel}</span>
          </button>
        </div>
      </div>

      {error ? (
        <p className="flex items-center gap-xxs px-xxs text-sm text-danger-strong" role="alert">
          <Icon name="alert" size={13} />
          {error}
        </p>
      ) : null}
    </div>
  );
}
