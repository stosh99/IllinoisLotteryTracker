import { useMemo, useState } from "react";

import { RankingFilters } from "../components/RankingFilters";
import { UnavailableState } from "../components/UnavailableState";
import { useSiteData } from "../context/SiteDataProvider";
import { formatMoney, formatOneIn } from "../lib/strategies";
import type { RankingDataset, RankingRecord, TicketPriceFilter } from "../types/rankings";

export interface DirectoryGame {
  gameId: number;
  gameNumber: string;
  gameName: string;
  ticketPrice: number;
  anyPrizeOneIn: number | null;
  profitOneIn: number | null;
  estimatedReturn: number | null;
  topPrizeAmount: number | null;
  topPrizesOriginal: number | null;
  topPrizesRemaining: number | null;
  topPrizeOneIn: number | null;
}

export function AllTicketsPage() {
  const { dataset, error, retry } = useSiteData();
  const [ticketPrice, setTicketPrice] = useState<TicketPriceFilter>("all");
  const games = useMemo(() => directoryGames(dataset), [dataset]);
  const prices = useMemo(
    () => [...new Set(games.map((game) => game.ticketPrice))].sort((left, right) => left - right),
    [games],
  );
  const filtered = useMemo(
    () =>
      games.filter(
        (game) => ticketPrice === "all" || game.ticketPrice === ticketPrice,
      ),
    [games, ticketPrice],
  );

  return (
    <main className="ticket-directory" id="main-content">
      <header className="ticket-directory__hero">
        <p className="eyebrow">ALL CURRENT TICKETS</p>
        <h1>See every game—without choosing a player type.</h1>
        <p>
          This directory is alphabetical, not ranked. Use it to browse or compare the
          same basic facts across every current ticket.
        </p>
      </header>

      {error ? (
        <section className="load-state" aria-live="polite">
          <h2>We could not load the ticket directory.</h2>
          <p>{error}</p>
          <button className="button" onClick={retry} type="button">Try again</button>
        </section>
      ) : !dataset ? (
        <section className="load-state" aria-live="polite">
          <span className="loading-line" />
          <p>Loading every ticket…</p>
        </section>
      ) : !dataset.status.available ? (
        <UnavailableState reasonCode={dataset.status.reasonCode} />
      ) : (
        <section className="ticket-directory__body" aria-labelledby="ticket-directory-title">
          <div className="ticket-directory__heading">
            <div>
              <p className="eyebrow">TICKET DIRECTORY</p>
              <h2 id="ticket-directory-title">{filtered.length} of {games.length} current games</h2>
            </div>
            <a className="text-link" href="/#player-types">Choose a player type instead →</a>
          </div>
          <RankingFilters
            ariaLabel="Ticket directory filters"
            prices={prices}
            ticketPrice={ticketPrice}
            onTicketPriceChange={setTicketPrice}
          />
          {filtered.length === 0 ? (
            <div className="ticket-directory__empty">
              <h3>No tickets match those filters.</h3>
              <button
                className="button button--outline"
                onClick={() => setTicketPrice("all")}
                type="button"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <div className="ticket-directory-table-wrap">
              <table className="ticket-directory-table">
                <caption className="visually-hidden">
                  Every current Illinois instant ticket in alphabetical order
                </caption>
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Price</th>
                    <th>Estimated chances</th>
                    <th>All-prize return</th>
                    <th>Top prize</th>
                    <th><span className="visually-hidden">Details</span></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((game) => (
                    <tr key={game.gameId}>
                      <th scope="row">
                        <span>{game.gameNumber}</span>
                        <strong>{game.gameName}</strong>
                      </th>
                      <td>{formatMoney(game.ticketPrice)}</td>
                      <td>
                        <span>Any prize <strong>{formatOneIn(game.anyPrizeOneIn)}</strong></span>
                        <span>Profit <strong>{formatOneIn(game.profitOneIn)}</strong></span>
                      </td>
                      <td>
                        <strong>{formatPercent(game.estimatedReturn)}</strong>
                        <small>estimated per $1</small>
                      </td>
                      <td>
                        <strong>{formatMoney(game.topPrizeAmount, true)}</strong>
                        <small>{inventory(game)}</small>
                        <small>{formatOneIn(game.topPrizeOneIn)} estimated chance</small>
                      </td>
                      <td><a href={`/games/${game.gameId}`}>View game →</a></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

export function directoryGames(dataset: RankingDataset | null): DirectoryGame[] {
  if (!dataset) return [];
  const rowsByGame = new Map<number, RankingRecord[]>();
  for (const row of dataset.rankings) {
    const rows = rowsByGame.get(row.gameId) ?? [];
    rows.push(row);
    rowsByGame.set(row.gameId, rows);
  }
  return [...rowsByGame.values()]
    .map((rows) => {
      const first = rows[0]!;
      const byStrategy = new Map(rows.map((row) => [row.strategyKey, row]));
      const anyPrize = byStrategy.get("any_win");
      const profit = byStrategy.get("profit_full");
      const value = byStrategy.get("value_full");
      const jackpot = byStrategy.get("jackpot_top_odds");
      return {
        gameId: first.gameId,
        gameNumber: first.gameNumber,
        gameName: first.gameName,
        ticketPrice: first.ticketPrice,
        anyPrizeOneIn: anyPrize?.oneInValue ?? null,
        profitOneIn: profit?.oneInValue ?? null,
        estimatedReturn: value?.metricValue ?? first.estimatedEvFull,
        topPrizeAmount: first.topPrizeAmount,
        topPrizesOriginal: first.topPrizesOriginal,
        topPrizesRemaining: first.topPrizesRemaining,
        topPrizeOneIn: jackpot?.oneInValue ?? null,
      };
    })
    .sort((left, right) => left.gameName.localeCompare(right.gameName));
}

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}

function inventory(game: DirectoryGame): string {
  if (game.topPrizesRemaining === null || game.topPrizesOriginal === null) {
    return "Inventory unavailable";
  }
  return `${game.topPrizesRemaining} out of ${game.topPrizesOriginal} left`;
}
