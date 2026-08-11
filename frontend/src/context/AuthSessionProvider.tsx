import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { loadAuthSession, logoutAllSessions, logoutSession } from "../services/auth";
import type { AuthSessionResponse, AuthViewState } from "../types/auth";

const CHANNEL_NAME = "ilt-auth-v1";
const REVALIDATE_INTERVAL_MS = 30_000;

export interface AuthSessionContextValue {
  state: AuthViewState;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;
  announceChange: () => void;
}

export const AuthSessionContext = createContext<AuthSessionContextValue | null>(null);

function toViewState(session: AuthSessionResponse): AuthViewState {
  if (!session.authenticationAvailable) return { status: "disabled", session };
  if (!session.authenticated) return { status: "anonymous", session };
  return { status: "authenticated", session };
}

export function AuthSessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthViewState>({ status: "loading" });
  const requestSequence = useRef(0);
  const lastRefreshAt = useRef(0);
  const channelRef = useRef<BroadcastChannel | null>(null);

  const refresh = useCallback(async () => {
    const sequence = ++requestSequence.current;
    try {
      const session = await loadAuthSession();
      if (sequence === requestSequence.current) {
        lastRefreshAt.current = Date.now();
        setState(toViewState(session));
      }
    } catch {
      if (sequence === requestSequence.current) {
        lastRefreshAt.current = Date.now();
        setState({ status: "unavailable" });
      }
    }
  }, []);

  const announceChange = useCallback(() => {
    channelRef.current?.postMessage({ type: "session-changed" });
  }, []);

  const logout = useCallback(async () => {
    if (state.status !== "authenticated") return;
    await logoutSession(state.session.csrfToken);
    announceChange();
    await refresh();
  }, [announceChange, refresh, state]);

  const logoutAll = useCallback(async () => {
    if (state.status !== "authenticated") return;
    await logoutAllSessions(state.session.csrfToken);
    announceChange();
    await refresh();
  }, [announceChange, refresh, state]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(CHANNEL_NAME);
    channelRef.current = channel;
    channel.addEventListener("message", (event: MessageEvent<unknown>) => {
      if (
        typeof event.data === "object" &&
        event.data !== null &&
        "type" in event.data &&
        event.data.type === "session-changed"
      ) {
        void refresh();
      }
    });
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, [refresh]);

  useEffect(() => {
    const maybeRefresh = () => {
      if (Date.now() - lastRefreshAt.current >= REVALIDATE_INTERVAL_MS) void refresh();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") maybeRefresh();
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) maybeRefresh();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [refresh]);

  const value = useMemo(
    () => ({ state, refresh, logout, logoutAll, announceChange }),
    [announceChange, logout, logoutAll, refresh, state],
  );
  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}
