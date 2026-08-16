import type {
  ConfidenceLabel,
  RankingDataset,
  RankingRecord,
  StrategyKey,
} from "../types/rankings";

interface FixtureMetric {
  value: number;
  launch: number;
  oneIn?: number;
  confidence?: ConfidenceLabel;
  containsLumpy?: boolean;
  targetTierCount?: number;
}

interface FixtureGame {
  id: number;
  number: string;
  name: string;
  price: number;
  topPrize: number;
  topOriginal: number;
  topRemaining: number;
  weeks: number;
  metrics: Record<StrategyKey, FixtureMetric>;
}

const observedAt = "2026-08-08T07:04:43Z";
const catalogAt = "2026-08-08T08:12:18Z";

const games: FixtureGame[] = [
  {
    id: 101,
    number: "DEMO-101",
    name: "Prairie Gold",
    price: 5,
    topPrize: 250_000,
    topOriginal: 6,
    topRemaining: 3,
    weeks: 14,
    metrics: metricSet(0.734, 0.692, 0.126, 0.0194, 710_000, "high"),
  },
  {
    id: 102,
    number: "DEMO-102",
    name: "Lakefront 10X",
    price: 10,
    topPrize: 500_000,
    topOriginal: 5,
    topRemaining: 2,
    weeks: 22,
    metrics: metricSet(0.742, 0.704, 0.111, 0.0228, 940_000, "moderate"),
  },
  {
    id: 103,
    number: "DEMO-103",
    name: "Route 66 Riches",
    price: 20,
    topPrize: 1_000_000,
    topOriginal: 8,
    topRemaining: 4,
    weeks: 31,
    metrics: metricSet(0.719, 0.701, 0.118, 0.0181, 620_000, "moderate"),
  },
  {
    id: 104,
    number: "DEMO-104",
    name: "Windy City Cash",
    price: 5,
    topPrize: 100_000,
    topOriginal: 6,
    topRemaining: 1,
    weeks: 38,
    metrics: metricSet(0.702, 0.681, 0.132, 0.0162, 1_200_000, "high"),
  },
  {
    id: 105,
    number: "DEMO-105",
    name: "Lincoln Lucky Lines",
    price: 10,
    topPrize: 300_000,
    topOriginal: 8,
    topRemaining: 5,
    weeks: 9,
    metrics: metricSet(0.705, 0.667, 0.104, 0.0241, 510_000, "low"),
  },
  {
    id: 106,
    number: "DEMO-106",
    name: "Great Lakes Vault",
    price: 30,
    topPrize: 2_000_000,
    topOriginal: 6,
    topRemaining: 2,
    weeks: 18,
    metrics: metricSet(0.752, 0.711, 0.098, 0.0207, 780_000, "moderate"),
  },
  {
    id: 107,
    number: "DEMO-107",
    name: "State Street Stacks",
    price: 20,
    topPrize: 750_000,
    topOriginal: 6,
    topRemaining: 2,
    weeks: 43,
    metrics: metricSet(0.694, 0.676, 0.121, 0.0154, 880_000, "high"),
  },
  {
    id: 108,
    number: "DEMO-108",
    name: "Midwest Money Match",
    price: 50,
    topPrize: 5_000_000,
    topOriginal: 5,
    topRemaining: 3,
    weeks: 27,
    metrics: metricSet(0.759, 0.716, 0.093, 0.0215, 450_000, "lumpy"),
  },
];

