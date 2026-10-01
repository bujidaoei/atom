import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { useProjects } from "../lib/projects";
import { STATUS_LABEL, isRunningStatus } from "../lib/format";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";
import { IconButton } from "./ui/Button";
import { Icon } from "./ui/Icon";
import type { IconName } from "./ui/Icon";
import { Skeleton } from "./ui/States";

const COLLAPSE_KEY = "atom-sidebar-collapsed";

type SidebarProps = {
  /** Mobile drawer visibility; the rail is always rendered on >=lg. */
  mobileOpen: boolean;
  onCloseMobile: () => void;
};

export function Sidebar({ mobileOpen, onCloseMobile }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  // Expand and collapse use different curves — this is a signature Atoms detail.
  const [collapsing, setCollapsing] = useState(false);
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  function toggle() {
    setCollapsing(!collapsed);
    setCollapsed((current) => !current);
  }

  return (
    <>
      {mobileOpen ? (
        <button
          type="button"
          aria-label="关闭侧边栏"
          onClick={onCloseMobile}
          className="fixed inset-0 z-30 bg-black/30 backdrop-blur-[2px] lg:hidden"
        />
      ) : null}

      <aside
        className={[
          "sidebar-motion fixed inset-y-0 left-0 z-40 flex shrink-0 flex-col border-r border-neutral-12 bg-base-secondary lg:static lg:z-auto lg:translate-x-0",
          collapsing ? "sidebar-motion--collapsing" : "",
          collapsed ? "w-[56px]" : "w-sidebar",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        ]
          .filter(Boolean)
          .join(" ")}
        aria-label="主导航"
      >
        <SidebarHeader collapsed={collapsed} onToggle={toggle} onCloseMobile={onCloseMobile} />
        <SidebarProjects collapsed={collapsed} onNavigate={onCloseMobile} />
        <SidebarFooter collapsed={collapsed} />
      </aside>
    </>
  );
}

function SidebarHeader({
  collapsed,
  onToggle,
  onCloseMobile,
}: {
  collapsed: boolean;
  onToggle: () => void;
  onCloseMobile: () => void;
}) {
  return (
    <div className="flex flex-col gap-m p-s">
      <div className={`flex items-center ${collapsed ? "justify-center" : "justify-between"}`}>
        <NavLink
          to="/app"
          onClick={onCloseMobile}
          className="rounded-m px-xxs py-xxs transition-colors duration-ui ease-ui hover:bg-neutral-8"
          aria-label="Atom 首页"
        >
          <Logo compact={collapsed} />
        </NavLink>
        {collapsed ? null : (
          <IconButton label="收起侧边栏" onClick={onToggle}>
            <Icon name="panel" size={15} />
          </IconButton>
        )}
      </div>

      {collapsed ? (
        <IconButton label="展开侧边栏" onClick={onToggle} className="self-center">
          <Icon name="panel" size={15} />
        </IconButton>
      ) : null}

      <NavLink
        to="/app"
        end
        onClick={onCloseMobile}
        className={({ isActive }) =>
          [
            "flex items-center gap-xs rounded-full text-sm font-medium transition-colors duration-ui ease-ui",
            collapsed ? "h-7 w-7 justify-center self-center" : "h-7 px-m",
            isActive
              ? "bg-brand text-white hover:bg-brand-secondary"
              : "hairline border-neutral-20 bg-base-tertiary text-neutral-95 hover:bg-base-secondary-alt",
          ].join(" ")
        }
        title="新建项目"
      >
        <Icon name="plus" size={14} />
        {collapsed ? null : <span>新建项目</span>}
      </NavLink>
    </div>
  );
}

