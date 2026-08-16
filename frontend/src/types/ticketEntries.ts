export interface TicketEntry {
  id: string;
  gameId: number;
  gameNumber: string;
  gameName: string;
  ticketPrice: number;
  playedOn: string;
  ticketCount: number;
  amountSpent: number;
  amountWon: number;
  netResult: number;
  createdAt: string;
}

export interface TicketHistorySummary {
  entryCount: number;
  ticketCount: number;
  amountSpent: number;
  amountWon: number;
  netResult: number;
  returnPercentage: number | null;
}

export interface TicketHistory {
  summary: TicketHistorySummary;
  entries: TicketEntry[];
}

export interface CreateTicketEntry {
  gameId: number;
  playedOn: string;
  ticketCount: number;
  amountWon: number;
}
