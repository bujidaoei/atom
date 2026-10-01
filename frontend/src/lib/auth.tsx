import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api, setUnauthorizedHandler } from "./api";
import type { User } from "./types";
import { FullPageSpinner } from "../components/ui/Spinner";

type AuthContextValue = {
  user: User | null;
  ready: boolean;
  signIn: (user: User) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Locally adjust the credit counter after a run consumes one. */
  setCredits: (credits: number) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    let cancelled = false;
    api
      .me(true)
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch((err: unknown) => {
        if (!cancelled && !(err instanceof ApiError && err.status === 401)) {
          // A non-401 boot failure still leaves the app usable while signed out.
          console.warn("会话检查失败", err);
        }
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      const here = `${location.pathname}${location.search}`;
      if (!here.startsWith("/login") && !here.startsWith("/register")) {
        navigate("/login", { replace: true, state: { from: here } });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate, location.pathname, location.search]);

  const signIn = useCallback((next: User) => setUser(next), []);

  const signOut = useCallback(async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const result = await api.logout(controller.signal);
      if (result?.ok !== true) throw new Error("退出结果无法确认。");
      setUser(null);
      navigate("/", { replace: true });
    } finally { window.clearTimeout(timeout); }
  }, [navigate]);

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me(true));
    } catch {
      setUser(null);
    }
  }, []);

  const setCredits = useCallback((credits: number) => {
    setUser((current) => (current ? { ...current, credits } : current));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, ready, signIn, signOut, refresh, setCredits }),
    [user, ready, signIn, signOut, refresh, setCredits],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth 必须在 AuthProvider 内使用。");
  return context;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();

  if (!ready) return <FullPageSpinner label="正在检查登录态" />;
  if (!user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }
  return <>{children}</>;
}

/** Prompts typed while signed out survive the login round-trip. */
const PENDING_PROMPT_KEY = "atom-pending-prompt";

export function stashPendingPrompt(prompt: string): void {
  try {
    sessionStorage.setItem(PENDING_PROMPT_KEY, prompt);
  } catch {
    /* ignore */
  }
}

export function takePendingPrompt(): string | null {
  try {
    const value = sessionStorage.getItem(PENDING_PROMPT_KEY);
    if (value) sessionStorage.removeItem(PENDING_PROMPT_KEY);
    return value;
  } catch {
    return null;
  }
}
