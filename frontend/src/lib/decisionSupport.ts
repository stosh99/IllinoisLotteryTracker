import { formatMetric, formatOneIn } from "./strategies";
import type { RankingRecord, StrategyKey } from "../types/rankings";

export interface RankExplanation {
  heading: string;
  basis: string;
  comparison: string;
}

export interface JackpotDependence {
  fullReturnPerDollar: number;
  nonTopReturnPerDollar: number;
  topContributionPerDollar: number;
  nonTopShare: number;
  topShare: number;
}

const RETURN_STRATEGIES = new Set<StrategyKey>(["value_ex_top", "value_full"]);
const ROUNDING_TOLERANCE = 0.005;

export function explainRank(
  record: RankingRecord,
  rankings: RankingRecord[],
  filteredByPrice: boolean,
): RankExplanation {
  const rank = displayRank(record, filteredByPrice);
  const leaders = rankings.filter((candidate) => displayRank(candidate, filteredByPrice) === 1);
  const leader = leaders[0] ?? rankings[0] ?? null;
  const basis = `This view is ordered by ${rankingBasis(record.strategyKey)}.`;

  if (rank === 1) {
    return {
      heading: "Why rank #1",
      basis,
      comparison:
        leaders.length > 1
          ? "This game is tied for the strongest result among the games shown."
          : "This game has the strongest result among the games shown.",
    };
  }

  if (!leader) {
    return {
      heading: `Why rank #${rank}`,
      basis,
      comparison: "A leader comparison is unavailable for this view.",
    };
  }

  return {
    heading: `Why rank #${rank}`,
    basis,
    comparison: RETURN_STRATEGIES.has(record.strategyKey)
      ? returnGapCopy(record, leader)
      : probabilityComparisonCopy(record, leader),
  };
}

export function calculateJackpotDependence(
  ticketPrice: number,
  estimatedEvFull: number | null,
  estimatedEvExTop: number | null,
): JackpotDependence | null {
  if (
    !Number.isFinite(ticketPrice) ||
    ticketPrice <= 0 ||
    estimatedEvFull === null ||
    !Number.isFinite(estimatedEvFull) ||
    estimatedEvFull <= 0 ||
    estimatedEvExTop === null ||
    !Number.isFinite(estimatedEvExTop) ||
    estimatedEvExTop < 0 ||
    estimatedEvExTop > estimatedEvFull + ROUNDING_TOLERANCE
  ) {
    return null;
  }

  const normalizedExTop = Math.min(estimatedEvExTop, estimatedEvFull);
  const topContribution = estimatedEvFull - normalizedExTop;
  return {
    fullReturnPerDollar: estimatedEvFull / ticketPrice,
    nonTopReturnPerDollar: normalizedExTop / ticketPrice,
    topContributionPerDollar: topContribution / ticketPrice,
    nonTopShare: normalizedExTop / estimatedEvFull,
    topShare: topContribution / estimatedEvFull,
  };
}

export function formatCentsPerDollarValue(value: number): string {
  return `${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: value * 100 < 1 ? 2 : 1,
  }).format(value * 100)}¢ per $1`;
}

export function formatShare(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: value > 0 && value < 0.001 ? 2 : 1,
    maximumFractionDigits: value > 0 && value < 0.001 ? 3 : 1,
  }).format(value);
}

function displayRank(record: RankingRecord, filteredByPrice: boolean): number {
  return filteredByPrice ? record.rankWithinTicketPrice : record.rankOverall;
}

function rankingBasis(strategyKey: StrategyKey): string {
  switch (strategyKey) {
    case "value_ex_top":
      return "estimated return without the top prize";
    case "value_full":
      return "estimated return including all prizes";
    case "money_back_exact":
      return "the estimated chance of winning exactly the ticket price";
    case "moderate_10x":
      return "the estimated chance of winning at least 10×, excluding the top prize";
    case "jackpot_top_odds":
      return "the estimated chance of winning the top prize";
    default:
      return "the selected estimated measure";
  }
}

function returnGapCopy(record: RankingRecord, leader: RankingRecord): string {
  const gapInCents = Math.max(0, leader.metricValue - record.metricValue) * 100;
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: gapInCents < 0.1 ? 2 : 1,
  }).format(gapInCents);
  return `Its estimated return is about ${formatted}¢ per $1 below the leader in this view.`;
}

function probabilityComparisonCopy(record: RankingRecord, leader: RankingRecord): string {
  if (record.oneInValue !== null && leader.oneInValue !== null) {
    return `Its estimated chance is ${formatOneIn(record.oneInValue)}; the leader is ${formatOneIn(leader.oneInValue)}.`;
  }
  return `Its estimated chance is ${formatMetric(record)}; the leader is ${formatMetric(leader)}.`;
}
