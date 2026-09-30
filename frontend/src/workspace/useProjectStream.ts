import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { withBase } from "../lib/api";
import type { ProjectStatus, RunEvent, RunEventPayload } from "../lib/types";
import { EMPTY, reduceEvent, type StreamState, type ConnectionState } from "./stream-state";
export type { TimelineItem, ToolStatus, HeatActivity } from "./stream-state";

type UseProjectStreamOptions = {
  projectId: string | undefined;
  enabled: boolean;
  snapshotStatus?: ProjectStatus;
  /** Fired on `project.updated` so the caller can refetch the project. */
  onProjectUpdated: (payload: RunEventPayload) => void;
};

export function useProjectStream({ projectId, enabled, snapshotStatus, onProjectUpdated }: UseProjectStreamOptions) {
  const [state, setState] = useState<StreamState>(EMPTY);
  const [connection, setConnection] = useState<ConnectionState>("idle");
  const lastSeq = useRef(0);
  const attempt = useRef(0);
  const [reconnectKey, setReconnectKey] = useState(0);
  const updatedRef = useRef(onProjectUpdated);
  updatedRef.current = onProjectUpdated;
  useEffect(() => {
    if (!snapshotStatus || ["planning", "building"].includes(snapshotStatus)) return;
    setState(current => reduceEvent(current, { seq: 0, runId: null, role: null,
      type: "project.updated", payload: { status: snapshotStatus }, at: "" }));
  }, [snapshotStatus]);

  // Switching projects resets the whole thread.
  useEffect(() => {
    lastSeq.current = 0;
    attempt.current = 0;
    setState(EMPTY);
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !enabled) {
      setConnection("idle");
      return;
    }

    let closed = false;
    let retryTimer: number | undefined;

    setConnection((current) => (current === "retrying" ? current : "connecting"));
    const source = new EventSource(
      withBase(`/api/projects/${projectId}/events?after=${lastSeq.current}`),
      { withCredentials: true },
    );

    function handle(raw: MessageEvent<string>) {
      if (closed) return;
      let event: RunEvent;
      try {
        event = JSON.parse(raw.data) as RunEvent;
      } catch {
        return;
      }
      if (typeof event.seq !== "number") return;
      // Reconnects replay history; anything we already applied is skipped.
      if (event.seq <= lastSeq.current) return;
      lastSeq.current = event.seq;
      attempt.current = 0;

      if (event.type === "project.updated") {
        updatedRef.current(event.payload ?? {});
      }
      setState((current) => reduceEvent(current, event));
    }

    source.addEventListener("open", () => {
      if (!closed) { setConnection("open"); updatedRef.current({}); }
    });
    source.addEventListener("run", handle as EventListener);
    source.addEventListener("message", handle as EventListener);
    source.addEventListener("error", () => {
      if (closed) return;
      source.close();
      setConnection("retrying");
      attempt.current += 1;
      const delay = Math.min(1000 * 2 ** (attempt.current - 1), 15000);
      retryTimer = window.setTimeout(() => setReconnectKey((key) => key + 1), delay);
    });

    return () => {
      closed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      source.close();
    };
  }, [projectId, enabled, reconnectKey]);

  const reconnectNow = useCallback(() => {
    attempt.current = 0;
    setReconnectKey((key) => key + 1);
  }, []);

  const runIdSet = useMemo(() => new Set(state.runIds), [state.runIds]);

  return {
    items: state.items,
    runIdSet,
    activeRole: state.activeRole,
    inputTokens: state.inputTokens,
    outputTokens: state.outputTokens,
    heatActivity: state.heatActivity,
    connection,
    reconnectNow,
  };
}
