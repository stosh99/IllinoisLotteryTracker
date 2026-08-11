export const STRATEGY_KEYS = [
  "money_back_exact",
  "profit_ex_top",
  "value_full",
  "value_ex_top",
  "moderate_5x",
  "moderate_10x",
  "jackpot_top_odds",
  "large_1000",
  "large_100000",
] as const;

export type StrategyKey = (typeof STRATEGY_KEYS)[number];

export type MetricStatus =
  | "complete"
  | "partial"
  | "unavailable"
  | "not_applicable";

export type ConfidenceLabel = "lumpy" | "low" | "moderate" | "high";

export type RankingReasonCode =
  | "AVAILABLE"
  | "ANALYTICS_MODEL_UNAVAILABLE"
  | "SOURCE_UNAVAILABLE"
  | "CATALOG_UNAVAILABLE"
  | "SOURCE_STALE"
  | "CATALOG_STALE"
  | "ANALYTICS_UNAVAILABLE";

export type DataMode = "live";

export interface RankingStatus {
  available: boolean;
  reasonCode: RankingReasonCode;
  sourceObservedAt: string | null;
  catalogObservedAt: string | null;
  modelVersion: string | null;
  sourceRunId: number | null;
  catalogRunId: number | null;
  analyticsRunId: number | null;
}

export interface RankingRecord {
  analyticsRunId: number;
  gameId: number;
  gameNumber: string;
  gameName: string;
  ticketPrice: number;
  strategyKey: StrategyKey;
  metricValue: number;
  oneInValue: number | null;
  launchMetricValue: number | null;
  relativeToLaunch: number | null;
  targetTierCount: number;
  targetCountCoverage: number;
  targetValueCoverage: number;
  metricStatus: MetricStatus;
  lowestConfidence: ConfidenceLabel;
  containsLumpyTier: boolean;
  sourceObservedAt: string;
  catalogObservedAt: string;
  modelVersion: string;
  rankOverall: number;
  rankWithinTicketPrice: number;
  estimatedEvFull: number | null;
  estimatedEvExTop: number | null;
  topPrizeAmount: number | null;
  topPrizesOriginal: number | null;
  topPrizesRemaining: number | null;
  weeksInMarket: number | null;
}

export interface RankingDataset {
  generatedAt: string;
  mode: DataMode;
  status: RankingStatus;
  rankings: RankingRecord[];
}

export type TicketPriceFilter = "all" | number;

export interface RankingViewState {
  strategy: StrategyKey;
  ticketPrice: TicketPriceFilter;
}
