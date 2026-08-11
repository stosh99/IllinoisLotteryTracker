import type { RankingRecord, StrategyKey } from "../types/rankings";

export interface StrategyDefinition {
  key: StrategyKey;
  shortLabel: string;
  label: string;
  question: string;
  explanation: string;
  metricLabel: string;
  kind: "ratio" | "probability";
}

export const PRIMARY_STRATEGIES: readonly StrategyDefinition[] = [
  {
    key: "value_ex_top",
    shortLabel: "Practical value",
    label: "Value without the top prize",
    question: "What looks strongest without the jackpot doing all the work?",
    explanation:
      "Compares estimated payout ratio after removing each game's largest prize tier.",
    metricLabel: "Est. payout ratio, ex. top",
    kind: "ratio",
  },
  {
    key: "value_full",
    shortLabel: "Overall value",
    label: "Overall estimated value",
    question: "Which games retain the most estimated prize value per dollar?",
    explanation:
      "Includes every scored prize tier, including the top prize when the model can score it.",
    metricLabel: "Estimated payout ratio",
    kind: "ratio",
  },
  {
    key: "money_back_exact",
    shortLabel: "Money back",
    label: "Chance to get the ticket cost back",
    question: "Which games offer the strongest estimated break-even chance?",
    explanation:
      "Ranks the estimated probability of winning exactly the ticket price.",
    metricLabel: "Est. exact break-even chance",
    kind: "probability",
  },
  {
    key: "moderate_10x",
    shortLabel: "10× upside",
    label: "Moderate upside without the top prize",
    question: "Where does a meaningful, non-jackpot win appear most likely?",
    explanation:
      "Compares the estimated chance of winning at least 10× the ticket price, excluding the top tier.",
    metricLabel: "Est. chance of 10×+",
    kind: "probability",
  },
  {
    key: "jackpot_top_odds",
    shortLabel: "Jackpot chase",
    label: "Top-prize odds",
    question: "Which current top prize has the strongest estimated odds?",
    explanation:
      "Shows estimated top-prize probability beside raw remaining counts and confidence.",
    metricLabel: "Est. top-prize chance",
    kind: "probability",
  },
] as const;

export const DEFAULT_STRATEGY: StrategyKey = "value_ex_top";

const EX_TOP_EV_STRATEGIES = new Set<StrategyKey>([
  "profit_ex_top",
  "value_ex_top",
  "moderate_5x",
  "moderate_10x",
]);

export function getStrategy(key: StrategyKey): StrategyDefinition {
  return (
    PRIMARY_STRATEGIES.find((strategy) => strategy.key === key) ??
    PRIMARY_STRATEGIES[0]!
  );
}

export function formatMetric(record: RankingRecord): string {
  const strategy = getStrategy(record.strategyKey);
  const isSmallProbability =
    strategy.kind === "probability" && record.metricValue < 0.0001;
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: isSmallProbability
      ? 4
      : strategy.kind === "probability"
        ? 2
        : 1,
    maximumFractionDigits: isSmallProbability
      ? 5
      : strategy.kind === "probability"
        ? 3
        : 1,
  }).format(record.metricValue);
}

export function formatOneIn(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value <= 0) return "—";
  return `1 in ${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value)}`;
}

export function formatMoney(value: number | null, compact = false): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: compact && value >= 1_000 ? 0 : 2,
    notation: compact && value >= 1_000 ? "compact" : "standard",
  }).format(value);
}

export function formatRelativeToLaunch(value: number | null): string {
  if (value === null) return "No launch comparison";
  const change = value - 1;
  const formatted = new Intl.NumberFormat("en-US", {
    style: "percent",
    signDisplay: "always",
    maximumFractionDigits: 1,
  }).format(change);
  return `${formatted} vs. launch`;
}

export function getSupportingEv(record: RankingRecord): {
  label: string;
  value: number | null;
} {
  if (EX_TOP_EV_STRATEGIES.has(record.strategyKey)) {
    return {
      label: "Est. EV, ex. top",
      value: record.estimatedEvExTop,
    };
  }
  return {
    label: "Estimated EV, full",
    value: record.estimatedEvFull,
  };
}
