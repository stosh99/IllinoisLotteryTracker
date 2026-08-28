import { Link } from "react-router-dom";

import { useAuthSession } from "../hooks/useAuthSession";

/**
 * The hero panel's ticket-history row. Signed out it introduces the feature
 * and starts the Google flow with `/account` as the return path; signed in it
 * becomes a shortcut to the user's own history. Hidden while authentication
 * is disabled or unknown, because the pitch would dead-end.
 */
export function TicketHistoryPromo() {
  const { state } = useAuthSession();

  if (state.status === "authenticated") {
    return (
      <Link className="hero-all-tickets hero-track-plays" to="/account#ticket-history">
        <span>My tickets</span>
        <strong>My ticket history</strong>
        <small>Your spend, winnings, and net over time.</small>
      </Link>
    );
  }

  if (state.status !== "anonymous") return null;

  return (
    <a
      className="hero-all-tickets hero-track-plays"
      href="/api/v1/auth/google/start?returnTo=%2Faccount"
    >
      <span>Tracking your play?</span>
      <strong>Record what you spend and win.</strong>
      <small>Private ticket history — sign in with Google to start.</small>
    </a>
  );
}
