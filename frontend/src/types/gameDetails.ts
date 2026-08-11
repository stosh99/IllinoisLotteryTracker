import type { ConfidenceLabel } from "./rankings";

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
  tiers: GamePrizeTier[];
}
