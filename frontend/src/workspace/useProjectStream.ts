import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, openProjectStream } from "../lib/api";
import type { ProjectStatus, RunEvent, RunEventPayload } from "../lib/types";
import { EMPTY, reduceEvent, type StreamState, type ConnectionState } from "./stream-state";
import { splitSseFrames } from "./sse-frames";
export type { TimelineItem, ToolStatus, HeatActivity } from "./stream-state";

type UseProjectStreamOptions = {
  projectId: string | undefined;
  enabled: boolean;
  snapshotStatus?: ProjectStatus;
  snapshotEventSeq?: number;
  /** Fired on `project.updated` so the caller can refetch the project. */
  onProjectUpdated: (payload: RunEventPayload) => void;
};

export function useProjectStream({ projectId, enabled, snapshotStatus, snapshotEventSeq, onProjectUpdated }: UseProjectStreamOptions) {
  const [state, setState] = useState<StreamState>(EMPTY);
  const [connection, setConnection] = useState<ConnectionState>("idle");
  const lastSeq = useRef(0);
  const attempt = useRef(0);
  const [reconnectKey, setReconnectKey] = useState(0);
  const updatedRef = useRef(onProjectUpdated);
  updatedRef.current = onProjectUpdated;
  const snapshotSeq = useRef(snapshotEventSeq);
  snapshotSeq.current = snapshotEventSeq;
  const pendingUpdate = useRef<RunEvent | null>(null);
  const connectedOnce = useRef(false);
  useEffect(() => {
    const pending = pendingUpdate.current;
    if (snapshotEventSeq === undefined || !pending) return;
    pendingUpdate.current = null;
    if (pending.seq > snapshotEventSeq) updatedRef.current(pending.payload ?? {});
  }, [snapshotEventSeq]);
  useEffect(() => {
    if (!snapshotStatus || ["planning", "building"].includes(snapshotStatus)) return;
    setState(current => reduceEvent(current, { seq: 0, runId: null, role: null,
      type: "project.updated", payload: { status: snapshotStatus }, at: "" }));
  }, [snapshotStatus]);

  // Switching projects resets the whole thread.
  useEffect(() => {
    lastSeq.current = 0;
    attempt.current = 0;
    pendingUpdate.current = null;
    connectedOnce.current = false;
    setState(EMPTY);
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !enabled) {
      setConnection("idle");
      return;
    }

    let closed = false;
    let retryTimer: number | undefined;
    const controller = new AbortController();
    const currentProjectId = projectId;

    setConnection((current) => (current === "retrying" ? current : "connecting"));

    function handle(raw: string) {
      if (closed) return;
      let event: RunEvent;
      try {
        event = JSON.parse(raw) as RunEvent;
      } catch {
        return;
      }
      if (typeof event.seq !== "number") return;
      // Reconnects replay history; anything we already applied is skipped.
      if (event.seq <= lastSeq.current) return;
      lastSeq.current = event.seq;
      attempt.current = 0;

      if (event.type === "project.updated") {
        if (snapshotSeq.current === undefined) pendingUpdate.current = event;
        else if (event.seq > snapshotSeq.current) updatedRef.current(event.payload ?? {});
      }
      setState((current) => reduceEvent(current, event));
    }

    async function connect() {
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      try {
        const body = await openProjectStream(currentProjectId, lastSeq.current,
          controller.signal);
        if (closed) return;
        reader = body.getReader();
        setConnection("open");
        if (connectedOnce.current) updatedRef.current({});
        connectedOnce.current = true;
        const decoder = new TextDecoder();
        let pending = "";
        while (!closed) {
          const chunk = await reader.read();
          if (chunk.done) throw new Error("stream_closed");
          const parsed = splitSseFrames(
            pending + decoder.decode(chunk.value, { stream: true }));
          pending = parsed.pending;
          for (const frame of parsed.frames) {
            if (frame.event === "run" || frame.event === "message") handle(frame.data);
          }
        }
      } catch (error) {
        if (closed || controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          setConnection("idle");
          return;
        }
        setConnection("retrying");
        attempt.current += 1;
        const delay = Math.min(1000 * 2 ** (attempt.current - 1), 15000);
        retryTimer = window.setTimeout(() => setReconnectKey((key) => key + 1), delay);
      } finally {
        reader?.releaseLock();
      }
    }

    void connect();

    return () => {
      closed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      controller.abort();
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
