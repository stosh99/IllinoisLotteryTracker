export interface TicketSalesHistoryPoint {
  observedAt: string;
  estimatedOriginalTickets: number;
  estimatedSoldTickets: number;
  estimatedRemainingTickets: number;
  segment: number;
}

export interface TierClaimHistoryPoint {
  observedAt: string;
  originalCount: number;
  claimedCount: number;
  remainingCount: number;
  claimedFraction: number | null;
  segment: number;
}

export interface TierClaimHistorySeries {
  prizeAmount: number;
  points: TierClaimHistoryPoint[];
}

export interface GameHistory {
  generatedAt: string;
  sourceObservedAt: string;
  modelVersion: string;
  gameId: number;
  gameNumber: string;
  gameName: string;
  salesPoints: TicketSalesHistoryPoint[];
  tierSeries: TierClaimHistorySeries[];
}
