import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import {
  EvidenceGuide,
  EvidenceTag,
  type EvidenceKind,
} from "../components/EvidenceGuide";
import { GameHistorySection } from "../components/GameHistoryCharts";
import { JackpotDependenceDetail } from "../components/JackpotDependence";
import { OutcomeLadder } from "../components/OutcomeLadder";
import { formatMoney, formatOneIn } from "../lib/strategies";
import { comparisonHref, parseViewState } from "../lib/urlState";
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
    document.title = `${detail.gameName} | Scratch-Off Data`;
    return () => {
      document.title = previousTitle;
    };
  }, [detail]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [gameId]);

  if (error) {
    return (
      <main className="game-detail-page" id="main-content">
        <DetailNavigation />
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
        <DetailNavigation />
        <section className="load-state" aria-live="polite">
          <span className="loading-line" />
          <p>Loading game details…</p>
        </section>
      </main>
    );
  }

  return (
    <main className="game-detail-page" id="main-content">
      <DetailNavigation />
      <GameDetailHeader detail={detail} />
      <div className="game-insight-grid">
        <JackpotDependenceDetail
          estimatedEvExTop={detail.estimatedEvExTop}
          estimatedEvFull={detail.estimatedEvFull}
          ticketPrice={detail.ticketPrice}
        />
        <OutcomeLadder detail={detail} />
      </div>
      <PrizeTierSection detail={detail} />
      <GameHistorySection gameId={detail.gameId} historyOverride={historyOverride} />
    </main>
  );
}

function DetailNavigation() {
  const location = useLocation();
  const viewState = parseViewState(location.search);
  return (
    <div className="game-detail-navigation">
      <Link className="game-detail__back" to={comparisonHref(viewState)}>
        ← Back to comparison
      </Link>
    </div>
  );
}

function GameDetailHeader({ detail }: { detail: GameDetail }) {
  return (
    <section className="game-detail-hero" aria-labelledby="game-detail-title">
      <div className="game-detail-hero__title">
        <p className="eyebrow">
          GAME {detail.gameNumber} · {formatMoney(detail.ticketPrice)} TICKET
        </p>
        <h1 id="game-detail-title">{detail.gameName}</h1>
      </div>
      <dl className="game-detail-facts">
        <div className="game-detail-fact game-detail-fact--odds">
          <dt>Overall chances</dt>
          <dd>
            <span>
              <small>Official odds at launch</small>
              <strong>{formatOneIn(detail.publishedOverallOddsOneIn)}</strong>
              <EvidenceTag kind="official" />
            </span>
            <span>
              <small>Estimated chance now</small>
              <strong>{formatOneIn(detail.estimatedCurrentOverallOddsOneIn)}</strong>
              <EvidenceTag kind="estimated" />
            </span>
          </dd>
        </div>
        <Fact
          evidence="official"
          label="Top prize"
          value={formatMoney(detail.topPrizeAmount, true)}
          detail={formatCountPair(detail.topPrizesRemaining, detail.topPrizesOriginal)}
        />
        <div className="game-detail-fact game-detail-fact--return">
          <dt>Estimated prize return</dt>
          <dd>
            <span>
              <small>All prizes</small>
              <strong>{formatReturnPerDollar(detail.estimatedEvFull, detail.ticketPrice)}</strong>
            </span>
            <span>
              <small>Without jackpot</small>
              <strong>{formatReturnPerDollar(detail.estimatedEvExTop, detail.ticketPrice)}</strong>
            </span>
          </dd>
          <EvidenceTag kind="estimated" />
        </div>
        <Fact
          evidence="calculated"
          label="Time in market"
          value={detail.weeksInMarket === null ? "Unavailable" : `${detail.weeksInMarket} weeks`}
        />
      </dl>
    </section>
  );
}

