import { useState } from "react";

import { useAuthSession } from "../hooks/useAuthSession";

export const TICKET_HINT_STORAGE_KEY = "scratchoffdata.ticketHistoryHint";
export const TICKET_HINT_VERSION = "2026-08-28-v1";

export function hasDismissedTicketHint(storage: Storage = window.localStorage): boolean {
  try {
    return storage.getItem(TICKET_HINT_STORAGE_KEY) === TICKET_HINT_VERSION;
  } catch {
    return true;
  }
}

export function persistTicketHintDismissal(storage: Storage = window.localStorage): void {
  try {
    storage.setItem(TICKET_HINT_STORAGE_KEY, TICKET_HINT_VERSION);
  } catch {
    // Dismissal simply will not persist; the hint returns on the next visit.
  }
}

/**
 * A one-time pointer under the header's Log in control for signed-out
 * visitors. Dismissing it is remembered per browser; it never returns after
 * sign-in because the anonymous state is the only one that renders it.
 */
export function TicketHistoryHint() {
  const { state } = useAuthSession();
  const [dismissed, setDismissed] = useState(() => hasDismissedTicketHint());

  if (dismissed || state.status !== "anonymous") return null;

  const dismiss = () => {
    persistTicketHintDismissal();
    setDismissed(true);
  };

  return (
    <div className="ticket-history-hint" role="note">
      <p>Track your plays. Log in to start.</p>
      <button aria-label="Dismiss this reminder" onClick={dismiss} type="button">
        ×
      </button>
    </div>
  );
}
