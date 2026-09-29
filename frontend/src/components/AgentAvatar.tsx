import type { AgentMeta } from "../lib/agents";
import { agentMeta } from "../lib/agents";
import type { MessageRole } from "../lib/types";

const SIZES = {
  xs: "h-5 w-5 text-2xs",
  sm: "h-6 w-6 text-xs",
  md: "h-7 w-7 text-sm",
  lg: "h-10 w-10 text-lg",
  xl: "h-12 w-12 text-2xl",
} as const;

export type AvatarSize = keyof typeof SIZES;

type AgentAvatarProps = {
  role: MessageRole | string | null;
  size?: AvatarSize;
  active?: boolean;
  className?: string;
};

/** Colored circle + initial. Never a drawn face (design-system §8). */
export function AgentAvatar({ role, size = "md", active = false, className = "" }: AgentAvatarProps) {
  const meta: AgentMeta | null = agentMeta(role);
  const initial = meta ? meta.name.charAt(0) : role === "user" ? "你" : "S";
  const tone = meta ? `${meta.bg} text-white` : "bg-neutral-20 text-neutral-80";

  return (
    <span
      className={[
        "inline-flex shrink-0 items-center justify-center rounded-full font-medium leading-none",
        SIZES[size],
        tone,
        active ? "ring-2 ring-brand ring-offset-2 ring-offset-base-default" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      aria-hidden="true"
    >
      {initial}
    </span>
  );
}

export function PlaceholderAvatar({
  initial,
  size = "lg",
}: {
  initial: string;
  size?: AvatarSize;
}) {
  return (
    <span
      className={[
        "inline-flex shrink-0 items-center justify-center rounded-full font-medium leading-none",
        SIZES[size],
        "hairline border-dashed border-neutral-40 bg-transparent text-neutral-40",
      ].join(" ")}
      aria-hidden="true"
    >
      {initial}
    </span>
  );
}
