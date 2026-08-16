import type {
  GameOutcomeMetric,
  OutcomeKey,
  OutcomeMetricStatus,
} from "../types/gameDetails";

export type OutcomeLane = "primary" | "supporting" | "jackpot";

export interface OutcomeDefinition {
  key: OutcomeKey;
  label: string;
  definition: string;
  lane: OutcomeLane;
  depth: number;
}

export interface OutcomeRow extends OutcomeDefinition {
  probability: number | null;
  oneIn: number | null;
  metricStatus: OutcomeMetricStatus;
  available: boolean;
  relativeWidth: number;
}

export const OUTCOME_DEFINITIONS: readonly OutcomeDefinition[] = [
  {
    key: "any_win",
    label: "Win any prize",
    definition: "Win the ticket price or more.",
    lane: "primary",
    depth: 0,
  },
  {
    key: "profit_full",
    label: "Make a profit",
    definition: "Win more than the ticket price, including the jackpot.",
    lane: "primary",
    depth: 0,
  },
  {
    key: "profit_ex_top",
    label: "Profit without the jackpot",
    definition: "Win more than the ticket price from any non-jackpot tier.",
    lane: "supporting",
    depth: 0,
  },
  {
    key: "moderate_10x_full",
    label: "Win at least 10×",
    definition: "Win at least ten times the ticket price, including the jackpot.",
    lane: "primary",
    depth: 0,
  },
  {
    key: "moderate_10x_ex_top",
    label: "10× without the jackpot",
    definition: "Win at least ten times the ticket price from a non-jackpot tier.",
    lane: "supporting",
    depth: 0,
  },
  {
    key: "jackpot_top_odds",
    label: "Top prize",
    definition: "The game’s highest prize tier, shown separately.",
    lane: "jackpot",
    depth: 0,
  },
] as const;

export function buildOutcomeRows(metrics: GameOutcomeMetric[]): OutcomeRow[] {
  const byKey = new Map(metrics.map((metric) => [metric.outcomeKey, metric]));
  const maximumPrimaryProbability = OUTCOME_DEFINITIONS
    .filter(({ lane }) => lane === "primary")
    .reduce((maximum, { key }) => {
      const metric = byKey.get(key);
      return isCompleteMetric(metric)
        ? Math.max(maximum, metric.probability)
        : maximum;
    }, 0);

  return OUTCOME_DEFINITIONS.map((definition) => {
    const metric = byKey.get(definition.key);
    const available = isCompleteMetric(metric);
    const probability = available ? metric.probability : null;
    return {
      ...definition,
      probability,
      oneIn: available ? metric.oneIn : null,
      metricStatus: metric?.metricStatus ?? "unavailable",
      available,
      relativeWidth:
        available &&
        probability !== null &&
        definition.lane === "primary" &&
        maximumPrimaryProbability > 0
          ? Math.max(2, Math.min(100, (probability / maximumPrimaryProbability) * 100))
          : 0,
    };
  });
}

export function formatOutcomeProbability(probability: number | null): string {
  if (probability === null || !Number.isFinite(probability) || probability < 0) {
    return "Unavailable";
  }
  const percentage = probability * 100;
  const maximumFractionDigits =
    percentage >= 10
      ? 1
      : percentage >= 1
        ? 2
        : percentage >= 0.1
          ? 3
          : percentage >= 0.01
            ? 4
            : 5;
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits,
  }).format(probability);
}

function isCompleteMetric(
  metric: GameOutcomeMetric | undefined,
): metric is GameOutcomeMetric & { probability: number; oneIn: number } {
  return Boolean(
    metric &&
      metric.metricStatus === "complete" &&
      metric.probability !== null &&
      Number.isFinite(metric.probability) &&
      metric.probability >= 0 &&
      metric.oneIn !== null &&
      Number.isFinite(metric.oneIn) &&
      metric.oneIn > 0,
  );
}
