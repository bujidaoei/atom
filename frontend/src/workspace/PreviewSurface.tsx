import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { PreviewViewport } from "./PreviewToolbar";

/** Scale the presentation, never the tablet/mobile layout viewport. */
export function PreviewSurface({ viewport, children }: { viewport: PreviewViewport; children: ReactNode }) {
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 420 });
  useLayoutEffect(() => {
    const element = host.current;
    if (!element) return;
    const update = () => setSize({ width: element.clientWidth, height: element.clientHeight });
    const observer = new ResizeObserver(update);
    observer.observe(element);
    update();
    return () => observer.disconnect();
  }, []);
  const width = viewport === "tablet" ? 768 : viewport === "mobile" ? 390 : size.width;
  const scale = width > 0 && size.width > 0 ? Math.min(1, size.width / width) : 1;
  return <div className="flex min-h-0 flex-1 flex-col bg-base-secondary-alt p-m">
    <div ref={host} className="relative min-h-[420px] min-w-0 flex-1 overflow-hidden"
      data-preview-surface data-viewport={viewport} data-layout-width={width} data-scale={scale}>
      <div className="absolute top-0 origin-top-left overflow-hidden rounded-m bg-white shadow-flat"
        style={{ width: width || "100%", height: size.height / scale,
          left: Math.max(0, (size.width - width * scale) / 2), transform: `scale(${scale})` }}>
        {children}
      </div>
    </div>
    <div className="flex shrink-0 items-center justify-center gap-xs pt-xs text-xs text-neutral-40" aria-live="polite">
      <span>{viewport === "desktop" ? "自适应宽度" : `${width} px`}</span>
      {scale < 0.99 ? <span>· 缩放 {Math.round(scale * 100)}%</span> : null}
    </div>
  </div>;
}
