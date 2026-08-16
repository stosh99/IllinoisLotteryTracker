import { useEffect, useMemo, useState, type FormEvent } from "react";

import { useAuthSession } from "../hooks/useAuthSession";
import {
  createTicketEntry,
  deleteTicketEntry,
  loadTicketHistory,
} from "../services/ticketEntries";
import type { TicketHistory } from "../types/ticketEntries";
import { formatTicketOption, type TicketOption } from "./TicketFinder";

const EMPTY_HISTORY: TicketHistory = {
  summary: {
    entryCount: 0,
    ticketCount: 0,
    amountSpent: 0,
    amountWon: 0,
    netResult: 0,
    returnPercentage: null,
  },
  entries: [],
};

export function TicketTracker({ games }: { games: TicketOption[] }) {
  const { state } = useAuthSession();
  const [history, setHistory] = useState<TicketHistory>(EMPTY_HISTORY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [gameId, setGameId] = useState(games[0]?.gameId ?? 0);
  const [playedOn, setPlayedOn] = useState(todayLocal());
  const [ticketCount, setTicketCount] = useState(1);
  const [amountWon, setAmountWon] = useState(0);

  useEffect(() => {
    if (gameId === 0 && games[0]) setGameId(games[0].gameId);
  }, [gameId, games]);

  useEffect(() => {
    if (state.status !== "authenticated") return;
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    loadTicketHistory(controller.signal)
      .then(setHistory)
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [requestVersion, state.status]);

  const selectedGame = useMemo(
    () => games.find((game) => game.gameId === gameId) ?? null,
    [gameId, games],
  );
  const expectedSpent = (selectedGame?.ticketPrice ?? 0) * ticketCount;

  if (state.status !== "authenticated") return null;
  const csrfToken = state.session.csrfToken;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedGame || saving) return;
    setSaving(true);
    setError(false);
    try {
      await createTicketEntry({ gameId, playedOn, ticketCount, amountWon }, csrfToken);
      setTicketCount(1);
      setAmountWon(0);
      setRequestVersion((value) => value + 1);
    } catch {
      setError(true);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    setError(false);
    try {
      await deleteTicketEntry(id, csrfToken);
      setPendingDelete(null);
      setRequestVersion((value) => value + 1);
    } catch {
      setError(true);
    }
  };

  return (
    <section className="ticket-tracker" id="ticket-history" aria-labelledby="ticket-history-title">
      <div className="ticket-tracker__heading">
        <div>
          <p className="eyebrow">MY TICKETS</p>
          <h1 id="ticket-history-title">Track what you spent and won.</h1>
          <p>Private records tied to your account. Totals describe past results only.</p>
        </div>
      </div>

      <dl className="ticket-summary" aria-label="Ticket history totals">
        <Summary label="Spent" value={money(history.summary.amountSpent)} />
        <Summary label="Won" value={money(history.summary.amountWon)} />
        <Summary label="Net result" value={signedMoney(history.summary.netResult)} tone={history.summary.netResult} />
        <Summary
          label="Prize return"
          value={history.summary.returnPercentage === null ? "—" : `${formatNumber(history.summary.returnPercentage)}%`}
        />
      </dl>

      <form className="ticket-entry-form" id="ticket-entry" onSubmit={(event) => void submit(event)}>
        <div className="ticket-entry-form__heading">
          <h2>Add a ticket result</h2>
          <p>Enter several tickets together when they were the same game and purchase.</p>
        </div>
        <label>
          Game
          <select required value={gameId} onChange={(event) => setGameId(Number(event.target.value))}>
            {games.map((game) => <option key={game.gameId} value={game.gameId}>{formatTicketOption(game)}</option>)}
          </select>
        </label>
        <label>
          Date played
          <input max={todayLocal()} onChange={(event) => setPlayedOn(event.target.value)} required type="date" value={playedOn} />
        </label>
        <label>
          Number of tickets
          <input max="1000" min="1" onChange={(event) => setTicketCount(Number(event.target.value))} required type="number" value={ticketCount} />
        </label>
        <label htmlFor="ticket-amount-won">
          Total amount won
          <span className="money-input"><span>$</span><input aria-label="Total amount won" id="ticket-amount-won" min="0" onChange={(event) => setAmountWon(Number(event.target.value))} required step="0.01" type="number" value={amountWon} /></span>
        </label>
        <div className="ticket-entry-form__total">
          <span>Calculated amount spent</span>
          <strong>{money(expectedSpent)}</strong>
        </div>
        <button className="button" disabled={saving || games.length === 0} type="submit">
          {saving ? "Saving…" : "Save ticket result"}
        </button>
      </form>

      {error ? <p className="ticket-tracker__error" role="alert">Ticket history is temporarily unavailable. Please try again.</p> : null}
      {loading ? <p role="status">Loading ticket history…</p> : history.entries.length === 0 ? (
        <div className="ticket-history-empty">
          <h2>No ticket results yet.</h2>
          <p>Your totals will appear here after you save the first entry.</p>
        </div>
      ) : (
        <div className="ticket-history-table-wrap">
          <table className="ticket-history-table">
            <caption className="visually-hidden">Saved ticket results</caption>
            <thead><tr><th>Date</th><th>Game</th><th>Tickets</th><th>Spent</th><th>Won</th><th>Net</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {history.entries.map((entry) => (
                <tr key={entry.id}>
                  <td>{formatDate(entry.playedOn)}</td>
                  <th scope="row"><span>{entry.gameNumber}</span>{entry.gameName}</th>
                  <td>{entry.ticketCount}</td>
                  <td>{money(entry.amountSpent)}</td>
                  <td>{money(entry.amountWon)}</td>
                  <td data-tone={entry.netResult < 0 ? "negative" : entry.netResult > 0 ? "positive" : "neutral"}>{signedMoney(entry.netResult)}</td>
                  <td>
                    {pendingDelete === entry.id ? (
                      <span className="ticket-history-table__confirm">
                        <button onClick={() => void remove(entry.id)} type="button">Confirm</button>
                        <button onClick={() => setPendingDelete(null)} type="button">Cancel</button>
                      </span>
                    ) : (
                      <button aria-label={`Remove ${entry.gameName} result from ${formatDate(entry.playedOn)}`} onClick={() => setPendingDelete(entry.id)} type="button">Remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Summary({ label, value, tone }: { label: string; value: string; tone?: number }) {
  return <div data-tone={tone === undefined ? undefined : tone < 0 ? "negative" : tone > 0 ? "positive" : "neutral"}><dt>{label}</dt><dd>{value}</dd></div>;
}

function todayLocal(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function money(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function signedMoney(value: number): string {
  if (value === 0) return money(0);
  return `${value > 0 ? "+" : "−"}${money(Math.abs(value))}`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
}
