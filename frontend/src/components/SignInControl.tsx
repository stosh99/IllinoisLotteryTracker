import { AccountMenu } from "./AccountMenu";
import { useAuthSession } from "../hooks/useAuthSession";

export function SignInControl() {
  const { state } = useAuthSession();
  if (state.status === "disabled") return null;
  if (state.status === "loading") {
    return <span className="auth-control auth-control--status">Checking account…</span>;
  }
  if (state.status === "unavailable") {
    return (
      <span className="auth-control auth-control--status" role="status">
        Account unavailable
      </span>
    );
  }
  if (state.status === "anonymous") {
    return (
      <a className="header-link" href="/api/v1/auth/google/start?returnTo=%2F">
        Sign in with Google
      </a>
    );
  }
  return <AccountMenu />;
}
