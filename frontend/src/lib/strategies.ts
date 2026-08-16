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
    label: "Best value without relying on the jackpot",
    question: "Which tickets give me the best value without relying on the jackpot?",
    explanation:
      "Ranks estimated long-run prize return after removing each game's largest prize tier, while keeping the all-prize result visible.",
    metricLabel: "Estimated return without the top prize",
    kind: "ratio",
  },
  {
    key: "value_full",
    shortLabel: "Overall value",
    label: "Best value when every prize is included",
    question: "Which tickets give me the best value when every prize is included?",
    explanation:
      "Ranks estimated long-run prize return from every available prize tier, including the jackpot.",
    metricLabel: "Estimated return including all prizes",
    kind: "ratio",
  },
  {
    key: "any_win",
    shortLabel: "Best chance of winning",
    label: "Chance of winning any prize",
    question: "Which tickets give me the best chance of winning any prize?",
    explanation:
      "Ranks the estimated chance of winning the ticket cost or more. Illinois games in the current data have no below-cost prize tiers.",
    metricLabel: "Estimated chance of any prize",
    kind: "probability",
  },
  {
    key: "profit_full",
    shortLabel: "Best chance of profit",
    label: "Chance of winning more than the ticket costs",
    question: "Which tickets give me the best chance of winning more than they cost?",
    explanation:
      "Ranks the estimated chance of a prize greater than the ticket price, including the jackpot; the non-jackpot chance stays visible.",
    metricLabel: "Estimated chance of a profit",
    kind: "probability",
  },
  {
    key: "moderate_10x_full",
    shortLabel: "10× upside",
    label: "Chance of winning at least 10× the ticket price",
    question: "Which tickets give me the best chance of winning at least 10× the price?",
    explanation:
      "Ranks every prize worth at least ten times the ticket price, including the jackpot; the non-jackpot chance stays visible.",
    metricLabel: "Estimated chance of 10× or more",
    kind: "probability",
  },
  {
    key: "jackpot_top_odds",
    shortLabel: "Jackpot chase",
    label: "Chance of winning the top prize",
    question: "Which tickets give me the best chance of winning the top prize?",
    explanation:
      "Compares estimated top-prize chances while keeping the official remaining count visible.",
    metricLabel: "Estimated chance of the top prize",
    kind: "probability",
  },
] as const;

export const DEFAULT_STRATEGY: StrategyKey = "value_ex_top";

const EX_TOP_EV_STRATEGIES = new Set<StrategyKey>([
  "value_ex_top",
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
  return `1 in ${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: value < 100 ? 2 : value < 1_000 ? 1 : 0,
  }).format(value)}`;
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

export function formatCentsPerDollar(value: number): string {
  const cents = Math.max(0, value * 100);
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: cents < 1 ? 2 : 1,
  }).format(cents);
  return `About ${formatted}¢ in prizes per $1 over the long run`;
}

export function formatLongRunReturn(
  value: number | null,
  ticketPrice: number,
): string {
  if (value === null) return "Unavailable";
  const price = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(ticketPrice);
  return `${formatMoney(value)} per ${price} ticket over the long run`;
}

export function formatRelativeToLaunch(value: number | null): string {
  if (value === null) return "No launch comparison";
  const change = value - 1;
  if (Math.abs(change) < 0.0005) return "About the same as at launch";
  const formatted = new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(Math.abs(change));
  return `${formatted} ${change > 0 ? "higher" : "lower"} than at launch`;
}

export function getSupportingEv(record: RankingRecord): {
  label: string;
  value: number | null;
} {
  if (EX_TOP_EV_STRATEGIES.has(record.strategyKey)) {
    return {
      label: "Est. return, all prizes",
      value: record.estimatedEvFull,
    };
  }
  if (record.strategyKey === "value_full") {
    return {
      label: "Est. return, without top prize",
      value: record.estimatedEvExTop,
    };
  }
  return {
    label: "Est. return, all prizes",
    value: record.estimatedEvFull,
  };
}
