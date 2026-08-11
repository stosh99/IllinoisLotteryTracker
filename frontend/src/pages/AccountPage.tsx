import { Navigate } from "react-router-dom";

import { SessionList } from "../components/SessionList";
import { AccountSettings } from "../components/AccountSettings";
import { useAuthSession } from "../hooks/useAuthSession";

export function AccountPage() {
  const { state, logoutAll } = useAuthSession();
  if (state.status === "loading") {
    return <main className="account-page" id="main-content"><p role="status">Loading account…</p></main>;
  }
  if (state.status === "anonymous") return <Navigate replace to="/" />;
  if (state.status === "disabled") {
    return <main className="account-page" id="main-content"><h1>Accounts are not enabled.</h1></main>;
  }
  if (state.status === "unavailable") {
    return (
      <main className="account-page" id="main-content">
        <h1>Account information is temporarily unavailable.</h1>
        <p>Your ranking comparison remains available from the home page.</p>
      </main>
    );
  }
  return (
    <main className="account-page" id="main-content">
      <p className="eyebrow">YOUR ACCOUNT</p>
      <h1>Signed-in sessions</h1>
      <p className="account-page__lede">
        Signed in as <strong>{state.session.user.email}</strong>. For privacy, this site does not
        record device names, IP addresses, or locations for sessions.
      </p>
      <SessionList />
      <section className="account-action" aria-labelledby="all-session-title">
        <h2 id="all-session-title">Sign out everywhere</h2>
        <p>End every active session, including this one.</p>
        <button className="button button--outline" onClick={() => void logoutAll()} type="button">
          Sign out all sessions
        </button>
      </section>
      <AccountSettings />
    </main>
  );
}
