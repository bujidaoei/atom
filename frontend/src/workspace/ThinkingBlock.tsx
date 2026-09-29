import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/ui/Icon";

type ThinkingBlockProps = {
  text: string;
  active: boolean;
};

/** Collapsed by default; shimmers while the thought is still streaming. */
export function ThinkingBlock({ text, active }: ThinkingBlockProps) {
  const [open, setOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !active) return;
    const node = bodyRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [text, open, active]);

  if (!text.trim()) return null;

  return (
    <div className="hairline rounded-m border-neutral-12 bg-neutral-4">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center gap-xs px-s py-xs text-left text-sm transition-colors duration-ui ease-ui hover:bg-neutral-8 active:bg-neutral-12"
      >
        <Icon
          name="chevron-right"
          size={12}
          className={`text-neutral-40 transition-transform duration-ui ease-ui ${
            open ? "rotate-90" : ""
          }`}
        />
        <span className={active ? "shimmer-text font-medium" : "font-medium text-neutral-60"}>
          深度思考
        </span>
        <span className="ml-auto font-mono text-xs text-neutral-40">{text.length}</span>
      </button>

      {open ? (
        <div
          ref={bodyRef}
          className="max-h-[220px] overflow-y-auto border-t border-neutral-8 px-s py-s"
        >
          <p className="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-neutral-60">
            {text}
          </p>
        </div>
      ) : null}
    </div>
  );
}