function Fact({
  label,
  value,
  detail,
  evidence,
}: {
  label: string;
  value: string;
  detail?: string;
  evidence: EvidenceKind;
}) {
  return (
    <div className="game-detail-fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
      {detail ? <small>{detail}</small> : null}
      <EvidenceTag kind={evidence} />
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
        <table
          className="prize-tier-table"
          aria-describedby="prize-tier-note"
        >
          <caption className="visually-hidden">
            Current prize tiers for {detail.gameName}, including official counts and
            estimated chances.
          </caption>
          <thead>
            <tr>
              <th scope="col">Prize</th>
              <EvidenceHeader kind="official" label="Starting prizes" />
              <EvidenceHeader kind="calculated" label="Claimed" />
              <EvidenceHeader kind="official" label="Reported unclaimed" />
              <th scope="col">Current count used</th>
              <EvidenceHeader kind="estimated" label="Estimated chance now" />
              <EvidenceHeader kind="estimated" label="Estimated chance at launch" />
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
        <div className="prize-tier-note__reading">
          <strong>How to read this table</strong>
          <p>
            “Claimed” is starting prizes minus the official reported-unclaimed count.
            “Current count used” applies the 24-day working assumption only to prize
            tiers over $600 with at least 300 starting prizes; every other tier keeps
            the official count. Current and launch chances are estimates because live
            ticket inventory is not published. They describe the game, not the next ticket.
          </p>
        </div>
        <EvidenceGuide id="prize-evidence-key" />
      </div>
    </section>
  );
}

function EvidenceHeader({ label, kind }: { label: string; kind: EvidenceKind }) {
  return (
    <th scope="col">
      <span>{label}</span>
      <EvidenceTag kind={kind} />
    </th>
  );
}

function PrizeTierRow({ tier }: { tier: GamePrizeTier }) {
  const chanceTrend = tierChanceTrend(tier);
  const countExplanation = currentCountExplanation(tier);
  return (
    <tr data-chance-trend={chanceTrend} data-top={tier.isTopPrize}>
      <th scope="row">
        <strong>{formatMoney(tier.prizeAmount)}</strong>
        {tier.isTopPrize ? <small>Top prize</small> : null}
      </th>
      <td>{formatInteger(tier.originalCount)}</td>
      <td>{formatInteger(tier.claimedCount)}</td>
      <td>{formatInteger(tier.reportedRemainingCount)}</td>
      <td>
        <strong>{formatEstimatedCount(tier.estimatedRemainingCount)}</strong>
        <EvidenceTag kind={tier.adjustmentStatus === "applied" ? "adjusted" : "official"} />
        {countExplanation ? <small>{countExplanation}</small> : null}
      </td>
      <td className="prize-tier-table__current-chance">
        <strong>{formatOneIn(tier.currentOneIn)}</strong>
        <ChanceTrendLabel trend={chanceTrend} />
      </td>
      <td>
        <strong>{formatOneIn(tier.launchOneIn)}</strong>
      </td>
    </tr>
  );
}

type TierChanceTrend = "better" | "worse" | "same" | "unavailable";

const MATERIAL_CHANCE_CHANGE = 0.02;

export function tierChanceTrend(tier: GamePrizeTier): TierChanceTrend {
  if (
    tier.currentOneIn === null ||
    tier.launchOneIn === null ||
    tier.currentOneIn <= 0 ||
    tier.launchOneIn <= 0
  ) {
    return "unavailable";
  }
  const relativeChange = tier.launchOneIn / tier.currentOneIn - 1;
  if (relativeChange >= MATERIAL_CHANCE_CHANGE) return "better";
  if (relativeChange <= -MATERIAL_CHANCE_CHANGE) return "worse";
  return "same";
}

function ChanceTrendLabel({ trend }: { trend: TierChanceTrend }) {
  if (trend === "unavailable") return null;
  const labels: Record<Exclude<TierChanceTrend, "unavailable">, string> = {
    better: "Better estimated chance than at launch",
    worse: "Worse estimated chance than at launch",
    same: "About the same as at launch",
  };
  return <span className={`chance-trend chance-trend--${trend}`}>{labels[trend]}</span>;
}

function currentCountExplanation(tier: GamePrizeTier): string | null {
  if (tier.adjustmentStatus === "applied") {
    return `${formatEstimatedCount(tier.estimatedPendingCount)} estimated pending · ${tier.lagDaysUsed ?? 24}-day working assumption`;
  }
  return null;
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatEstimatedCount(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function formatReturnPerDollar(value: number | null, ticketPrice: number): string {
  if (value === null || ticketPrice <= 0) return "Unavailable";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(
    (value / ticketPrice) * 100,
  )}¢ per $1`;
}

function formatCountPair(remaining: number | null, original: number | null): string {
  if (remaining === null || original === null) return "Count unavailable";
  return `${formatInteger(remaining)} out of ${formatInteger(original)} left`;
}
