import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/States";
import { errorMessage } from "../lib/api";
import { acquireRevisionPreview, openRevisionPreview, type PreviewGrant } from "../lib/previewAccess";
import { PreviewToolbar, type PreviewViewport } from "./PreviewToolbar";
import { PreviewSurface } from "./PreviewSurface";

type Navigation = { grant: PreviewGrant; src: string; serial: number };
type State = "empty" | "acquiring" | "loading" | "displayed" | "failed";

export function IsolatedPreview({ projectId, revisionId }: { projectId: string; revisionId: string | null }) {
  const [viewport, setViewport] = useState<PreviewViewport>("desktop");
  const [retry, setRetry] = useState(0);
  const [navigation, setNavigation] = useState<Navigation | null>(null);
  const [state, setState] = useState<State>("empty");
  const [error, setError] = useState<string | null>(null);
  const [popupError, setPopupError] = useState<string | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const prior = useRef<PreviewGrant | null>(null);
  const ready = useRef(false);
  const loadDeadline = useRef<number | undefined>(undefined);
  const serial = useRef(0);
  const popupPending = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    setNavigation(null); setError(null); ready.current = false;
    if (!revisionId) { setState("empty"); return () => controller.abort(); }
    setState("acquiring");
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    void acquireRevisionPreview(projectId, revisionId, controller.signal, prior.current?.viewId)
      .then(grant => {
        if (controller.signal.aborted) return;
        prior.current = grant;
        setNavigation({ grant, src: grant.url, serial: ++serial.current });
        setState("loading");
      })
      .catch(failure => {
        if (disposed) return;
        setState("failed");
        setError(controller.signal.aborted ? "预览连接超时，请重新加载。" : errorMessage(failure));
      }).finally(() => window.clearTimeout(timeout));
    return () => { disposed = true; controller.abort(); window.clearTimeout(timeout); };
  }, [projectId, revisionId, retry]);

  useEffect(() => {
    if (!navigation) return;
    ready.current = false;
    const timeout = window.setTimeout(() => {
      setState("failed"); setError("预览未能及时加载，请重新加载或在新窗口打开。");
    }, 10000);
    loadDeadline.current = timeout;
    const receive = (event: MessageEvent) => {
      if (ready.current) return;
      if (event.source !== frame.current?.contentWindow ||
          event.origin !== new URL(navigation.grant.viewUrl).origin) return;
      const data = event.data;
      if (!data || typeof data !== "object" || data.type !== "atom.preview" ||
          (data.viewId !== navigation.grant.viewId && !(data.viewId === null && data.state === "error"))) return;
      if (data.state === "ready") ready.current = true;
      else if (data.state === "error") {
        window.clearTimeout(timeout); setState("failed");
        setError("预览访问已失效或文件暂时不可用，请重新加载。");
      }
    };
    window.addEventListener("message", receive);
    return () => { window.clearTimeout(timeout); window.removeEventListener("message", receive); };
  }, [navigation]);

  const refresh = () => {
    if (!navigation) { setRetry(value => value + 1); return; }
    ready.current = false; setState("loading"); setError(null);
    setNavigation({ ...navigation, src: navigation.grant.viewUrl + "_atom/resume", serial: ++serial.current });
  };
  const open = () => {
    if (!revisionId || popupPending.current) return;
    popupPending.current = true; setPopupError(null);
    void openRevisionPreview(projectId, revisionId)
      .catch(failure => setPopupError(errorMessage(failure)))
      .finally(() => { popupPending.current = false; });
  };
  return <div className="relative flex min-h-0 flex-1 flex-col" data-preview-state={state}>
    <PreviewToolbar viewport={viewport} onViewport={setViewport} url="当前已保存版本"
      hasFiles={Boolean(revisionId)} busy={state === "acquiring" || state === "loading"}
      onRefresh={refresh} onOpen={open} />
    {popupError ? <p role="alert" className="px-m py-xs text-sm text-danger-strong">{popupError}</p> : null}
    {revisionId ? <div className="relative flex min-h-0 flex-1 flex-col">
      <PreviewSurface viewport={viewport}>
        {navigation ? <iframe key={navigation.serial} ref={frame} src={navigation.src}
          title="项目预览" sandbox="allow-scripts allow-same-origin" referrerPolicy="no-referrer"
          onLoad={() => { if (ready.current) { window.clearTimeout(loadDeadline.current); setState("displayed"); } }}
          className="h-full w-full border-0 bg-white" /> : null}
      </PreviewSurface>
      {state !== "displayed" ? <div className="absolute inset-0 flex items-center justify-center bg-base-secondary-alt p-l">
        {state === "failed" ? <div className="max-w-[360px] space-y-m text-center">
          <p role="alert" className="text-sm text-neutral-80">{error}</p>
          <Button variant="secondary" onClick={() => setRetry(value => value + 1)}>重新加载</Button>
        </div> : <p role="status" className="text-sm text-neutral-60">正在加载预览…</p>}
      </div> : null}
    </div> : <EmptyState icon="eye" title="还没有可预览的版本" description="代码保存完成后，会在这里显示预览。" />}
  </div>;
}
