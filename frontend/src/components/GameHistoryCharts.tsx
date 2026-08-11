import { useEffect, useMemo, useState, type CSSProperties } from "react";

import { formatMoney } from "../lib/strategies";
import { loadGameHistory } from "../services/gameHistory";
import type {
  GameHistory,
  TicketSalesHistoryPoint,
  TierClaimHistorySeries,
} from "../types/gameHistory";
import { EvidenceTag } from "./EvidenceGuide";
import { TimeSeriesChart, type TimeSeriesChartSeries } from "./TimeSeriesChart";

const MAX_SELECTED_TIERS = 6;
const TIER_STYLES: ReadonlyArray<{ color: string; dash?: string }> = [
  { color: "#266b8f" },
  { color: "#c95035", dash: "8 4" },
  { color: "#28745d", dash: "3 3" },
  { color: "#7353a6", dash: "11 4 2 4" },
  { color: "#8a6500", dash: "2 4" },
  { color: "#6b4f3d", dash: "12 5" },
];

interface GameHistorySectionProps {
  gameId: number;
  historyOverride?: GameHistory;
}

export function GameHistorySection({ gameId, historyOverride }: GameHistorySectionProps) {
  const [history, setHistory] = useState<GameHistory | null>(
    historyOverride?.gameId === gameId ? historyOverride : null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (historyOverride?.gameId === gameId) {
      setHistory(historyOverride);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setHistory(null);
    setError(null);
    loadGameHistory(gameId, controller.signal)
      .then(setHistory)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Game history failed to load.");
        }
      });
    return () => controller.abort();
  }, [gameId, historyOverride]);

  return (
    <section className="game-history-section" aria-labelledby="game-history-title">
      <div className="game-history-section__heading">
        <p className="eyebrow">GAME HISTORY</p>
        <h2 id="game-history-title">How this game has changed over time</h2>
        <p>
          Dated estimates and official claimed-prize counts through the latest
          published data date.
        </p>
      </div>
      {error ? (
        <div className="chart-state" role="status">
          <strong>Historical charts are temporarily unavailable.</strong>
          <p>{error} The current prize-tier table above remains available.</p>
        </div>
      ) : history ? (
        <div className="game-history-stack">
          <SalesHistoryChart history={history} />
          <TierClaimHistoryChart history={history} />
        </div>
      ) : (
        <div className="chart-state" aria-live="polite">
          <span className="loading-line" />
          <p>Loading game history…</p>
        </div>
      )}
    </section>
  );
}

function SalesHistoryChart({ history }: { history: GameHistory }) {
  const points = history.salesPoints;
  const first = points[0];
  const latest = points.at(-1);
  if (!first || !latest) {
    return <ChartUnavailable title="Estimated tickets sold" />;
  }
  const maximum = niceCeiling(Math.max(...points.map((point) => point.estimatedSoldTickets)));
  const chartSeries: TimeSeriesChartSeries[] = [
    {
      key: "estimated-sold",
      label: "Estimated tickets sold",
      color: "#266b8f",
      points: points.map((point) => ({
        observedAt: point.observedAt,
        value: point.estimatedSoldTickets,
        segment: point.segment,
      })),
    },
  ];
  return (
    <article className="history-chart-card" aria-labelledby="sales-history-title">
      <ChartHeader
        eyebrow="SALES ESTIMATE"
        id="sales-history-title"
        title="Estimated tickets sold"
        summary={`≈ ${formatInteger(Math.round(latest.estimatedSoldTickets))}`}
        detail={`${formatInteger(points.length)} dated observations · ${formatSignedCount(
          latest.estimatedSoldTickets - first.estimatedSoldTickets,
        )} since the first observation`}
      />
      <TimeSeriesChart
        ariaLabel={`Estimated tickets sold over time for ${history.gameName}`}
        description={`A single line from ${formatLongDate(first.observedAt)} to ${formatLongDate(
          latest.observedAt,
        )}, ending at approximately ${formatInteger(Math.round(latest.estimatedSoldTickets))} tickets sold.`}
        formatY={formatCompactNumber}
        series={chartSeries}
        unitLabel="Estimated tickets sold"
        yDomain={[0, maximum]}
      />
      <p className="chart-caveat">
        <EvidenceTag kind="estimated" />{" "}
        This is inferred from the public prize pool and published overall odds; it is
        not an official sales count. Line breaks mark published prize-structure changes.
      </p>
      <SalesHistoryTable points={points} />
    </article>
  );
}

