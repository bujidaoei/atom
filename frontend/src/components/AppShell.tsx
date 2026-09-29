import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { ProjectsProvider } from "../lib/projects";
import { Logo } from "./Logo";
import { Sidebar } from "./Sidebar";
import { IconButton } from "./ui/Button";
import { Icon } from "./ui/Icon";

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  // The workspace manages its own internal scrolling; other pages scroll normally.
  const isWorkspace = location.pathname.startsWith("/app/p/");

  return (
    <ProjectsProvider>
      <div className="flex h-screen overflow-hidden bg-base-default">
        <Sidebar mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex h-11 items-center gap-s border-b border-neutral-12 bg-utilities-header px-m backdrop-blur-md lg:hidden">
            <IconButton label="打开侧边栏" onClick={() => setMobileOpen(true)}>
              <Icon name="panel" size={16} />
            </IconButton>
            <Logo />
          </header>

          <main className={`min-w-0 flex-1 ${isWorkspace ? "overflow-hidden" : "overflow-y-auto"}`}>
            <Outlet />
          </main>
        </div>
      </div>
    </ProjectsProvider>
  );
}
