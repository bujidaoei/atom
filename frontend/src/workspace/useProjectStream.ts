import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MessageRole, RunEvent, RunEventPayload } from "../lib/types";

export type ToolStatus = "running" | "ok" | "failed";

export type TimelineItem =
  | { kind: "role"; id: string; seq: number; role: MessageRole }
  | {
      kind: "message";
      id: string;
      seq: number;
      role: MessageRole;
      runId: string | null;
      text: string;
      thinking: string;
      thinkingActive: boolean;
      streaming: boolean;
    }
  | {
      kind: "tool";
      id: string;
      seq: number;
      role: MessageRole | null;
      toolName: string;
      argSummary: string;
      status: ToolStatus;
      detail: string;
    }
  | {
      kind: "error";
      id: string;
      seq: number;
      role: MessageRole | null;
      message: string;
    };

export type HeatActivity = {
  label: string;
  at: string;
};

export type ConnectionState = "idle" | "connecting" | "open" | "retrying";

type StreamState = {
  items: TimelineItem[];
  /** Run ids the stream owns; persisted messages for these are hidden. */
  runIds: string[];
  inputTokens: number;
  outputTokens: number;
  activeRole: MessageRole | null;
  heatActivity: Record<string, HeatActivity>;
};

const EMPTY: StreamState = {
  items: [],
  runIds: [],
  inputTokens: 0,
  outputTokens: 0,
  activeRole: null,
  heatActivity: {},
};

/** Turn a tool's args into a one-line summary, e.g. `write  index.html`. */
export function summarizeArgs(args: RunEventPayload["args"]): string {
  if (args === null || args === undefined) return "";
  if (typeof args === "string") return truncate(args);

  const preferred = ["path", "file", "filename", "file_path", "url", "query", "command", "pattern"];
  for (const key of preferred) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return truncate(value.trim());
  }
  for (const value of Object.values(args)) {
    if (typeof value === "string" && value.trim()) return truncate(value.trim());
    if (typeof value === "number") return String(value);
  }
  return "";
}

function truncate(value: string, max = 80): string {
  const single = value.replace(/\s+/g, " ").trim();
  return single.length > max ? `${single.slice(0, max)}…` : single;
}

function resultText(result: unknown): string {
  if (typeof result === "string") return truncate(result, 160);
  if (result && typeof result === "object") {
    const record = result as Record<string, unknown>;
    for (const key of ["message", "detail", "error", "summary"]) {
      const value = record[key];
      if (typeof value === "string" && value.trim()) return truncate(value.trim(), 160);
    }
  }
  return "";
}

function openMessage(
  items: TimelineItem[],
  role: MessageRole,
  runId: string | null,
): { index: number; item: Extract<TimelineItem, { kind: "message" }> } | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.kind === "message" && item.streaming && item.role === role && item.runId === runId) {
      return { index, item };
    }
    // A later role taking over closes the previous speaker's bubble.
    if (item.kind === "message" && item.streaming && item.role !== role) break;
  }
  return null;
}

function replace(items: TimelineItem[], index: number, next: TimelineItem): TimelineItem[] {
  const copy = items.slice();
  copy[index] = next;
  return copy;
}

