import { useState } from "react";
import type { RefObject } from "react";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/States";
import { errorMessage, previewUrl } from "../lib/api";
import { openRevisionPreview } from "../lib/previewAccess";
import type { ProjectStatus } from "../lib/types";

import { PreviewToolbar, PREVIEW_VIEWPORTS, type PreviewViewport } from "./PreviewToolbar";

type PreviewTabProps = {
  projectId: string;
  status: ProjectStatus;
  hasFiles: boolean;
  isolated: boolean;
  revisionId: string | null;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  /** Bumped by the parent whenever the workspace files change. */
  reloadToken: number;
};

export function PreviewTab({
  projectId,
  status,
  hasFiles,
  isolated,
  revisionId,
  iframeRef,
  reloadToken,
}: PreviewTabProps) {
  const [viewport, setViewport] = useState<PreviewViewport>("desktop");
  const [manualToken, setManualToken] = useState(0);
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  const url = previewUrl(projectId);
  const active = PREVIEW_VIEWPORTS.find((item) => item.id === viewport) ?? PREVIEW_VIEWPORTS[0];

  if (isolated) {
    return <div className="flex min-h-0 flex-1 items-center justify-center bg-base-secondary-alt p-l">
      <div className="max-w-[420px] space-y-m rounded-l border border-neutral-12 bg-base-default p-l text-center">
        <h2 className="text-md font-medium text-neutral-95">独立预览</h2>
        <p className="text-sm text-neutral-60">在独立窗口查看当前已保存的版本。网页脚本和浏览器存储与 Atom 工作区隔离。</p>
        {openError ? <p role="alert" className="text-sm text-danger-strong">{openError}</p> : null}
        <Button disabled={!revisionId} loading={opening} onClick={() => {
          if (!revisionId) return;
          setOpening(true); setOpenError(null);
          void openRevisionPreview(projectId, revisionId)
            .catch(error => setOpenError(errorMessage(error)))
            .finally(() => setOpening(false));
        }}>打开当前版本</Button>
        {!revisionId ? <p className="text-xs text-neutral-60">保存完成后即可预览。</p> : null}
      </div>
    </div>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PreviewToolbar viewport={viewport} onViewport={setViewport} url={url}
        hasFiles={hasFiles} onRefresh={() => {
          setLoading(true);
          setManualToken(token => token + 1);
        }} />

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
