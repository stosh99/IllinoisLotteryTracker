import { AccountMenu } from "./AccountMenu";
import { useAuthSession } from "../hooks/useAuthSession";

export function SignInControl() {
  const { state } = useAuthSession();
  if (state.status === "disabled") {
    return <UnavailableSignIn message="Account sign-in is not enabled yet." />;
  }
  if (state.status === "loading") {
    return <span className="auth-control auth-control--status">Checking account…</span>;
  }
  if (state.status === "unavailable") {
    return <UnavailableSignIn message="Account sign-in is temporarily unavailable." />;
  }
  if (state.status === "anonymous") {
    return (
      <a className="header-link" href="/api/v1/auth/google/start?returnTo=%2F" title="Continue with Google">
        Log in
      </a>
    );
  }
  return <AccountMenu />;
}

function UnavailableSignIn({ message }: { message: string }) {
  return (
    <details className="login-unavailable">
      <summary className="header-link" role="button">Log in</summary>
      <p role="status">{message}</p>
    </details>
  );
}
