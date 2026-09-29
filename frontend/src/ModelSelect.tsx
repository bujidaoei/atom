import { FormEvent, useEffect, useRef, useState } from "react";
import { api, readError } from "./api";
import type { SettingsView } from "./types";

function Chevron() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function SendMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 12.5V3.5M8 3.5 4.8 6.7M8 3.5l3.2 3.2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ModelSelect({ onError }: { onError?: (message: string) => void }) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.settings().then(setView).catch((err) => onError?.(readError(err)));
  }, [onError]);

  useEffect(() => {
    function close(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  async function change(model: string) {
    setOpen(false);
    const previous = view;
    setView((current) => (current ? { ...current, model } : current));
    try {
      setView(await api.saveSettings({ model }));
    } catch (err) {
      setView(previous);
      onError?.(readError(err));
    }
  }

  const models = view?.models || [];
  const current = view?.model || "";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="网关模型"
        disabled={!view}
        onClick={() => setOpen((value) => !value)}
        className="flex max-w-[220px] items-center gap-1 text-sm text-[#6b7280] disabled:opacity-50"
      >
        <span className="truncate">{current || "选择模型"}</span>
        <Chevron />
      </button>
      {open ? (
        <ul
          role="listbox"
          aria-label="网关模型"
          className="absolute bottom-full right-0 z-30 mb-2 max-h-80 w-[240px] overflow-auto rounded-xl bg-white py-1 shadow-[0_12px_40px_rgba(15,23,42,0.16)]"
        >
          {models.map((model) => {
            const selected = model.id === current;
            return (
              <li key={model.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    change(model.id);
                  }}
                  className={`w-full truncate px-4 py-2.5 text-left text-sm text-[#1f2937] ${selected ? "bg-[#f3f4f6]" : "hover:bg-[#f7f7f8]"}`}
                >
                  {model.id}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function ComposerDock({
  value,
  onChange,
  onSubmit,
  busy,
  placeholder,
  disabled,
  onError,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  busy?: boolean;
  placeholder: string;
  disabled?: boolean;
  onError?: (message: string) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="w-full rounded-[24px] bg-white px-4 pb-3 pt-3 shadow-[0_10px_40px_rgba(15,23,42,0.08)]">
      <label className="sr-only">{placeholder}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={3}
        placeholder={placeholder}
        className="w-full resize-none bg-transparent text-[15px] leading-7 text-[#1a1a1a] outline-none placeholder:text-[#9aa0a6]"
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
      />
      <div className="mt-1 flex items-center justify-between">
        <button
          type="button"
          aria-label="聚焦输入"
          onClick={(event) => event.currentTarget.closest("form")?.querySelector("textarea")?.focus()}
          className="flex h-8 w-8 items-center justify-center rounded-full border border-[#e5e7eb] text-lg leading-none text-[#6b7280]"
        >
          +
        </button>
        <div className="flex items-center gap-3">
          <ModelSelect onError={onError} />
          <button
            type="submit"
            aria-label="发送"
            disabled={disabled || busy || !value.trim()}
            className="relative z-40 flex h-9 w-9 items-center justify-center rounded-full bg-[#3b6cff] text-white disabled:bg-[#8b9098] disabled:opacity-40"
          >
            <SendMark />
          </button>
        </div>
      </div>
    </form>
  );
}
