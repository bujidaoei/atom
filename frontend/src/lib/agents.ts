import type { AgentRole, MessageRole } from "./types";

export type AgentMeta = {
  role: AgentRole;
  name: string;
  title: string;
  /** Tailwind background class bound to the agent token. */
  bg: string;
  /** What this agent contributes to the run, shown in the squad row tooltip. */
  blurb: string;
};

export const AGENTS: AgentMeta[] = [
  {
    role: "mike",
    name: "Mike",
    title: "Team Leader",
    bg: "bg-agent-mike",
    blurb: "拆解你的想法，决定这一轮谁上场。",
  },
  {
    role: "iris",
    name: "Iris",
    title: "Deep Researcher",
    bg: "bg-agent-iris",
    blurb: "查同类产品与惯例，给出参考。",
  },
  {
    role: "emma",
    name: "Emma",
    title: "Product Manager",
    bg: "bg-agent-emma",
    blurb: "写成可机检的需求与验收条件。",
  },
  {
    role: "bob",
    name: "Bob",
    title: "Architect",
    bg: "bg-agent-bob",
    blurb: "定文件结构、技术选型与数据形状。",
  },
  {
    role: "alex",
    name: "Alex",
    title: "Engineer",
    bg: "bg-agent-alex",
    blurb: "把契约写成真实可运行的多文件代码。",
  },
];

/** Shown as not-yet-enabled so the full product shape is legible. */
export const UPCOMING_AGENTS: { name: string; title: string }[] = [
  { name: "Sarah", title: "SEO Specialist" },
  { name: "Adrian", title: "Ads Strategist" },
  { name: "David", title: "Data Analyst" },
];

const BY_ROLE = new Map<string, AgentMeta>(AGENTS.map((agent) => [agent.role, agent]));

export function agentMeta(role: MessageRole | string | null): AgentMeta | null {
  if (!role) return null;
  return BY_ROLE.get(role) ?? null;
}

export function roleLabel(role: MessageRole | string | null): string {
  const meta = agentMeta(role);
  if (meta) return meta.name;
  if (role === "system") return "系统";
  if (role === "user") return "你";
  return "Atom";
}
