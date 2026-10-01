import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api, setUnauthorizedHandler } from "./api";
import type { User } from "./types";
import { ErrorState } from "../components/ui/States";
import { FullPageSpinner } from "../components/ui/Spinner";

type AuthContextValue = {
  user: User | null;
  ready: boolean;
  sessionError: boolean;
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
  const [sessionError, setSessionError] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const navigate = useNavigate();
  const location = useLocation();

  const invalidateCheck = useCallback(() => {
    generation.current += 1;
    pending.current?.abort();
    pending.current = null;
  }, []);

  const refresh = useCallback(async () => {
    invalidateCheck();
    const current = generation.current;
    const controller = new AbortController();
    pending.current = controller;
    setSessionError(false);
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const me = await api.me(true, controller.signal);
      if (current === generation.current) { setUser(me); setReady(true); }
    } catch (error) {
      if (current !== generation.current) return;
      if (error instanceof ApiError && error.status === 401) {
        setUser(null); setReady(true);
      } else {
        // Retain prior identity; unavailable verification is not evidence of logout.
        setSessionError(true);
      }
    } finally {
      window.clearTimeout(timeout);
      if (current === generation.current) pending.current = null;
    }
  }, [invalidateCheck]);

  useEffect(() => {
    void refresh();
    return invalidateCheck;
  }, [refresh, invalidateCheck]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      invalidateCheck(); setSessionError(false); setReady(true);
      setUser(null);
      const here = `${location.pathname}${location.search}`;
      if (!here.startsWith("/login") && !here.startsWith("/register")) {
        navigate("/login", { replace: true, state: { from: here } });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate, location.pathname, location.search, invalidateCheck]);

  const signIn = useCallback((next: User) => {
    invalidateCheck(); setSessionError(false); setReady(true); setUser(next);
  }, [invalidateCheck]);

  const signOut = useCallback(async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const result = await api.logout(controller.signal);
      if (result?.ok !== true) throw new Error("退出结果无法确认。");
      invalidateCheck(); setSessionError(false); setReady(true);
      setUser(null);
      navigate("/", { replace: true });
    } finally { window.clearTimeout(timeout); }
  }, [navigate, invalidateCheck]);

  const setCredits = useCallback((credits: number) => {
    setUser((current) => (current ? { ...current, credits } : current));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, ready, sessionError, signIn, signOut, refresh, setCredits }),
    [user, ready, sessionError, signIn, signOut, refresh, setCredits],
  );

  return <AuthContext.Provider value={value}>
    {ready && sessionError ? <div className="fixed top-m left-1/2 -translate-x-1/2 z-50 w-96 max-w-[calc(100vw-2rem)]">
      <ErrorState title="暂时无法核对会话" message="当前会话状态无法确认，请重试。" onRetry={() => void refresh()} />
    </div> : null}
    {children}
  </AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth 必须在 AuthProvider 内使用。");
  return context;
}

export function SessionGate({ children }: { children: ReactNode }) {
  const { ready, sessionError, refresh } = useAuth();
  if (!ready && sessionError) return <main className="mx-auto max-w-xl p-xl">
    <ErrorState title="暂时无法核对会话" message="尚未确认登录状态，请重试。" onRetry={() => void refresh()} />
  </main>;
  if (!ready) return <FullPageSpinner label="正在检查登录态" />;
  return <>{children}</>;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();

  if (!ready) return <SessionGate>{children}</SessionGate>;
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
