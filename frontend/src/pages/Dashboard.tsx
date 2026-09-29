import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, readError } from "../api";
import { useSession } from "../session";
import type { ProjectSummary, Usage } from "../types";
import { Button, Wordmark, formatWhen, inputClass, statusLabel } from "../ui";

export function DashboardPage() {
  const { user, setUser } = useSession();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState("");

  useEffect(() => {
    document.title = "工作台 · Atom";
    api.projects().then(setProjects).catch((err) => setError(readError(err)));
    api.usage().then(setUsage).catch(() => setUsage(null));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (prompt.trim().length < 4) {
      setError("再多写一句");
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

  async function logout() {
    await api.logout();
    setUser(null);
    navigate("/");
  }

  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-6 border-b border-line px-5 py-4 md:px-10">
        <Wordmark to="/app" />
        <Link to="/app/settings" className="text-sm text-muted hover:text-ink">
          网关设置
        </Link>
        <div className="ml-auto flex items-center gap-4 text-sm">
          <span className="text-muted">{user?.name}</span>
          <button type="button" onClick={logout} className="hover:text-copper">
            退出
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-5 py-10 md:px-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h1 className="font-display text-5xl font-medium tracking-[-0.03em]">项目</h1>
          <p className="text-sm text-muted">
            {usage
              ? `已调用 ${usage.calls} 次 · 输入 ${usage.prompt_tokens.toLocaleString("zh-CN")} / 输出 ${usage.completion_tokens.toLocaleString("zh-CN")} tokens`
              : "用量还在读取"}
          </p>
        </div>

        <form className="mt-8" onSubmit={create}>
          <label htmlFor="next-idea" className="text-sm">
            新的想法
          </label>
          <textarea
            id="next-idea"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={3}
            className={`${inputClass} mt-2`}
            placeholder="谁在用，第一版要能完成什么。"
          />
          <Button type="submit" className="mt-3" disabled={busy}>
            {busy ? "正在创建" : "创建项目"}
          </Button>
        </form>

        {error ? <p className="mt-4 text-sm text-clay">{error}</p> : null}

        <div className="mt-10 border-t border-line">
          {projects.length === 0 ? (
            <p className="py-8 text-sm text-muted">还没有项目。上面写下一句，就会从契约开始。</p>
          ) : (
            <ul>
              {projects.map((project) => (
                <li key={project.id} className="grid items-center gap-3 border-b border-line py-4 md:grid-cols-[1fr_120px_140px_auto]">
                  <div className="min-w-0">
                    <Link to={`/app/p/${project.id}`} className="text-base hover:text-copper">
                      {project.name || "未命名"}
                    </Link>
                    <p className="truncate text-sm text-muted">{project.prompt}</p>
                  </div>
                  <span className="text-sm text-muted">{statusLabel[project.status] || project.status}</span>
                  <span className="text-sm text-muted">{formatWhen(project.updated_at)}</span>
                  <div className="flex gap-3 text-sm">
                    <Link to={`/app/p/${project.id}`}>打开</Link>
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
        </div>
      </main>
    </div>
  );
}
