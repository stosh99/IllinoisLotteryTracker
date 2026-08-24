import { useMemo, useState } from "react";

import type { TicketEntry } from "../types/ticketEntries";
import { formatTicketOption, type TicketOption } from "./TicketFinder";

export interface DailyPoint {
  date: string;
  cumulative: number;
  dayNet: number;
  hasEntry: boolean;
}

const WIDTH = 720;
const HEIGHT = 260;
const MARGIN = { top: 14, right: 14, bottom: 30, left: 58 };
const PLOT_W = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom;

type ChartFilter =
  | { kind: "all" }
  | { kind: "price"; price: number }
  | { kind: "game"; gameId: number };

export function WinningsChart({ entries }: { entries: TicketEntry[] }) {
  const [filter, setFilter] = useState<ChartFilter>({ kind: "all" });
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  // Pills and the game list both come from the user's own history.
  const prices = useMemo(
    () => [...new Set(entries.map((entry) => entry.ticketPrice))].sort((a, b) => a - b),
    [entries],
  );
  const historyGames = useMemo(() => {
    const byId = new Map<number, TicketOption>();
    for (const entry of entries) {
      if (!byId.has(entry.gameId)) {
        byId.set(entry.gameId, {
          gameId: entry.gameId,
          gameNumber: entry.gameNumber,
          gameName: entry.gameName,
          ticketPrice: entry.ticketPrice,
        });
      }
    }
    return [...byId.values()].sort(
      (left, right) =>
        left.ticketPrice - right.ticketPrice || left.gameName.localeCompare(right.gameName),
    );
  }, [entries]);

  const effectiveFilter: ChartFilter =
    (filter.kind === "game" && !historyGames.some((game) => game.gameId === filter.gameId)) ||
    (filter.kind === "price" && !prices.includes(filter.price))
      ? { kind: "all" }
      : filter;
  const gameOptions =
    effectiveFilter.kind === "price"
      ? historyGames.filter((game) => game.ticketPrice === effectiveFilter.price)
      : historyGames;

  const filterKey =
    effectiveFilter.kind === "all"
      ? "all"
      : effectiveFilter.kind === "price"
        ? `price:${effectiveFilter.price}`
        : `game:${effectiveFilter.gameId}`;
  const series = useMemo(() => {
    const filtered = entries.filter((entry) =>
      effectiveFilter.kind === "all"
        ? true
        : effectiveFilter.kind === "price"
          ? entry.ticketPrice === effectiveFilter.price
          : entry.gameId === effectiveFilter.gameId,
    );
    return buildDailySeries(filtered);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, filterKey]);

  const geometry = useMemo(() => {
    if (series.length === 0) return null;
    const values = series.map((point) => point.cumulative);
    const { min, max, ticks } = niceDollarScale(Math.min(0, ...values), Math.max(0, ...values));
    const x = (index: number) =>
      MARGIN.left + (series.length === 1 ? PLOT_W / 2 : (index / (series.length - 1)) * PLOT_W);
    const y = (value: number) => MARGIN.top + ((max - value) / (max - min)) * PLOT_H;
    const segments = series.slice(1).map((point, index) => {
      const previous = series[index]!;
      const change = point.cumulative - previous.cumulative;
      return {
        key: point.date,
        direction: tone(change),
        x1: round2(x(index)),
        y1: round2(y(previous.cumulative)),
        x2: round2(x(index + 1)),
        y2: round2(y(point.cumulative)),
      };
    });
    const labelEvery = Math.max(1, Math.ceil(series.length / 6));
    const dateLabels = series
      .map((point, index) => ({ point, index }))
      .filter(({ index }) => index % labelEvery === 0 || index === series.length - 1);
    return { min, max, ticks, x, y, segments, dateLabels };
  }, [series]);

  const hovered = hoverIndex === null ? null : (series[hoverIndex] ?? null);

  return (
    <section aria-labelledby="winnings-chart-title" className="winnings-chart">
      <div className="winnings-chart__heading">
        <h2 id="winnings-chart-title">Results over time</h2>
        <p>Running net total of what you won minus what you spent, day by day.</p>
      </div>
      <div className="winnings-chart__filters">
        <div aria-label="Filter chart by ticket price" className="chart-pills" role="group">
          <button
            aria-pressed={effectiveFilter.kind === "all"}
            className={effectiveFilter.kind === "all" ? "is-active" : ""}
            onClick={() => setFilter({ kind: "all" })}
            type="button"
          >
            All
          </button>
          {prices.map((price) => (
            <button
              aria-pressed={effectiveFilter.kind === "price" && effectiveFilter.price === price}
              className={
                effectiveFilter.kind === "price" && effectiveFilter.price === price
                  ? "is-active"
                  : ""
              }
              key={price}
              onClick={() => setFilter({ kind: "price", price })}
              type="button"
            >
              ${price}
            </button>
          ))}
        </div>
        <label className="winnings-chart__game">
          Game
          <select
            onChange={(event) =>
              setFilter(
                event.target.value === ""
                  ? { kind: "all" }
                  : { kind: "game", gameId: Number(event.target.value) },
              )
            }
            value={effectiveFilter.kind === "game" ? effectiveFilter.gameId : ""}
          >
            <option value=""></option>
            {gameOptions.map((game) => (
              <option key={game.gameId} value={game.gameId}>
                {formatTicketOption(game)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {series.length === 0 || geometry === null ? (
        <p className="winnings-chart__empty">No saved results for this selection yet.</p>
      ) : (
        <div className="winnings-chart__plot" onMouseLeave={() => setHoverIndex(null)}>
          <svg
            aria-label="Cumulative winnings and losses by day"
            onMouseLeave={() => setHoverIndex(null)}
            onMouseMove={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              const px = ((event.clientX - rect.left) / rect.width) * WIDTH;
              const ratio = Math.min(1, Math.max(0, (px - MARGIN.left) / PLOT_W));
              setHoverIndex(Math.round(ratio * (series.length - 1)));
            }}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          >
            {/* Minor gridlines halfway between major ticks. */}
            {geometry.ticks.slice(0, -1).map((tick, index) => {
              const midway = (tick + geometry.ticks[index + 1]!) / 2;
              return (
                <line
                  className="winnings-chart__grid-minor"
                  key={`minor-${tick}`}
                  x1={MARGIN.left}
                  x2={WIDTH - MARGIN.right}
                  y1={round2(geometry.y(midway))}
                  y2={round2(geometry.y(midway))}
                />
              );
            })}
            {geometry.ticks.map((tick) => (
              <g key={`major-${tick}`}>
                <line
                  className="winnings-chart__grid-major"
                  x1={MARGIN.left}
                  x2={WIDTH - MARGIN.right}
                  y1={round2(geometry.y(tick))}
                  y2={round2(geometry.y(tick))}
                />
                <text className="winnings-chart__axis-label" textAnchor="end" x={MARGIN.left - 8} y={round2(geometry.y(tick)) + 3.5}>
                  {axisMoney(tick)}
                </text>
              </g>
            ))}
            {geometry.min < 0 && geometry.max > 0 ? (
              <line
                className="winnings-chart__zero"
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={round2(geometry.y(0))}
                y2={round2(geometry.y(0))}
              />
            ) : null}
            {geometry.dateLabels.map(({ point, index }) => (
              <text
                className="winnings-chart__axis-label"
                key={point.date}
                textAnchor="middle"
                x={round2(geometry.x(index))}
                y={HEIGHT - 8}
              >
                {shortDate(point.date)}
              </text>
            ))}
            {hoverIndex !== null ? (
              <line
                className="winnings-chart__crosshair"
                x1={round2(geometry.x(hoverIndex))}
                x2={round2(geometry.x(hoverIndex))}
                y1={MARGIN.top}
                y2={MARGIN.top + PLOT_H}
              />
            ) : null}
            {geometry.segments.map((segment) => (
              <line
                className={`winnings-chart__segment is-${segment.direction}`}
                key={segment.key}
                x1={segment.x1}
                y1={segment.y1}
                x2={segment.x2}
                y2={segment.y2}
              />
            ))}
            {series.map((point, index) => (
              <circle
                className={
                  point.hasEntry
                    ? `winnings-chart__dot is-entry is-${tone(point.dayNet)}`
                    : "winnings-chart__dot is-neutral"
                }
                cx={round2(geometry.x(index))}
                cy={round2(geometry.y(point.cumulative))}
                key={point.date}
                r={point.hasEntry ? 3.2 : 1.4}
              />
            ))}
          </svg>
          {hovered !== null && hoverIndex !== null ? (
            <div
              className="winnings-chart__tooltip"
              data-side={geometry.x(hoverIndex) > WIDTH * 0.62 ? "left" : "right"}
              style={{
                left: `${(geometry.x(hoverIndex) / WIDTH) * 100}%`,
                top: `${(geometry.y(hovered.cumulative) / HEIGHT) * 100}%`,
              }}
            >
              <strong>{shortDate(hovered.date)}</strong>
              <span data-tone={tone(hovered.cumulative)}>Net position {signedMoney(hovered.cumulative)}</span>
              {hovered.hasEntry ? (
                <span data-tone={tone(hovered.dayNet)}>This day {signedMoney(hovered.dayNet)}</span>
              ) : (
                <span>No tickets this day</span>
              )}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

export function buildDailySeries(entries: TicketEntry[], endDate = todayLocal()): DailyPoint[] {
  if (entries.length === 0) return [];
  const netByDay = new Map<string, number>();
  for (const entry of entries) {
    netByDay.set(entry.playedOn, (netByDay.get(entry.playedOn) ?? 0) + entry.netResult);
  }
  const first = [...netByDay.keys()].sort()[0]!;
  const points: DailyPoint[] = [];
  let cumulative = 0;
  let cursor = Date.parse(`${first}T00:00:00Z`);
  const end = Date.parse(`${endDate}T00:00:00Z`);
  while (cursor <= end) {
    const date = new Date(cursor).toISOString().slice(0, 10);
    const dayNet = netByDay.get(date);
    cumulative = round2(cumulative + (dayNet ?? 0));
    points.push({ date, cumulative, dayNet: dayNet ?? 0, hasEntry: dayNet !== undefined });
    cursor += 86_400_000;
  }
  return points;
}

function niceDollarScale(rawMin: number, rawMax: number): { min: number; max: number; ticks: number[] } {
  const span = Math.max(rawMax - rawMin, 1);
  const roughStep = span / 4;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const step =
    [1, 2, 2.5, 5, 10].map((mult) => mult * magnitude).find((candidate) => candidate >= roughStep) ??
    10 * magnitude;
  const min = Math.floor(rawMin / step) * step;
  const max = Math.ceil(rawMax / step) * step;
  const ticks: number[] = [];
  for (let tick = min; tick <= max + step / 2; tick += step) ticks.push(round2(tick));
  return { min, max, ticks };
}

function todayLocal(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function tone(value: number): "negative" | "positive" | "neutral" {
  return value < 0 ? "negative" : value > 0 ? "positive" : "neutral";
}

function axisMoney(value: number): string {
  const abs = Math.abs(value);
  const text = abs >= 1000 ? `$${abs / 1000}k` : `$${abs}`;
  return value < 0 ? `−${text}` : text;
}

function signedMoney(value: number): string {
  const digits = Number.isInteger(value) ? 0 : 2;
  const text = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Math.abs(value));
  if (value === 0) return text;
  return `${value > 0 ? "+" : "−"}${text}`;
}

function shortDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(`${value}T00:00:00Z`),
  );
}
