import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { gameDetailHref, parseViewState } from "../lib/urlState";
import type { RankingDataset } from "../types/rankings";

export interface TicketOption {
  gameId: number;
  gameNumber: string;
  gameName: string;
  ticketPrice: number;
}

export function TicketFinder({ dataset }: { dataset: RankingDataset | null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [ticketPrice, setTicketPrice] = useState<"all" | number>("all");
  const [query, setQuery] = useState("");
  const [selectedGameId, setSelectedGameId] = useState<number | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const games = useMemo(() => uniqueGames(dataset), [dataset]);
  const prices = useMemo(
    () => [...new Set(games.map((game) => game.ticketPrice))].sort((a, b) => a - b),
    [games],
  );
  const suggestions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return games
      .filter((game) => ticketPrice === "all" || game.ticketPrice === ticketPrice)
      .filter(
        (game) =>
          normalized === "" ||
          game.gameName.toLocaleLowerCase().includes(normalized) ||
          game.gameNumber.toLocaleLowerCase().includes(normalized),
      )
      .slice(0, 7);
  }, [games, query, ticketPrice]);

  const choose = (game: TicketOption) => {
    setQuery(formatTicketOption(game));
    setSelectedGameId(game.gameId);
    setOpen(false);
  };
  const submit = () => {
    const selected = games.find((game) => game.gameId === selectedGameId);
    const exact = selected ?? findExactGame(games, query, ticketPrice);
    if (!exact) {
      setOpen(true);
      return;
    }
    navigate(gameDetailHref(exact.gameId, parseViewState(location.search)));
    setOpen(false);
  };

  return (
    <form
      aria-label="Find a ticket"
      className="ticket-finder"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      role="search"
    >
      <label className="visually-hidden" htmlFor="header-ticket-price">Ticket denomination</label>
      <select
        aria-label="Ticket denomination"
        id="header-ticket-price"
        onChange={(event) => {
          setTicketPrice(event.target.value === "all" ? "all" : Number(event.target.value));
          setQuery("");
          setSelectedGameId(null);
          setOpen(false);
        }}
        value={ticketPrice}
      >
        <option value="all">All prices</option>
        {prices.map((price) => <option key={price} value={price}>${price}</option>)}
      </select>
      <div className="ticket-finder__combobox">
        <label className="visually-hidden" htmlFor="header-ticket-query">Game name or number</label>
        <input
          aria-activedescendant={open && suggestions[activeIndex] ? `ticket-option-${suggestions[activeIndex].gameId}` : undefined}
          aria-autocomplete="list"
          aria-controls="header-ticket-options"
          aria-expanded={open}
          autoComplete="off"
          id="header-ticket-query"
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onChange={(event) => {
            setQuery(event.target.value);
            setSelectedGameId(null);
            setActiveIndex(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
              setActiveIndex((value) => Math.min(value + 1, suggestions.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((value) => Math.max(value - 1, 0));
            } else if (event.key === "Enter" && open && suggestions[activeIndex]) {
              event.preventDefault();
              choose(suggestions[activeIndex]);
            } else if (event.key === "Escape") {
              setOpen(false);
            }
          }}
          placeholder="Game name or number"
          role="combobox"
          type="search"
          value={query}
        />
        {open && suggestions.length > 0 ? (
          <div className="ticket-finder__options" id="header-ticket-options" role="listbox">
            {suggestions.map((game, index) => (
              <button
                aria-selected={index === activeIndex}
                className="ticket-finder__option"
                id={`ticket-option-${game.gameId}`}
                key={game.gameId}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(game)}
                role="option"
                type="button"
              >
                {formatTicketOption(game)}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <button className="ticket-finder__go" disabled={!selectedGameId && !findExactGame(games, query, ticketPrice)} type="submit">
        Go
      </button>
    </form>
  );
}

export function uniqueGames(dataset: RankingDataset | null): TicketOption[] {
  if (!dataset) return [];
  const byId = new Map<number, TicketOption>();
  for (const row of dataset.rankings) {
    if (!byId.has(row.gameId)) {
      byId.set(row.gameId, {
        gameId: row.gameId,
        gameNumber: row.gameNumber,
        gameName: row.gameName,
        ticketPrice: row.ticketPrice,
      });
    }
  }
  return [...byId.values()].sort(
    (left, right) =>
      left.ticketPrice - right.ticketPrice || left.gameName.localeCompare(right.gameName),
  );
}

export function formatTicketOption(game: TicketOption): string {
  return `$${game.ticketPrice} · ${game.gameNumber} — ${game.gameName}`;
}

function findExactGame(
  games: TicketOption[],
  query: string,
  ticketPrice: "all" | number,
): TicketOption | null {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return null;
  const matches = games.filter(
    (game) =>
      (ticketPrice === "all" || game.ticketPrice === ticketPrice) &&
      [game.gameNumber, game.gameName, formatTicketOption(game)].some(
        (value) => value.toLocaleLowerCase() === normalized,
      ),
  );
  return matches.length === 1 ? (matches[0] ?? null) : null;
}
