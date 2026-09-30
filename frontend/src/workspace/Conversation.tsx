import { useEffect, useMemo, useRef } from "react";
import type { ReactNode } from "react";
import { AgentAvatar } from "../components/AgentAvatar";
import { Icon } from "../components/ui/Icon";
import { EmptyState } from "../components/ui/States";
import { agentMeta, roleLabel } from "../lib/agents";
import { formatTime } from "../lib/format";
import type { Message, MessageRole } from "../lib/types";
import { MessageText } from "./MessageText";
import { ThinkingBlock } from "./ThinkingBlock";
import { ToolCard } from "./ToolCard";
import type { TimelineItem } from "./useProjectStream";

type ConversationProps = {
  messages: Message[];
  items: TimelineItem[];
  /** Run ids owned by the live stream; their persisted twins stay hidden. */
  liveRunIds: Set<string>;
  starting: boolean;
};

export function Conversation({ messages, items, liveRunIds, starting }: ConversationProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const persisted = useMemo(
    () => messages.filter((message) => !(message.runId && liveRunIds.has(message.runId))),
    [messages, liveRunIds],
  );

  // Stay pinned to the bottom unless the reader scrolled up to re-read.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !pinned.current) return;
    node.scrollTop = node.scrollHeight;
  }, [persisted, items, starting]);

  const empty = persisted.length === 0 && items.length === 0 && !starting;

  return (
    <div
      ref={scrollRef}
      onScroll={(event) => {
        const node = event.currentTarget;
        pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
      }}
      className="flex-1 overflow-y-auto px-l py-l"
    >
      <div className="mx-auto flex max-w-[680px] flex-col gap-l">
        {empty ? (
          <EmptyState
            title="还没有对话"
            description="规划一开始，Mike 会先在这里说明他的拆解思路。"
          />
        ) : null}

        {persisted.map((message) => (
          <PersistedMessage key={message.id} message={message} />
        ))}

        {items.map((item) => (
          <TimelineRow key={item.id} item={item} />
        ))}

        {starting ? (
          <p className="flex items-center gap-xs text-sm text-neutral-60">
            <span className="shimmer-text">正在唤起 squad…</span>
          </p>
        ) : null}
      </div>
    </div>
  );
}

function PersistedMessage({ message }: { message: Message }) {
  if (message.role === "user") {
    return <UserBubble content={message.content} at={message.createdAt} />;
  }
  if (message.role === "system") {
    return <SystemNote content={message.content} />;
  }
  return (
    <AgentBlock role={message.role} at={message.createdAt}>
      <MessageText content={message.content} />
    </AgentBlock>
  );
}

function TimelineRow({ item }: { item: TimelineItem }) {
  switch (item.kind) {
    case "role":
      return <RoleDivider role={item.role} />;
    case "tool":
      return (
        <div className="animate-fade-in pl-xxl">
          <ToolCard
            toolName={item.toolName}
            argSummary={item.argSummary}
            status={item.status}
            detail={item.detail}
          />
        </div>
      );
    case "error":
      return (
        <div
          role="alert"
          className="hairline flex items-start gap-xs rounded-m border-danger-edge bg-danger-surface px-m py-s"
        >
          <Icon name="alert" size={14} className="mt-[3px] text-danger-strong" />
          <p className="text-base text-neutral-95">
            <span className="font-medium text-danger-strong">
              {roleLabel(item.role)} 失败：
            </span>{" "}
            {item.message}
          </p>
        </div>
      );
    case "notice":
      return <SystemNote content={item.message} />;
    case "message":
      return (
        <AgentBlock role={item.role} streaming={item.streaming}>
          <ThinkingBlock text={item.thinking} active={item.thinkingActive} />
          <MessageText content={item.text} />
          {item.streaming && !item.text ? (
            <p className="text-sm text-neutral-40">
              <span className="shimmer-text">正在组织回答…</span>
            </p>
          ) : null}
        </AgentBlock>
      );
    default:
      return null;
  }
}

function UserBubble({ content, at }: { content: string; at?: string }) {
  return (
    <div className="flex flex-col items-end gap-xxs">
      <div className="max-w-[86%] rounded-l rounded-br-[4px] bg-brand-alpha-strong px-m py-s">
        <p className="whitespace-pre-wrap break-words text-base leading-6 text-neutral-95">
          {content}
        </p>
      </div>
      {at ? <span className="pr-xxs text-xs text-neutral-40">{formatTime(at)}</span> : null}
    </div>
  );
}

function SystemNote({ content }: { content: string }) {
  return (
    <p className="mx-auto max-w-[80%] text-center text-sm leading-5 text-neutral-60">{content}</p>
  );
}

function AgentBlock({
  role,
  at,
  streaming = false,
  children,
}: {
  role: MessageRole;
  at?: string;
  streaming?: boolean;
  children: ReactNode;
}) {
  const meta = agentMeta(role);
  return (
    <div className="flex animate-fade-in gap-s">
      <AgentAvatar role={role} size="md" active={streaming} />
      <div className="min-w-0 flex-1">
        <div className="mb-xxs flex items-baseline gap-xs">
          <span className="text-base font-medium text-neutral-95">{roleLabel(role)}</span>
          {meta ? <span className="text-xs text-neutral-40">{meta.title}</span> : null}
          {at ? <span className="ml-auto text-xs text-neutral-40">{formatTime(at)}</span> : null}
        </div>
        <div className="flex flex-col gap-s">{children}</div>
      </div>
    </div>
  );
}

function RoleDivider({ role }: { role: MessageRole }) {
  const meta = agentMeta(role);
  return (
    <div className="flex items-center gap-s py-xxs" role="separator" aria-label={`${roleLabel(role)} 接手`}>
      <span className="h-px flex-1 bg-neutral-12" />
      <span className="hairline flex items-center gap-xs rounded-full border-neutral-12 bg-base-tertiary px-s py-[2px]">
        <AgentAvatar role={role} size="xs" />
        <span className="text-xs text-neutral-60">
          {roleLabel(role)} 接手{meta ? ` · ${meta.title}` : ""}
        </span>
      </span>
      <span className="h-px flex-1 bg-neutral-12" />
    </div>
  );
}
