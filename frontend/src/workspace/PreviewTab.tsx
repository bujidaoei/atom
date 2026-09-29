import { useState } from "react";
import type { RefObject } from "react";
import { IconButton } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import type { IconName } from "../components/ui/Icon";
import { EmptyState } from "../components/ui/States";
import { previewUrl } from "../lib/api";
import type { ProjectStatus } from "../lib/types";

type Viewport = "desktop" | "tablet" | "mobile";

const VIEWPORTS: { id: Viewport; label: string; icon: IconName; width: string }[] = [
  { id: "desktop", label: "桌面", icon: "desktop", width: "100%" },
  { id: "tablet", label: "平板", icon: "tablet", width: "768px" },
  { id: "mobile", label: "手机", icon: "mobile", width: "390px" },
];

type PreviewTabProps = {
  projectId: string;
  status: ProjectStatus;
  hasFiles: boolean;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  /** Bumped by the parent whenever the workspace files change. */
  reloadToken: number;
};

export function PreviewTab({
  projectId,
  status,
  hasFiles,
  iframeRef,
  reloadToken,
}: PreviewTabProps) {
  const [viewport, setViewport] = useState<Viewport>("desktop");
  const [manualToken, setManualToken] = useState(0);
  const [loading, setLoading] = useState(true);
  const url = previewUrl(projectId);
  const active = VIEWPORTS.find((item) => item.id === viewport) ?? VIEWPORTS[0];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-xs border-b border-neutral-12 px-m py-xs">
        <div className="hairline flex items-center gap-xxxs rounded-full border-neutral-12 bg-base-secondary p-[2px]">
          {VIEWPORTS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setViewport(item.id)}
              aria-pressed={viewport === item.id}
              title={`${item.label}（${item.width}）`}
              className={[
                "inline-flex h-6 items-center gap-xxs rounded-full px-s text-xs transition-colors duration-ui ease-ui",
                viewport === item.id
                  ? "bg-base-tertiary text-neutral-95 shadow-flat"
                  : "text-neutral-60 hover:text-neutral-95",
              ].join(" ")}
            >
              <Icon name={item.icon} size={13} />
              <span className="hidden sm:inline">{item.label}</span>
            </button>
          ))}
        </div>

        <span className="ml-xs truncate font-mono text-xs text-neutral-40">{url}</span>

        <div className="ml-auto flex items-center gap-xxs">
          <IconButton
            label="刷新预览"
            onClick={() => {
              setLoading(true);
              setManualToken((token) => token + 1);
            }}
            disabled={!hasFiles}
          >
            <Icon name="refresh" size={14} />
          </IconButton>
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            title="打开新窗口"
            className={[
              "inline-flex h-7 items-center gap-xxs rounded-m px-s text-xs transition-colors duration-ui ease-ui",
              hasFiles
                ? "text-neutral-60 hover:bg-neutral-8 hover:text-neutral-95 active:bg-neutral-12"
                : "pointer-events-none text-neutral-40 opacity-50",
            ].join(" ")}
          >
            <Icon name="external" size={13} />
            打开新窗口
          </a>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-auto bg-base-secondary-alt p-m">
        {hasFiles ? (
          <div
            className="mx-auto h-full transition-[max-width] duration-ui ease-ui"
            style={{ maxWidth: active.width }}
          >
            <iframe
              key={`${reloadToken}-${manualToken}`}
              ref={iframeRef}
              src={url}
              title="项目预览"
              onLoad={() => setLoading(false)}
              sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals"
              className="h-full min-h-[420px] w-full rounded-m border-0 bg-white shadow-flat"
            />
          </div>
        ) : (
          <EmptyState
            icon="eye"
            title="还没有可预览的文件"
            description={
              status === "awaiting_approval"
                ? "先在「契约」里确认需求，Alex 写完代码就能在这里看到成品。"
                : "等 Alex 写完第一个文件，这里会实时刷新。"
            }
          />
        )}

        {hasFiles && loading ? (
          <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-center pt-m">
            <span className="hairline rounded-full border-neutral-12 bg-base-tertiary px-m py-[3px] text-xs text-neutral-60 shadow-flat">
              正在加载预览…
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
