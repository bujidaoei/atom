export const team = [
  { id: "mike", name: "Mike", job: "带队", fill: "#1c1915", mouth: "M22 40c3 4 17 4 20 0" },
  { id: "iris", name: "Iris", job: "研究", fill: "#21593f", mouth: "M24 41h16" },
  { id: "emma", name: "Emma", job: "契约", fill: "#8f4318", mouth: "M23 39c2.2 3.2 15.8 3.2 18 0" },
  { id: "bob", name: "Bob", job: "结构", fill: "#31425c", mouth: "M24 42c2-3 14-3 16 0" },
  { id: "alex", name: "Alex", job: "工程", fill: "#8d3b32", mouth: "M22 40c3 5 17 5 20 0" },
] as const;

export function AgentFace({
  name,
  fill,
  mouth,
  className = "h-12 w-12",
}: {
  name: string;
  fill: string;
  mouth: string;
  className?: string;
}) {
  return (
    <svg viewBox="0 0 64 64" className={className} role="img" aria-label={name}>
      <circle cx="32" cy="34" r="22" fill={fill} />
      <path d="M16 30c2-14 30-16 34-2" fill={fill} />
      <circle cx="25" cy="34" r="2.2" fill="#fbf8f3" />
      <circle cx="39" cy="34" r="2.2" fill="#fbf8f3" />
      <path d={mouth} fill="none" stroke="#fbf8f3" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
