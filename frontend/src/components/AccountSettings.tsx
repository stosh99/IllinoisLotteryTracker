import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuthSession } from "../hooks/useAuthSession";
import {
  AuthRequestError,
  deleteAccount,
  startDeleteReauthentication,
} from "../services/auth";

const CONFIRMATION = "DELETE MY ACCOUNT";

interface AccountSettingsProps {
  navigateToProvider?: (url: string) => void;
}

export function AccountSettings({
  navigateToProvider = (url) => window.location.assign(url),
}: AccountSettingsProps) {
  const { state, announceChange, refresh } = useAuthSession();
  const navigate = useNavigate();
  const [confirmation, setConfirmation] = useState("");
  const [needsReauthentication, setNeedsReauthentication] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (state.status !== "authenticated") return null;

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(confirmation, state.session.csrfToken);
      announceChange();
      await refresh();
      navigate("/", { replace: true });
    } catch (reason) {
      setConfirmation("");
      if (reason instanceof AuthRequestError && reason.code === "RECENT_AUTH_REQUIRED") {
        setNeedsReauthentication(true);
      } else {
        setError("The account could not be deleted. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  const reauthenticate = async () => {
    setBusy(true);
    setError(null);
    try {
      const url = await startDeleteReauthentication(state.session.csrfToken);
      navigateToProvider(url);
    } catch {
      setError("Google identity confirmation could not be started. Please try again.");
      setBusy(false);
    }
  };

  return (
    <section className="account-danger" aria-labelledby="delete-account-title">
      <p className="eyebrow">DELETE ACCOUNT</p>
      <h2 id="delete-account-title">Permanently remove this account</h2>
      <p>
        This removes your local account and active sessions. Type <strong>{CONFIRMATION}</strong>{" "}
        to continue.
      </p>
      {needsReauthentication ? (
        <div className="reauth-prompt">
          <p>
            Confirm recent control of the same Google identity before deleting. Google may let
            you select an account; this is not a password or multi-factor challenge.
          </p>
          <button className="button" disabled={busy} onClick={() => void reauthenticate()} type="button">
            Continue with Google
          </button>
        </div>
      ) : (
        <div className="delete-confirmation">
          <label htmlFor="delete-confirmation">Confirmation phrase</label>
          <input
            autoComplete="off"
            id="delete-confirmation"
            onChange={(event) => setConfirmation(event.currentTarget.value)}
            spellCheck={false}
            value={confirmation}
          />
          <button
            className="button button--danger"
            disabled={busy || confirmation !== CONFIRMATION}
            onClick={() => void remove()}
            type="button"
          >
            Delete my account
          </button>
        </div>
      )}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
