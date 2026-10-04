import { useLayoutEffect, useRef, useState } from "react";
import { IconButton } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import type { IconName } from "../components/ui/Icon";

export type PreviewViewport = "desktop" | "tablet" | "mobile";
export const PREVIEW_VIEWPORTS: {
  id: PreviewViewport; label: string; icon: IconName; width: string;
}[] = [
  { id: "desktop", label: "桌面", icon: "desktop", width: "100%" },
  { id: "tablet", label: "平板", icon: "tablet", width: "768px" },
  { id: "mobile", label: "手机", icon: "mobile", width: "390px" },
];

export function PreviewToolbar({ viewport, onViewport, url, hasFiles, onRefresh }: {
  viewport: PreviewViewport;
  onViewport: (viewport: PreviewViewport) => void;
  url: string;
  hasFiles: boolean;
  onRefresh: () => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const fullRow = useRef<HTMLDivElement>(null);
  const [labels, setLabels] = useState(false);
  useLayoutEffect(() => {
    const host = container.current;
    const measure = fullRow.current;
    if (!host || !measure) return;
    const update = () => setLabels(measure.getBoundingClientRect().width <= host.clientWidth);
    const observer = new ResizeObserver(update);
    observer.observe(host);
    observer.observe(measure);
    update();
    return () => observer.disconnect();
  }, []);

  function contents(showLabels: boolean) {
    return <>
      <div className="hairline flex shrink-0 items-center gap-xxxs rounded-full border-neutral-12 bg-base-secondary p-[2px]">
        {PREVIEW_VIEWPORTS.map(item => <button key={item.id} type="button"
          onClick={() => onViewport(item.id)} aria-label={item.label}
          aria-pressed={viewport === item.id} title={`${item.label}（${item.width}）`}
          className={[
            "inline-flex h-6 shrink-0 items-center gap-xxs whitespace-nowrap rounded-full px-s text-xs transition-colors duration-ui ease-ui",
            viewport === item.id ? "bg-base-tertiary text-neutral-95 shadow-flat" : "text-neutral-60 hover:text-neutral-95",
          ].join(" ")}>
          <Icon name={item.icon} size={13} />
          {showLabels ? <span>{item.label}</span> : null}
        </button>)}
      </div>
      <span className="ml-xs min-w-0 flex-1 truncate font-mono text-xs text-neutral-40" title={url}>{url}</span>
      <div className="ml-auto flex shrink-0 items-center gap-xxs">
        <IconButton label="刷新预览" onClick={onRefresh} disabled={!hasFiles}>
          <Icon name="refresh" size={14} />
        </IconButton>
        <a href={url} target="_blank" rel="noreferrer" title="打开新窗口" aria-label="打开新窗口"
          aria-disabled={!hasFiles} tabIndex={hasFiles ? undefined : -1}
          className={[
            "inline-flex h-7 shrink-0 items-center gap-xxs whitespace-nowrap rounded-m px-s text-xs transition-colors duration-ui ease-ui",
            hasFiles ? "text-neutral-60 hover:bg-neutral-8 hover:text-neutral-95 active:bg-neutral-12"
              : "pointer-events-none text-neutral-40 opacity-50",
          ].join(" ")}>
          <Icon name="external" size={13} />
          {showLabels ? <span>打开新窗口</span> : null}
        </a>
      </div>
    </>;
  }

  return <div ref={container} className="relative min-w-0 shrink-0 border-b border-neutral-12"
    data-preview-toolbar data-labels={labels ? "visible" : "hidden"}>
    <div className="flex items-center gap-xs px-m py-xs">{contents(labels)}</div>
    {/* Independent max-content geometry prevents compact/full feedback loops. */}
    <div className="pointer-events-none invisible absolute inset-0 overflow-hidden" aria-hidden inert>
      <div ref={fullRow} className="flex w-max items-center gap-xs px-m py-xs">{contents(true)}</div>
    </div>
  </div>;
}
