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
import { ShareLinkButton } from "../components/ShareLinkButton";
import { formatMoney, formatOneIn } from "../lib/strategies";
import {
  comparisonHref,
  gameDetailHref,
  parseViewState,
  viewStateLabel,
} from "../lib/urlState";
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
      <DetailNavigation gameId={detail.gameId} />
      <GameDetailHeader detail={detail} />
      <JackpotDependenceDetail
        estimatedEvExTop={detail.estimatedEvExTop}
        estimatedEvFull={detail.estimatedEvFull}
        ticketPrice={detail.ticketPrice}
      />
      <OutcomeLadder detail={detail} />
      <PrizeTierSection detail={detail} />
      <GameHistorySection gameId={detail.gameId} historyOverride={historyOverride} />
    </main>
  );
}

function DetailNavigation({ gameId }: { gameId?: number }) {
  const location = useLocation();
  const viewState = parseViewState(location.search);
  return (
    <div className="game-detail-navigation">
      <div>
        <Link className="game-detail__back" to={comparisonHref(viewState)}>
          ← Back to comparison
        </Link>
        <p>Returns to {viewStateLabel(viewState)}</p>
      </div>
      {gameId ? (
        <ShareLinkButton
          href={gameDetailHref(gameId, viewState)}
          label="Copy this game view"
          successMessage="Game link copied."
        />
      ) : null}
    </div>
  );
}

function GameDetailHeader({ detail }: { detail: GameDetail }) {
  return (
    <section className="game-detail-hero" aria-labelledby="game-detail-title">
      <div className="game-detail-hero__title">
        <p className="eyebrow">GAME {detail.gameNumber} · CURRENT DETAIL</p>
        <h1 id="game-detail-title">{detail.gameName}</h1>
        <p>
          Current prize inventory and estimated chances from the same published data
          date as the comparison page.
        </p>
      </div>
      <dl className="game-detail-facts">
        <Fact evidence="official" label="Ticket price" value={formatMoney(detail.ticketPrice)} />
        <Fact
          evidence="official"
          label="Official overall odds"
          value={formatOneIn(detail.publishedOverallOddsOneIn)}
        />
        <Fact
          evidence="official"
          label="Top prize"
          value={formatMoney(detail.topPrizeAmount, true)}
          detail={formatCountPair(detail.topPrizesRemaining, detail.topPrizesOriginal)}
        />
        <Fact
          evidence="estimated"
          label="Estimated tickets sold"
          value={formatWholeEstimate(detail.estimatedSoldTickets)}
        />
        <Fact
          evidence="estimated"
          label="Estimated tickets remaining"
          value={formatWholeEstimate(detail.estimatedRemainingTickets)}
        />
        <Fact
          evidence="calculated"
          label="Time in market"
          value={detail.weeksInMarket === null ? "Unavailable" : `${detail.weeksInMarket} weeks`}
        />
      </dl>
      <p className="game-detail-hero__cutoff">
        Official prize counts dated <DetailTimestamp value={detail.sourceObservedAt} /> ·
        Page updated <DetailTimestamp value={detail.generatedAt} />
      </p>
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
    <div>
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
      <EvidenceGuide id="prize-evidence-key" />
      <div className="prize-tier-table-wrap">
        <table
          className="prize-tier-table"
          aria-describedby="prize-evidence-key prize-tier-note"
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
        <strong>How to read this table</strong>
        <p>
          “Claimed” is starting prizes minus the official reported-unclaimed count.
          “Current count used” applies the 24-day working assumption only to prize
          tiers over $600 with at least 300 starting prizes; every other tier keeps
          the official count. Current and launch chances are estimates because live
          ticket inventory is not published. They describe the game, not the next ticket.
        </p>
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
        <EvidenceTag kind={tier.adjustmentStatus === "applied" ? "adjusted" : "official"} />
        <small>{currentCountExplanation(tier)}</small>
      </td>
      <td>
        <strong>{formatOneIn(tier.currentOneIn)}</strong>
        <small>
          {tier.confidenceLabel ? `${formatTierSample(tier.confidenceLabel)} · ` : ""}
          uses estimated ticket supply
        </small>
      </td>
      <td>
        <strong>{formatOneIn(tier.launchOneIn)}</strong>
        <small>Baseline from the starting prize structure</small>
      </td>
    </tr>
  );
}

function currentCountExplanation(tier: GamePrizeTier): string {
  if (tier.adjustmentStatus === "applied") {
    return `${formatEstimatedCount(tier.estimatedPendingCount)} estimated pending · ${tier.lagDaysUsed ?? 24}-day working assumption`;
  }
  if (tier.adjustmentStatus === "reference_unavailable") {
    return "Official count used · 24-day comparison unavailable";
  }
  if (tier.prizeAmount > 600 && tier.originalCount < 300) {
    return "Official count used · fewer than 300 starting prizes";
  }
  return "Official count used · claim-delay adjustment does not apply";
}

function formatTierSample(confidence: GamePrizeTier["confidenceLabel"]): string {
  if (confidence === "lumpy") return "Very small prize sample";
  if (confidence === "low") return "Small prize sample";
  if (confidence === "high") return "Larger prize sample";
  return "Medium prize sample";
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatEstimatedCount(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function formatWholeEstimate(value: number | null): string {
  return value === null ? "Unavailable" : `About ${formatInteger(Math.round(value))}`;
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
