import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { api } from "./api";
import { useSession } from "./session";
import type { ProjectSummary } from "./types";
import { Wordmark } from "./ui";

const itemClass = ({ isActive }: { isActive: boolean }) =>
  `flex h-9 items-center rounded-lg px-3 text-sm ${isActive ? "bg-ink/10 text-ink" : "text-muted hover:bg-ink/5 hover:text-ink"}`;

export function AppShell({ children }: { children: ReactNode }) {
  const { user, setUser } = useSession();
  const navigate = useNavigate();
  const [recent, setRecent] = useState<ProjectSummary[]>([]);

  useEffect(() => {
    api.projects().then(setRecent).catch(() => setRecent([]));
  }, []);

  async function logout() {
    await api.logout();
    setUser(null);
    navigate("/");
  }

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="border-b border-line bg-[#ebe4d8] md:sticky md:top-0 md:flex md:h-screen md:flex-col md:border-b-0 md:border-r">
        <div className="px-4 pb-2 pt-4">
          <Wordmark to="/app" />
          <p className="mt-4 truncate text-sm">{user?.name ? `${user.name} 的 Atom` : "Atom"}</p>
        </div>
        <nav className="flex gap-1 px-3 py-2 md:flex-col">
          <NavLink to="/app" end className={itemClass}>
            首页
          </NavLink>
          <Link to="/app#projects" className="flex h-9 items-center rounded-lg px-3 text-sm text-muted hover:bg-ink/5 hover:text-ink">
            我的项目
          </Link>
          <NavLink to="/app/settings" className={itemClass}>
            网关
          </NavLink>
        </nav>
        <div className="hidden px-4 pt-5 md:block">
          <p className="text-xs text-muted">最近</p>
          <ul className="mt-2 space-y-1">
            {recent.slice(0, 6).map((project) => (
              <li key={project.id}>
                <NavLink to={`/app/p/${project.id}`} className="block truncate rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-ink/5 hover:text-ink">
                  {project.name || "未命名"}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
        <button type="button" onClick={logout} className="mx-3 mb-4 mt-2 h-9 rounded-lg px-3 text-left text-sm text-muted hover:bg-ink/5 hover:text-ink md:mt-auto">
          退出
        </button>
      </aside>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
