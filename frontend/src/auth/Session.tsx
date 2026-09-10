import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { toast, Toaster } from "sonner";
import { get, onAuthenticationRequired, post } from "@/api/client";
import type { Me } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { applyTheme, usePrefs } from "@/store/prefs";

interface Session {
  user: Me | null;
  expired: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}
const SessionContext = createContext<Session | null>(null);

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("SessionProvider is required");
  return session;
}

export function SessionProvider() {
  const qc = useQueryClient();
  const theme = usePrefs((s) => s.theme);
  useEffect(() => applyTheme(theme), [theme]);
  const [user, setUser] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [expired, setExpired] = useState(false);
  const generation = useRef(0);
  const invalidatePendingCheck = useCallback(() => { ++generation.current; }, []);

  const clearPrivateData = useCallback(() => {
    void qc.cancelQueries();
    qc.clear();
    usePrefs.getState().setContext(null, null);
    toast.dismiss();
  }, [qc]);

  const checkSession = useCallback(async () => {
    const current = ++generation.current;
    setChecking(true);
    setError(null);
    try {
      const data = await get<{ user: Me | null }>("/auth/session/");
      if (current === generation.current) setUser(data.user);
    } catch (failure) {
      if (current === generation.current) setError(failure as Error);
    } finally {
      if (current === generation.current) setChecking(false);
    }
  }, []);

  useEffect(() => {
    const unsubscribe = onAuthenticationRequired(() => {
      ++generation.current;
      setUser(null);
      setExpired(true);
      setChecking(false);
      clearPrivateData();
    });
    void checkSession();
    return () => { unsubscribe(); invalidatePendingCheck(); };
  }, [checkSession, clearPrivateData, invalidatePendingCheck]);

  async function signIn(username: string, password: string) {
    // Refresh CSRF after another tab logs in/out or this form has been left open.
    await get("/auth/session/");
    const data = await post<{ user: Me }>("/auth/login/", { username, password });
    ++generation.current;
    clearPrivateData();
    setUser(data.user);
    setExpired(false);
  }

  async function signOut() {
    await post("/auth/logout/");
    ++generation.current;
    setUser(null);
    setExpired(false);
    clearPrivateData();
  }

  if (checking || error) return (
    <main className="grid min-h-screen place-items-center bg-base-200 p-6">
      <section className="w-full max-w-md space-y-4" aria-label="Account connection">
        <h1>DocAI</h1>
        {error ? <ErrorNotice message="We couldn’t connect to DocAI. Check your connection and try again." onRetry={() => void checkSession()} />
          : <output>Checking your session…</output>}
      </section>
    </main>
  );
  return <SessionContext.Provider value={{ user, expired, signIn, signOut }}><Outlet /></SessionContext.Provider>;
}

export function RequireSession() {
  const { user } = useSession();
  const theme = usePrefs((s) => s.theme);
  const location = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`} replace />;
  return <><Outlet /><Toaster theme={theme} position="bottom-right" duration={6000} closeButton toastOptions={{ style: { background: "var(--color-base-100)", color: "var(--color-base-content)", borderColor: "var(--color-base-300)" } }} /></>;
}
