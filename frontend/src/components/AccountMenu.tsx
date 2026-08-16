import { useState } from "react";
import { Link } from "react-router-dom";

import { useAuthSession } from "../hooks/useAuthSession";

export function AccountMenu() {
  const { state, logout } = useAuthSession();
  const [error, setError] = useState(false);
  if (state.status !== "authenticated") return null;

  const signOut = async () => {
    setError(false);
    try {
      await logout();
    } catch {
      setError(true);
    }
  };

  return (
    <div className="account-control">
      <details className="account-menu">
        <summary>Account</summary>
        <div className="account-menu__panel">
          <span className="account-menu__email">{state.session.user.email}</span>
          <Link to="/account#ticket-history">My ticket history</Link>
          <Link to="/account#account-security">Account settings</Link>
          <button onClick={() => void signOut()} type="button">
            Sign out
          </button>
        </div>
      </details>
      {error ? <span className="visually-hidden" role="alert">Sign out failed.</span> : null}
    </div>
  );
}
