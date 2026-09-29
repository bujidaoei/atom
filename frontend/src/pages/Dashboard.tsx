import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AgentFace, team } from "../agents";
import { api, readError } from "../api";
import { AppShell } from "../Shell";
import { useSession } from "../session";
import type { ProjectSummary, Usage } from "../types";
import { Button, formatWhen, statusLabel } from "../ui";

const starters = [
  "给街角咖啡馆做一个今日烘焙看板，店员能把卖完的标出来，刷新后还在",
  "给自由职业者做一个回款记录，能记下客户、金额和有没有到账",
  "做一个小面试表，记下候选人、时间和一句备注",
];

export function DashboardPage() {
  const { user } = useSession();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState("");

  useEffect(() => {
    document.title = "首页 · Atom";
    api.projects().then(setProjects).catch((err) => setError(readError(err)));
    api.usage().then(setUsage).catch(() => setUsage(null));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (prompt.trim().length < 4) {
      setError("再多写一句，小队才知道要做什么");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const project = await api.createProject(prompt.trim());
      navigate(`/app/p/${project.id}`);
    } catch (err) {
      setError(readError(err));
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setError("");
    try {
      await api.deleteProject(id);
      setProjects((current) => current.filter((item) => item.id !== id));
      setConfirmId("");
    } catch (err) {
      setError(readError(err));
    }
  }

  return (
    <AppShell>
      <div className="flex justify-end px-6 py-3 text-sm text-muted">
        {usage ? `已调用 ${usage.calls} 次` : "用量读取中"}
      </div>
      <div className="mx-auto flex w-full max-w-2xl flex-col items-center px-5 pb-20">
        <ul className="flex items-end gap-2">
          {team.map((person) => (
            <li key={person.id} className="text-center">
              <AgentFace name={person.name} fill={person.fill} mouth={person.mouth} />
              <span className="mt-1 block text-[11px] text-muted">{person.name}</span>
            </li>
          ))}
        </ul>
        <h1 className="mt-6 text-center font-display text-[clamp(2.1rem,4vw,3.25rem)] font-medium leading-tight tracking-[-0.03em]">
          你想创造什么{user?.name ? `，${user.name}` : ""}？
        </h1>
        <form onSubmit={create} className="mt-8 w-full rounded-2xl border border-line bg-raised p-4 shadow-sheet">
          <label htmlFor="idea" className="sr-only">
            想做什么
          </label>
          <textarea
            id="idea"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={3}
            placeholder="请 Alex 做一个能用的小页面。写清谁在用、第一版要完成什么。"
            className="w-full resize-none bg-transparent text-base leading-7 outline-none placeholder:text-muted/70"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <p className="text-xs leading-5 text-muted">小队先写契约。你点头之后，页面才会出现在右边。</p>
            <Button type="submit" disabled={busy}>
              {busy ? "正在交给小队" : "构建"}
            </Button>
          </div>
        </form>
        {error ? <p className="mt-3 w-full text-sm text-clay">{error}</p> : null}
        <div className="mt-4 flex w-full flex-wrap gap-2">
          {starters.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setPrompt(item)}
              className="rounded-full border border-line bg-raised px-3 py-1.5 text-left text-xs text-muted hover:border-ink/30 hover:text-ink"
            >
              {item.slice(0, 18)}…
            </button>
          ))}
        </div>

        <section id="projects" className="mt-16 w-full scroll-mt-8">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-medium">我的项目</h2>
            <span className="text-xs text-muted">{projects.length} 个</span>
          </div>
          {projects.length === 0 ? (
            <p className="mt-4 text-sm text-muted">还没有项目。上面写下一句，就会从契约开始。</p>
          ) : (
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {projects.map((project) => (
                <li key={project.id} className="grid items-center gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_88px_auto]">
                  <div className="min-w-0">
                    <Link to={`/app/p/${project.id}`} className="hover:text-copper">
                      {project.name || "未命名"}
                    </Link>
                    <p className="truncate text-sm text-muted">{project.prompt}</p>
                  </div>
                  <span className="text-sm text-muted">{statusLabel[project.status] || project.status}</span>
                  <div className="flex items-center gap-3 text-sm">
                    <span className="text-muted">{formatWhen(project.updated_at)}</span>
                    {confirmId === project.id ? (
                      <button type="button" className="text-clay" onClick={() => remove(project.id)}>
                        确认删除
                      </button>
                    ) : (
                      <button type="button" className="text-muted hover:text-ink" onClick={() => setConfirmId(project.id)}>
                        删除
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </AppShell>
  );
}