function reduceEvent(state: StreamState, event: RunEvent): StreamState {
  const role = (event.role ?? null) as MessageRole | null;
  const payload = event.payload ?? {};
  const heatId = payload.heatId;

  // Race heats run in parallel workspaces; their noise stays out of the main thread.
  if (heatId) {
    return {
      ...state,
      heatActivity: {
        ...state.heatActivity,
        [heatId]: { label: heatLabel(event.type, payload), at: event.at },
      },
    };
  }

  const runIds =
    event.runId && !state.runIds.includes(event.runId)
      ? [...state.runIds, event.runId]
      : state.runIds;
  const base = { ...state, runIds };

  switch (event.type) {
    case "squad.role_started": {
      const next = (payload.role ?? role) as MessageRole | null;
      if (!next) return base;
      const last = base.items[base.items.length - 1];
      if (last && last.kind === "role" && last.role === next) return { ...base, activeRole: next };
      return {
        ...base,
        activeRole: next,
        items: [...base.items, { kind: "role", id: `role-${event.seq}`, seq: event.seq, role: next }],
      };
    }

    case "run.started": {
      return { ...base, activeRole: role ?? base.activeRole };
    }

    case "thinking.delta": {
      if (!role || !payload.delta) return base;
      const found = openMessage(base.items, role, event.runId);
      if (!found) {
        return {
          ...base,
          activeRole: role,
          items: [
            ...base.items,
            {
              kind: "message",
              id: `msg-${event.seq}`,
              seq: event.seq,
              role,
              runId: event.runId,
              text: "",
              thinking: payload.delta,
              thinkingActive: true,
              streaming: true,
            },
          ],
        };
      }
      return {
        ...base,
        activeRole: role,
        items: replace(base.items, found.index, {
          ...found.item,
          thinking: found.item.thinking + payload.delta,
          thinkingActive: true,
        }),
      };
    }

    case "message.delta": {
      if (!role || !payload.delta) return base;
      const found = openMessage(base.items, role, event.runId);
      if (!found) {
        return {
          ...base,
          activeRole: role,
          items: [
            ...base.items,
            {
              kind: "message",
              id: `msg-${event.seq}`,
              seq: event.seq,
              role,
              runId: event.runId,
              text: payload.delta,
              thinking: "",
              thinkingActive: false,
              streaming: true,
            },
          ],
        };
      }
      return {
        ...base,
        activeRole: role,
        items: replace(base.items, found.index, {
          ...found.item,
          text: found.item.text + payload.delta,
          thinkingActive: false,
        }),
      };
    }

    case "message.completed": {
      if (!role) return base;
      const found = openMessage(base.items, role, event.runId);
      const text = payload.text ?? found?.item.text ?? "";
      if (!found) {
        if (!text) return base;
        return {
          ...base,
          items: [
            ...base.items,
            {
              kind: "message",
              id: `msg-${event.seq}`,
              seq: event.seq,
              role,
              runId: event.runId,
              text,
              thinking: "",
              thinkingActive: false,
              streaming: false,
            },
          ],
        };
      }
      return {
        ...base,
        items: replace(base.items, found.index, {
          ...found.item,
          text,
          thinkingActive: false,
          streaming: false,
        }),
      };
    }

    case "tool.started": {
      return {
        ...base,
        items: [
          ...base.items,
          {
            kind: "tool",
            id: `tool-${event.seq}`,
            seq: event.seq,
            role,
            toolName: payload.toolName ?? "tool",
            argSummary: summarizeArgs(payload.args),
            status: "running",
            detail: "",
          },
        ],
      };
    }

    case "tool.completed":
    case "tool.failed": {
      const status: ToolStatus = event.type === "tool.failed" ? "failed" : "ok";
      for (let index = base.items.length - 1; index >= 0; index -= 1) {
        const item = base.items[index];
        if (
          item.kind === "tool" &&
          item.status === "running" &&
          (!payload.toolName || item.toolName === payload.toolName)
        ) {
          return {
            ...base,
            items: replace(base.items, index, {
              ...item,
              status,
              detail: resultText(payload.result),
            }),
          };
        }
      }
      return base;
    }

    case "usage.updated": {
      return {
        ...base,
        inputTokens: base.inputTokens + (payload.inputTokens ?? 0),
        outputTokens: base.outputTokens + (payload.outputTokens ?? 0),
      };
    }

    case "run.completed": {
      const items = base.items.map((item) =>
        item.kind === "message" && item.streaming && item.runId === event.runId
          ? { ...item, streaming: false, thinkingActive: false }
          : item,
      );
      const hasText = items.some(
        (item) => item.kind === "message" && item.runId === event.runId && item.text.trim(),
      );
      if (!hasText && payload.resultText && role) {
        items.push({
          kind: "message",
          id: `msg-${event.seq}`,
          seq: event.seq,
          role,
          runId: event.runId,
          text: payload.resultText,
          thinking: "",
          thinkingActive: false,
          streaming: false,
        });
      }
      return { ...base, items, activeRole: null };
    }

    case "run.failed": {
      const items = base.items.map((item) =>
        item.kind === "message" && item.streaming && item.runId === event.runId
          ? { ...item, streaming: false, thinkingActive: false }
          : item,
      );
      return {
        ...base,
        activeRole: null,
        items: [
          ...items,
          {
            kind: "error",
            id: `err-${event.seq}`,
            seq: event.seq,
            role,
            message: payload.message ?? "这一步失败了。",
          },
        ],
      };
    }

    default:
      return base;
  }
}

function heatLabel(type: string, payload: RunEventPayload): string {
  switch (type) {
    case "tool.started":
      return `${payload.toolName ?? "tool"} ${summarizeArgs(payload.args)}`.trim();
    case "tool.completed":
      return `完成 ${payload.toolName ?? "tool"}`;
    case "tool.failed":
      return `失败 ${payload.toolName ?? "tool"}`;
    case "thinking.delta":
      return "思考中";
    case "message.delta":
      return "输出中";
    case "run.completed":
      return "已完成";
    case "run.failed":
      return payload.message ?? "运行失败";
    default:
      return type;
  }
}

type UseProjectStreamOptions = {
  projectId: string | undefined;
  enabled: boolean;
  /** Fired on `project.updated` so the caller can refetch the project. */
  onProjectUpdated: (payload: RunEventPayload) => void;
};

export function useProjectStream({ projectId, enabled, onProjectUpdated }: UseProjectStreamOptions) {
  const [state, setState] = useState<StreamState>(EMPTY);
  const [connection, setConnection] = useState<ConnectionState>("idle");
  const lastSeq = useRef(0);
  const attempt = useRef(0);
  const [reconnectKey, setReconnectKey] = useState(0);
  const updatedRef = useRef(onProjectUpdated);
  updatedRef.current = onProjectUpdated;

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
      `/api/projects/${projectId}/events?after=${lastSeq.current}`,
      { withCredentials: true },
    );

    function handle(raw: MessageEvent<string>) {
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
        return;
      }
      setState((current) => reduceEvent(current, event));
    }

    source.addEventListener("open", () => {
      if (!closed) setConnection("open");
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
