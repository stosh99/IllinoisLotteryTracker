import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

const RESULT_MESSAGES: Record<string, string> = {
  cancelled: "Sign-in was cancelled.",
  expired: "That sign-in attempt expired. Please try again.",
  failed: "We could not complete sign-in. Please try again.",
  account_unavailable: "This account cannot sign in.",
  in_progress: "Sign-in is already finishing in another tab.",
};

export function AuthResultNotice() {
  const location = useLocation();
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const url = new URL(window.location.href);
    const result = url.searchParams.get("authResult");
    setMessage(result ? (RESULT_MESSAGES[result] ?? null) : null);
    if (result !== null) {
      url.searchParams.delete("authResult");
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    }
  }, [location.key]);

  return message ? (
    <div className="auth-result" role="status">
      {message}
    </div>
  ) : null;
}
