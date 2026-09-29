import { useState } from "react";
import { AGENTS, UPCOMING_AGENTS } from "../lib/agents";
import type { AgentRole } from "../lib/types";
import { AgentAvatar, PlaceholderAvatar } from "./AgentAvatar";
import type { AvatarSize } from "./AgentAvatar";

type AgentRowProps = {
  size?: AvatarSize;
  activeRole?: AgentRole | null;
  showUpcoming?: boolean;
  className?: string;
};

/** The squad line-up. Hovering a member explains what they do in the run. */
export function AgentRow({
  size = "lg",
  activeRole = null,
  showUpcoming = true,
  className = "",
}: AgentRowProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const detail =
    AGENTS.find((agent) => agent.name === hovered) ??
    (activeRole ? AGENTS.find((agent) => agent.role === activeRole) : undefined);
  const upcoming = UPCOMING_AGENTS.find((agent) => agent.name === hovered);

  return (
    <div className={`flex flex-col items-center gap-s ${className}`}>
      <div className="flex items-end gap-s" onMouseLeave={() => setHovered(null)}>
        {AGENTS.map((agent) => (
          <button
            key={agent.role}
            type="button"
            onMouseEnter={() => setHovered(agent.name)}
            onFocus={() => setHovered(agent.name)}
            onBlur={() => setHovered(null)}
            aria-label={`${agent.name} · ${agent.title}`}
            className="group rounded-full transition-transform duration-ui ease-ui hover:-translate-y-[3px] focus-visible:-translate-y-[3px] active:translate-y-0"
          >
            <AgentAvatar role={agent.role} size={size} active={activeRole === agent.role} />
          </button>
        ))}

        {showUpcoming ? (
          <>
            <span className="mx-xxs h-6 w-px self-center bg-neutral-16" aria-hidden="true" />
            {UPCOMING_AGENTS.map((agent) => (
              <button
                key={agent.name}
                type="button"
                onMouseEnter={() => setHovered(agent.name)}
                onFocus={() => setHovered(agent.name)}
                onBlur={() => setHovered(null)}
                aria-label={`${agent.name} · ${agent.title}（未启用）`}
                className="rounded-full opacity-60 transition-opacity duration-ui ease-ui hover:opacity-100 focus-visible:opacity-100"
              >
                <PlaceholderAvatar initial={agent.name.charAt(0)} size={size} />
              </button>
            ))}
          </>
        ) : null}
      </div>

      <p className="h-5 text-center text-sm text-neutral-60">
        {upcoming ? (
          <>
            <span className="text-neutral-80">{upcoming.name}</span> · {upcoming.title} · 本 Demo 未启用
          </>
        ) : detail ? (
          <>
            <span className="text-neutral-80">{detail.name}</span> · {detail.title} · {detail.blurb}
          </>
        ) : (
          <>5 位 agent 接力：规划 → 调研 → 契约 → 架构 → 编码</>
        )}
      </p>
    </div>
  );
}
