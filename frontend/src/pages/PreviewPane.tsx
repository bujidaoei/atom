import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import type { Requirement, RuntimeResult } from "../types";
import { instrumentHtml, probeFrame } from "../preview";

export function PreviewPane({
  projectId,
  html,
  previewState,
  requirements,
  probeRef,
  onStateError,
}: {
  projectId: string;
  html: string;
  previewState: Record<string, string>;
  requirements: Requirement[];
  probeRef: MutableRefObject<(() => Promise<RuntimeResult[]>) | null>;
  onStateError: (message: string) => void;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const boot = useMemo(
    () => ({ html, state: previewState, nonce: crypto.randomUUID() }),
    // Preview state is captured when the page HTML changes. Later saves must not reload the frame.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [html],
  );
  const srcDoc = useMemo(() => (html ? instrumentHtml(boot.html, boot.state, boot.nonce) : ""), [boot, html]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(false);
  }, [srcDoc]);

  useEffect(() => {
    probeRef.current = async () => {
      const frame = frameRef.current;
      if (!frame || !ready) throw new Error("预览还没准备好");
      return probeFrame(frame, boot.nonce, requirements);
    };
    return () => {
      probeRef.current = null;
    };
  }, [boot.nonce, probeRef, ready, requirements]);

  useEffect(() => {
    const nonce = boot.nonce;
    let timer = 0;
    function onMessage(event: MessageEvent) {
      const data = event.data as { source?: string; nonce?: string; type?: string; snapshot?: Record<string, string> };
      if (!data || data.source !== "atom-preview" || data.nonce !== nonce || data.type !== "state" || !data.snapshot) {
        return;
      }
      window.clearTimeout(timer);
      const snapshot = data.snapshot;
      timer = window.setTimeout(() => {
        fetch(`/api/projects/${projectId}/preview-state`, {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ snapshot }),
        }).catch(() => onStateError("预览里的修改没能存上"));
      }, 400);
    }
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(timer);
    };
  }, [boot.nonce, onStateError, projectId]);

  if (!html) {
    return (
      <div className="flex h-full items-center px-6">
        <p className="max-w-xs text-sm leading-6 text-muted">锁定契约之后，页面会出现在这里。你可以在里面点击，改动会写回这个项目。</p>
      </div>
    );
  }

  return (
    <iframe
      ref={frameRef}
      title="应用预览"
      sandbox="allow-scripts allow-forms allow-modals"
      srcDoc={srcDoc}
      onLoad={() => setReady(true)}
      className="h-full min-h-[480px] w-full bg-white lg:min-h-0"
    />
  );
}
