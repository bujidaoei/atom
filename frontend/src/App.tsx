import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useSession } from "./session";
import { AuthPage } from "./pages/Auth";
import { DashboardPage } from "./pages/Dashboard";
import { LandingPage } from "./pages/Landing";
import { SettingsPage } from "./pages/Settings";
import { WorkspacePage } from "./pages/Workspace";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useSession();
  if (!ready) {
    return <p className="px-6 py-8 text-sm text-muted">正在确认登录状态</p>;
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route
        path="/app"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      <Route
        path="/app/settings"
        element={
          <RequireAuth>
            <SettingsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/app/p/:id"
        element={
          <RequireAuth>
            <WorkspacePage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