function metricSet(
  valueFull: number,
  valueExTop: number,
  anyWin: number,
  moderate10x: number,
  topOneIn: number,
  topConfidence: ConfidenceLabel,
): Record<StrategyKey, FixtureMetric> {
  const topProbability = 1 / topOneIn;
  const profitExTop = anyWin * 0.77;
  const profitFull = profitExTop + topProbability;
  const moderate10xFull = moderate10x + topProbability;
  return {
    any_win: {
      value: anyWin,
      launch: anyWin * 0.96,
      oneIn: 1 / anyWin,
      confidence: "high",
      targetTierCount: 9,
    },
    profit_full: {
      value: profitFull,
      launch: profitFull * 0.97,
      oneIn: 1 / profitFull,
      confidence: "high",
      targetTierCount: 9,
    },
    value_full: {
      value: valueFull,
      launch: valueFull * 0.97,
      confidence: topConfidence,
      containsLumpy: topConfidence === "lumpy",
      targetTierCount: 12,
    },
    value_ex_top: {
      value: valueExTop,
      launch: valueExTop * 0.985,
      confidence: "moderate",
      targetTierCount: 11,
    },
    moderate_10x_full: {
      value: moderate10xFull,
      launch: moderate10xFull * 0.95,
      oneIn: 1 / moderate10xFull,
      confidence: "moderate",
      targetTierCount: 6,
    },
    jackpot_top_odds: {
      value: topProbability,
      launch: topProbability * 0.92,
      oneIn: topOneIn,
      confidence: topConfidence,
      containsLumpy: true,
      targetTierCount: 1,
    },
  };
}

function buildRecords(): RankingRecord[] {
  const records: RankingRecord[] = [];
  const keys = Object.keys(games[0]?.metrics ?? {}) as StrategyKey[];

  for (const strategyKey of keys) {
    const ordered = [...games].sort(
      (left, right) =>
        right.metrics[strategyKey].value - left.metrics[strategyKey].value ||
        left.number.localeCompare(right.number),
    );
    const valueRanks = denseRanks(ordered.map((game) => game.metrics[strategyKey].value));

    ordered.forEach((game, index) => {
      const metric = game.metrics[strategyKey];
      const pricePeers = ordered.filter((peer) => peer.price === game.price);
      const priceIndex = pricePeers.findIndex((peer) => peer.id === game.id);
      const priceRank =
        denseRanks(pricePeers.map((peer) => peer.metrics[strategyKey].value))[
          priceIndex
        ] ?? priceIndex + 1;
      records.push({
        analyticsRunId: 9001,
        gameId: game.id,
        gameNumber: game.number,
        gameName: game.name,
        ticketPrice: game.price,
        strategyKey,
        metricValue: metric.value,
        oneInValue: metric.oneIn ?? null,
        launchMetricValue: metric.launch,
        relativeToLaunch: metric.launch > 0 ? metric.value / metric.launch : null,
        targetTierCount: metric.targetTierCount ?? 1,
        targetCountCoverage: 1,
        targetValueCoverage: 1,
        metricStatus: "complete",
        lowestConfidence: metric.confidence ?? "moderate",
        containsLumpyTier: metric.containsLumpy ?? false,
        sourceObservedAt: observedAt,
        catalogObservedAt: catalogAt,
        modelVersion: "test-1.0.0",
        rankOverall: valueRanks[index] ?? index + 1,
        rankWithinTicketPrice: priceRank,
        estimatedEvFull: game.metrics.value_full.value * game.price,
        estimatedEvExTop: game.metrics.value_ex_top.value * game.price,
        topPrizeAmount: game.topPrize,
        topPrizesOriginal: game.topOriginal,
        topPrizesRemaining: game.topRemaining,
        weeksInMarket: game.weeks,
        profitExTopProbability: game.metrics.any_win.value * 0.77,
        oneInProfitExTop: 1 / (game.metrics.any_win.value * 0.77),
        tenXExTopProbability:
          game.metrics.moderate_10x_full.value - 1 / game.metrics.jackpot_top_odds.oneIn!,
        oneInTenXExTop:
          1 /
          (game.metrics.moderate_10x_full.value -
            1 / game.metrics.jackpot_top_odds.oneIn!),
      });
    });
  }
  return records;
}

function denseRanks(values: number[]): number[] {
  let rank = 0;
  let previous: number | undefined;
  return values.map((value) => {
    if (previous === undefined || value !== previous) {
      rank += 1;
      previous = value;
    }
    return rank;
  });
}

export const rankingDatasetFixture: RankingDataset = {
  generatedAt: "2026-08-08T12:00:00Z",
  mode: "live",
  status: {
    available: true,
    reasonCode: "AVAILABLE",
    sourceObservedAt: observedAt,
    catalogObservedAt: catalogAt,
    modelVersion: "test-1.0.0",
    sourceRunId: 9001,
    catalogRunId: 9002,
    analyticsRunId: 9001,
  },
  rankings: buildRecords(),
};
