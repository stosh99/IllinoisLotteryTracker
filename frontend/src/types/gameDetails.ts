import type { ConfidenceLabel } from "./rankings";

export const OUTCOME_KEYS = [
  "money_back_exact",
  "profit_ex_top",
  "moderate_5x",
  "moderate_10x",
  "jackpot_top_odds",
] as const;

export type OutcomeKey = (typeof OUTCOME_KEYS)[number];
export type OutcomeMetricStatus =
  | "complete"
  | "partial"
  | "unavailable"
  | "not_applicable";

export type AdjustmentStatus =
  | "applied"
  | "reported_only"
  | "reference_unavailable";

export type TierStatus = "available" | "depleted" | "unavailable";

export interface GamePrizeTier {
  prizeAmount: number;
  isTopPrize: boolean;
  originalCount: number;
  claimedCount: number;
  reportedRemainingCount: number;
  estimatedPendingCount: number;
  estimatedRemainingCount: number;
  adjustmentStatus: AdjustmentStatus;
  lagDaysUsed: number | null;
  launchOneIn: number | null;
  currentOneIn: number | null;
  confidenceLabel: ConfidenceLabel | null;
  status: TierStatus;
}

export interface GameOutcomeMetric {
  outcomeKey: OutcomeKey;
  probability: number | null;
  oneIn: number | null;
  metricStatus: OutcomeMetricStatus;
}

export interface GameDetail {
  generatedAt: string;
  sourceObservedAt: string;
  catalogObservedAt: string;
  analyticsRunId: number;
  modelVersion: string;
  gameId: number;
  gameNumber: string;
  gameName: string;
  ticketPrice: number;
  launchDate: string | null;
  weeksInMarket: number | null;
  publishedOverallOddsOneIn: number | null;
  estimatedOriginalTickets: number | null;
  estimatedSoldTickets: number | null;
  estimatedRemainingTickets: number | null;
  estimatedEvFull: number | null;
  estimatedEvExTop: number | null;
  topPrizeAmount: number | null;
  topPrizesOriginal: number | null;
  topPrizesRemaining: number | null;
  outcomes: GameOutcomeMetric[];
  tiers: GamePrizeTier[];
}
