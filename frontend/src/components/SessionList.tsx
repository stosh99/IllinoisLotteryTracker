import { useEffect, useState } from "react";

import { useAuthSession } from "../hooks/useAuthSession";
import { listSessions, revokeSession } from "../services/auth";
import type { ManagedSession } from "../types/auth";

function localTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

export function SessionList() {
  const { state, refresh } = useAuthSession();
  const [sessions, setSessions] = useState<ManagedSession[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (state.status !== "authenticated") return;
    const controller = new AbortController();
    setError(false);
    listSessions(controller.signal)
      .then(setSessions)
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, [state.status]);

  if (state.status !== "authenticated") return null;
  if (error) return <p role="alert">Sessions could not be loaded. Please try again.</p>;
  if (sessions === null) return <p role="status">Loading sessions…</p>;

  const revoke = async (session: ManagedSession) => {
    setError(false);
    try {
      await revokeSession(session.id, state.session.csrfToken);
      if (session.current) {
        await refresh();
      } else {
        setSessions((current) => current?.filter((item) => item.id !== session.id) ?? []);
      }
    } catch {
      setError(true);
    }
  };

  return (
    <ul className="session-list">
      {sessions.map((session) => (
        <li key={session.id}>
          <div>
            <strong>{session.current ? "Current session" : "Signed-in session"}</strong>
            <dl>
              <div>
                <dt>Created</dt>
                <dd><time dateTime={session.createdAt}>{localTime(session.createdAt)}</time></dd>
              </div>
              <div>
                <dt>Last active</dt>
                <dd><time dateTime={session.lastSeenAt}>{localTime(session.lastSeenAt)}</time></dd>
              </div>
              <div>
                <dt>Ends by</dt>
                <dd><time dateTime={session.absoluteExpiresAt}>{localTime(session.absoluteExpiresAt)}</time></dd>
              </div>
            </dl>
          </div>
          <button className="button button--outline" onClick={() => void revoke(session)} type="button">
            {session.current ? "Sign out this session" : "Revoke session"}
          </button>
        </li>
      ))}
    </ul>
  );
}