function TierClaimHistoryChart({ history }: { history: GameHistory }) {
  const defaultPrizes = useMemo(
    () => history.tierSeries.slice(0, Math.min(4, history.tierSeries.length)).map(tierKey),
    [history.tierSeries],
  );
  const [selectedPrizes, setSelectedPrizes] = useState<string[]>(defaultPrizes);
  useEffect(() => setSelectedPrizes(defaultPrizes), [defaultPrizes]);

  const selectedSeries = history.tierSeries.filter((series) =>
    selectedPrizes.includes(tierKey(series)),
  );
  const chartSeries = selectedSeries.map((series) => chartTierSeries(series, history.tierSeries));
  const toggleTier = (series: TierClaimHistorySeries) => {
    const key = tierKey(series);
    setSelectedPrizes((current) => {
      if (current.includes(key)) {
        return current.length === 1 ? current : current.filter((item) => item !== key);
      }
      return current.length >= MAX_SELECTED_TIERS ? current : [...current, key];
    });
  };
  return (
    <article className="history-chart-card" aria-labelledby="tier-history-title">
      <ChartHeader
        eyebrow="CLAIM PROGRESS"
        id="tier-history-title"
        title="Prizes claimed by tier"
        summary={`${selectedSeries.length} of ${history.tierSeries.length} tiers`}
        detail="A shared 0–100% scale makes prize tiers comparable"
      />
      <ul className="chart-series-key" aria-label="Displayed prize tiers">
        {selectedSeries.map((series) => {
          const style = tierStyle(series, history.tierSeries);
          const latest = series.points.at(-1)?.claimedFraction;
          return (
            <li key={tierKey(series)}>
              <span
                aria-hidden="true"
                className="chart-series-key__line"
                style={
                  {
                    "--series-color": style.color,
                    "--series-line-style": style.dash ? "dashed" : "solid",
                  } as CSSProperties
                }
              />
              <strong>{formatMoney(series.prizeAmount, true)}</strong>
              <span>{latest === null || latest === undefined ? "Unavailable" : formatPercent(latest)} claimed</span>
            </li>
          );
        })}
      </ul>
      <TimeSeriesChart
        ariaLabel={`Percentage of prizes claimed by selected tier for ${history.gameName}`}
        description={`${selectedSeries.length} selected prize-tier lines on a shared zero-to-one-hundred-percent claimed scale.`}
        formatY={formatPercent}
        series={chartSeries}
        unitLabel="Share of prizes claimed"
        yDomain={[0, 1]}
      />
      <fieldset className="tier-series-controls">
        <legend>Choose up to six prize tiers</legend>
        <div>
          {history.tierSeries.map((series) => {
            const key = tierKey(series);
            const checked = selectedPrizes.includes(key);
            return (
              <label key={key}>
                <input
                  checked={checked}
                  disabled={!checked && selectedPrizes.length >= MAX_SELECTED_TIERS}
                  onChange={() => toggleTier(series)}
                  type="checkbox"
                />
                <span>{formatMoney(series.prizeAmount, true)}</span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <p className="chart-caveat">
        <EvidenceTag kind="calculated" />{" "}
        These lines use official claimed counts divided by each tier’s starting count.
        A steeper line means that tier was claimed faster during that period.
      </p>
      <TierHistoryTable series={selectedSeries} />
    </article>
  );
}

function ChartHeader({
  eyebrow,
  id,
  title,
  summary,
  detail,
}: {
  eyebrow: string;
  id: string;
  title: string;
  summary: string;
  detail: string;
}) {
  return (
    <header className="history-chart-card__header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h3 id={id}>{title}</h3>
      </div>
      <div className="history-chart-card__summary">
        <strong>{summary}</strong>
        <span>{detail}</span>
      </div>
    </header>
  );
}

function ChartUnavailable({ title }: { title: string }) {
  return (
    <article className="history-chart-card chart-state">
      <strong>{title} is unavailable.</strong>
      <p>There are not enough compatible historical observations to draw this chart.</p>
    </article>
  );
}

function SalesHistoryTable({ points }: { points: TicketSalesHistoryPoint[] }) {
  return (
    <details className="chart-data-disclosure">
      <summary>View exact sales-history data</summary>
      <div className="chart-data-table-wrap">
        <table className="chart-data-table">
          <thead><tr><th>Date</th><th>Estimated sold</th><th>Estimated remaining</th><th>Estimated total</th></tr></thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.observedAt}>
                <th scope="row">{formatLongDate(point.observedAt)}</th>
                <td>{formatInteger(Math.round(point.estimatedSoldTickets))}</td>
                <td>{formatInteger(Math.round(point.estimatedRemainingTickets))}</td>
                <td>{formatInteger(Math.round(point.estimatedOriginalTickets))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function TierHistoryTable({ series }: { series: TierClaimHistorySeries[] }) {
  const dates = [
    ...new Set(series.flatMap((item) => item.points.map((point) => point.observedAt))),
  ].sort();
  return (
    <details className="chart-data-disclosure">
      <summary>View exact selected-tier history</summary>
      <div className="chart-data-table-wrap">
        <table className="chart-data-table">
          <thead>
            <tr>
              <th>Date</th>
              {series.map((item) => (
                <th key={tierKey(item)}>{formatMoney(item.prizeAmount, true)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dates.map((date) => (
              <tr key={date}>
                <th scope="row">{formatLongDate(date)}</th>
                {series.map((item) => {
                  const point = item.points.find((candidate) => candidate.observedAt === date);
                  return (
                    <td key={tierKey(item)}>
                      {point?.claimedFraction === null || point?.claimedFraction === undefined
                        ? "—"
                        : `${formatPercent(point.claimedFraction)} (${formatInteger(point.claimedCount)} claimed)`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function chartTierSeries(
  series: TierClaimHistorySeries,
  allSeries: TierClaimHistorySeries[],
): TimeSeriesChartSeries {
  const style = tierStyle(series, allSeries);
  return {
    key: tierKey(series),
    label: formatMoney(series.prizeAmount, true),
    color: style.color,
    dash: style.dash,
    points: series.points.flatMap((point) =>
      point.claimedFraction === null
        ? []
        : [{ observedAt: point.observedAt, value: point.claimedFraction, segment: point.segment }],
    ),
  };
}

function tierStyle(series: TierClaimHistorySeries, allSeries: TierClaimHistorySeries[]) {
  const index = allSeries.findIndex((item) => tierKey(item) === tierKey(series));
  return TIER_STYLES[Math.max(0, index) % TIER_STYLES.length]!;
}

function tierKey(series: TierClaimHistorySeries): string {
  return String(series.prizeAmount);
}

function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step =
    [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find(
      (candidate) => candidate >= normalized,
    ) ?? 10;
  return step * magnitude;
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: value >= 1_000 ? "compact" : "standard",
    maximumFractionDigits: value >= 1_000 ? 1 : 0,
  }).format(value);
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatSignedCount(value: number): string {
  const rounded = Math.round(value);
  return new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(rounded);
}

function formatLongDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "America/Chicago",
  }).format(new Date(value));
}
