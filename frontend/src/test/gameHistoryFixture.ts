import type { GameHistory } from "../types/gameHistory";

export const gameHistoryFixture: GameHistory = {
  generatedAt: "2026-08-10T20:00:00Z",
  sourceObservedAt: "2026-08-10T19:44:20Z",
  modelVersion: "2.0.0",
  gameId: 102,
  gameNumber: "DEMO-102",
  gameName: "Lakefront 10X",
  salesPoints: [
    {
      observedAt: "2026-05-10T19:44:20Z",
      estimatedOriginalTickets: 5_000_000,
      estimatedSoldTickets: 1_100_000,
      estimatedRemainingTickets: 3_900_000,
      segment: 0,
    },
    {
      observedAt: "2026-06-10T19:44:20Z",
      estimatedOriginalTickets: 5_000_000,
      estimatedSoldTickets: 1_650_000,
      estimatedRemainingTickets: 3_350_000,
      segment: 0,
    },
    {
      observedAt: "2026-07-10T19:44:20Z",
      estimatedOriginalTickets: 5_000_000,
      estimatedSoldTickets: 2_100_000,
      estimatedRemainingTickets: 2_900_000,
      segment: 0,
    },
    {
      observedAt: "2026-08-10T19:44:20Z",
      estimatedOriginalTickets: 5_000_000,
      estimatedSoldTickets: 2_750_000,
      estimatedRemainingTickets: 2_250_000,
      segment: 0,
    },
  ],
  tierSeries: [
    {
      prizeAmount: 500_000,
      points: tierPoints(5, [1, 2, 2, 3]),
    },
    {
      prizeAmount: 1_000,
      points: tierPoints(400, [70, 130, 190, 250]),
    },
    {
      prizeAmount: 100,
      points: tierPoints(4_000, [700, 1_300, 1_900, 2_500]),
    },
    {
      prizeAmount: 10,
      points: tierPoints(500_000, [80_000, 145_000, 210_000, 275_000]),
    },
  ],
};

function tierPoints(originalCount: number, claimedCounts: number[]) {
  const dates = [
    "2026-05-10T19:44:20Z",
    "2026-06-10T19:44:20Z",
    "2026-07-10T19:44:20Z",
    "2026-08-10T19:44:20Z",
  ];
  return claimedCounts.map((claimedCount, index) => ({
    observedAt: dates[index]!,
    originalCount,
    claimedCount,
    remainingCount: originalCount - claimedCount,
    claimedFraction: claimedCount / originalCount,
    segment: 0,
  }));
}
