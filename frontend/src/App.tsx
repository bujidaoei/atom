import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AuthProvider, RequireAuth, SessionGate } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import { ContentAccessPage } from "./pages/ContentAccess";
import { AuthPage } from "./pages/Auth";
import { DashboardPage } from "./pages/Dashboard";
import { LandingPage } from "./pages/Landing";
import { NotFoundPage } from "./pages/NotFound";
import { SettingsPage } from "./pages/Settings";
import { UsagePage } from "./pages/Usage";
import { WorkspacePage } from "./pages/Workspace";

const basename = import.meta.env.BASE_URL.replace(/\/$/, "");

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter basename={basename || undefined}>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/content-access" element={<RequireAuth><ContentAccessPage /></RequireAuth>} />
            <Route path="/login" element={<SessionGate><AuthPage mode="login" /></SessionGate>} />
            <Route path="/register" element={<SessionGate><AuthPage mode="register" /></SessionGate>} />
            <Route
              path="/app"
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="p/:id" element={<WorkspacePage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="usage" element={<UsagePage />} />
            </Route>
            <Route path="/app/*" element={<Navigate to="/app" replace />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
