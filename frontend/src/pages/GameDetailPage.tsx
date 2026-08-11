import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { GameHistorySection } from "../components/GameHistoryCharts";
import { formatMoney, formatOneIn } from "../lib/strategies";
import { loadGameDetail } from "../services/gameDetails";
import type { GameDetail, GamePrizeTier } from "../types/gameDetails";
import type { GameHistory } from "../types/gameHistory";

interface GameDetailPageProps {
  detailOverride?: GameDetail;
  historyOverride?: GameHistory;
}

export function GameDetailPage({ detailOverride, historyOverride }: GameDetailPageProps) {
  const { gameId: gameIdParam } = useParams();
  const gameId = Number(gameIdParam);
  const validGameId = Number.isInteger(gameId) && gameId > 0;
  const [detail, setDetail] = useState<GameDetail | null>(
    detailOverride?.gameId === gameId ? detailOverride : null,
  );
  const [error, setError] = useState<string | null>(
    validGameId ? null : "This game address is invalid.",
  );

  useEffect(() => {
    if (!validGameId) return;
    if (detailOverride?.gameId === gameId) {
      setDetail(detailOverride);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    loadGameDetail(gameId, controller.signal)
      .then(setDetail)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Game detail failed to load.");
        }
      });
    return () => controller.abort();
  }, [detailOverride, gameId, validGameId]);

  useEffect(() => {
    if (!detail) return;
    const previousTitle = document.title;
    document.title = `${detail.gameName} | Illinois Lottery Tracker`;
    return () => {
      document.title = previousTitle;
    };
  }, [detail]);

  if (error) {
    return (
      <main className="game-detail-page" id="main-content">
        <DetailBackLink />
        <section className="load-state" role="alert">
          <p className="eyebrow">GAME DETAIL</p>
          <h1>We could not load this game.</h1>
          <p>{error}</p>
          <Link className="button" to="/#rankings">Return to the comparison</Link>
        </section>
      </main>
    );
  }
  if (!detail) {
    return (
      <main className="game-detail-page" id="main-content">
        <section className="load-state" aria-live="polite">
          <span className="loading-line" />
          <p>Loading game details…</p>
        </section>
      </main>
    );
  }

  return (
    <main className="game-detail-page" id="main-content">
      <DetailBackLink />
      <GameDetailHeader detail={detail} />
      <PrizeTierSection detail={detail} />
      <GameHistorySection gameId={detail.gameId} historyOverride={historyOverride} />
    </main>
  );
}

function DetailBackLink() {
  return <Link className="game-detail__back" to="/#rankings">← Back to comparison</Link>;
}

function GameDetailHeader({ detail }: { detail: GameDetail }) {
  return (
    <section className="game-detail-hero" aria-labelledby="game-detail-title">
      <div className="game-detail-hero__title">
        <p className="eyebrow">GAME {detail.gameNumber} · CURRENT DETAIL</p>
        <h1 id="game-detail-title">{detail.gameName}</h1>
        <p>
          Current prize inventory and estimated odds from the same published cutoff as
          the comparison page.
        </p>
      </div>
      <dl className="game-detail-facts">
        <Fact label="Ticket price" value={formatMoney(detail.ticketPrice)} />
        <Fact
          label="Published overall odds"
          value={formatOneIn(detail.publishedOverallOddsOneIn)}
        />
        <Fact
          label="Top prize"
          value={formatMoney(detail.topPrizeAmount, true)}
          detail={formatCountPair(detail.topPrizesRemaining, detail.topPrizesOriginal)}
        />
        <Fact
          label="Est. tickets sold"
          value={formatWholeEstimate(detail.estimatedSoldTickets)}
        />
        <Fact
          label="Est. tickets remaining"
          value={formatWholeEstimate(detail.estimatedRemainingTickets)}
        />
        <Fact
          label="Time in market"
          value={detail.weeksInMarket === null ? "Unavailable" : `${detail.weeksInMarket} weeks`}
        />
      </dl>
      <p className="game-detail-hero__cutoff">
        Prize counts observed <DetailTimestamp value={detail.sourceObservedAt} /> · Model {" "}
        {detail.modelVersion}
      </p>
    </section>
  );
}

function Fact({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function PrizeTierSection({ detail }: { detail: GameDetail }) {
  return (
    <section className="prize-tier-section" aria-labelledby="prize-tier-title">
      <div className="prize-tier-section__heading">
        <div>
          <p className="eyebrow">PRIZE INVENTORY</p>
          <h2 id="prize-tier-title">Every prize tier, in one view</h2>
        </div>
        <p>{detail.tiers.length} reported prize tiers</p>
      </div>
      <div className="prize-tier-table-wrap">
        <table className="prize-tier-table" aria-describedby="prize-tier-note">
          <caption className="visually-hidden">
            Current prize tiers for {detail.gameName}, including official counts and
            estimated odds.
          </caption>
          <thead>
            <tr>
              <th scope="col">Prize</th>
              <th scope="col">Starting prizes</th>
              <th scope="col">Claimed</th>
              <th scope="col">Reported unclaimed</th>
              <th scope="col">Est. unclaimed now</th>
              <th scope="col">Est. odds now</th>
              <th scope="col">Launch odds</th>
            </tr>
          </thead>
          <tbody>
            {detail.tiers.map((tier) => (
              <PrizeTierRow key={tier.prizeAmount} tier={tier} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="prize-tier-note" id="prize-tier-note">
        <strong>How to read this table</strong>
        <p>
          Claimed is the starting count minus the official reported-unclaimed count.
          “Est. unclaimed now” subtracts estimated pending claims only for eligible
          prize tiers over $600 with at least 300 starting prizes. Other tiers retain
          the official count. Odds are estimates, not guarantees.
        </p>
      </div>
    </section>
  );
}

function PrizeTierRow({ tier }: { tier: GamePrizeTier }) {
  return (
    <tr data-adjusted={tier.adjustmentStatus === "applied"} data-top={tier.isTopPrize}>
      <th scope="row">
        <strong>{formatMoney(tier.prizeAmount)}</strong>
        {tier.isTopPrize ? <small>Top prize</small> : null}
      </th>
      <td>{formatInteger(tier.originalCount)}</td>
      <td>{formatInteger(tier.claimedCount)}</td>
      <td>{formatInteger(tier.reportedRemainingCount)}</td>
      <td>
        <strong>{formatEstimatedCount(tier.estimatedRemainingCount)}</strong>
        {tier.adjustmentStatus === "applied" ? (
          <small>
            Lag-adjusted · {formatEstimatedCount(tier.estimatedPendingCount)} pending
          </small>
        ) : null}
      </td>
      <td>
        <strong>{formatOneIn(tier.currentOneIn)}</strong>
        {tier.confidenceLabel ? <small>{tier.confidenceLabel} confidence</small> : null}
      </td>
      <td>{formatOneIn(tier.launchOneIn)}</td>
    </tr>
  );
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatEstimatedCount(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function formatWholeEstimate(value: number | null): string {
  return value === null ? "Unavailable" : `≈ ${formatInteger(Math.round(value))}`;
}

function formatCountPair(remaining: number | null, original: number | null): string {
  if (remaining === null || original === null) return "Count unavailable";
  return `${formatInteger(remaining)} out of ${formatInteger(original)} left`;
}

function DetailTimestamp({ value }: { value: string }) {
  const formatted = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "America/Chicago",
  }).format(new Date(value));
  return <time dateTime={value}>{formatted}</time>;
}