function SidebarProjects({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate: () => void;
}) {
  const { projects, loading, error } = useProjects();

  return (
    <nav className="flex min-h-0 flex-1 flex-col gap-xxs overflow-y-auto px-s pb-s" aria-label="项目列表">
      {collapsed ? null : (
        <p className="px-xs pb-xxs pt-xs text-xs font-medium uppercase tracking-wide text-neutral-40">
          项目
        </p>
      )}

      {loading ? (
        <div className="flex flex-col gap-xxs px-xs">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-4/5" />
          <Skeleton className="h-6 w-3/5" />
        </div>
      ) : error ? (
        collapsed ? null : (
          <p className="px-xs text-sm text-danger-strong">{error}</p>
        )
      ) : projects.length === 0 ? (
        collapsed ? null : (
          <p className="px-xs text-sm leading-5 text-neutral-40">
            还没有项目。从上面开一个。
          </p>
        )
      ) : (
        projects.map((project) => (
          <NavLink
            key={project.id}
            to={`/app/p/${project.id}`}
            onClick={onNavigate}
            title={`${project.title} · ${STATUS_LABEL[project.status]}`}
            className={({ isActive }) =>
              [
                "flex items-center gap-xs rounded-m text-sm transition-colors duration-ui ease-ui",
                collapsed ? "h-7 justify-center" : "h-7 px-xs",
                isActive
                  ? "bg-neutral-16 text-neutral-95"
                  : "text-neutral-80 hover:bg-neutral-8 hover:text-neutral-95",
              ].join(" ")
            }
          >
            <span
              className={[
                "h-[6px] w-[6px] shrink-0 rounded-full",
                project.status === "error"
                  ? "bg-danger"
                  : project.status === "ready"
                    ? "bg-success"
                    : isRunningStatus(project.status)
                      ? "animate-pulse-soft bg-brand"
                      : "bg-neutral-20",
              ].join(" ")}
              aria-hidden="true"
            />
            {collapsed ? null : <span className="truncate">{project.title}</span>}
          </NavLink>
        ))
      )}
    </nav>
  );
}

const FOOTER_LINKS: { to: string; label: string; icon: IconName }[] = [
  { to: "/app/usage", label: "额度", icon: "gauge" },
  { to: "/app/settings", label: "设置", icon: "settings" },
];

function SidebarFooter({ collapsed }: { collapsed: boolean }) {
  const { user, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutFailed, setLogoutFailed] = useState(false);
  const logoutPending = useRef(false);

  async function logout() {
    if (logoutPending.current) return;
    logoutPending.current = true;
    setSigningOut(true);
    setLogoutFailed(false);
    try { await signOut(); }
    catch { setLogoutFailed(true); }
    finally { logoutPending.current = false; setSigningOut(false); }
  }

  return (
    <div className="flex flex-col gap-xxs border-t border-neutral-12 p-s">
      {FOOTER_LINKS.map((link) => (
        <NavLink
          key={link.to}
          to={link.to}
          title={link.label}
          className={({ isActive }) =>
            [
              "flex items-center gap-xs rounded-m text-sm transition-colors duration-ui ease-ui",
              collapsed ? "h-7 justify-center" : "h-7 px-xs",
              isActive
                ? "bg-neutral-16 text-neutral-95"
                : "text-neutral-80 hover:bg-neutral-8 hover:text-neutral-95",
            ].join(" ")
          }
        >
          <Icon name={link.icon} size={14} />
          {collapsed ? null : <span className="truncate">{link.label}</span>}
        </NavLink>
      ))}

      <div
        className={`mt-xxs flex items-center ${collapsed ? "flex-col gap-xxs" : "justify-between"}`}
      >
        <ThemeToggle />
        <IconButton
          label={signingOut ? "正在退出登录" : "退出登录"}
          disabled={signingOut}
          aria-busy={signingOut}
          onClick={() => void logout()}
        >
          <Icon name="logout" size={14} />
        </IconButton>
      </div>

      {logoutFailed ? <div role="alert" className="fixed bottom-16 left-m z-50 max-w-[calc(100vw-2rem)] w-80 rounded-m border border-neutral-12 bg-base-default p-l text-sm text-neutral-95 shadow-lg">
        <p>退出未能确认完成，会话可能仍然有效。请重试退出登录。</p>
        <button type="button" className="mt-s mr-l underline" disabled={signingOut} onClick={() => void logout()}>重试退出登录</button>
        <button type="button" className="mt-s underline" onClick={() => setLogoutFailed(false)}>关闭提示</button>
      </div> : null}

      {collapsed ? null : (
        <div className="mt-xxs rounded-m bg-neutral-8 px-xs py-xs">
          <p className="truncate text-xs text-neutral-60">{user?.email ?? "—"}</p>
          <p className="text-sm font-medium text-neutral-95">
            {typeof user?.credits === "number" ? `${user.credits} credits` : "—"}
          </p>
        </div>
      )}
    </div>
  );
}
