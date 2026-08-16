import type {
  CreateTicketEntry,
  TicketEntry,
  TicketHistory,
  TicketHistorySummary,
} from "../types/ticketEntries";

const ROOT = "/api/v1/ticket-entries";

export class TicketHistoryError extends Error {
  constructor(readonly status: number) {
    super("Ticket history request failed");
    this.name = "TicketHistoryError";
  }
}

async function request(path = "", init: RequestInit = {}): Promise<Response> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok) throw new TicketHistoryError(response.status);
  return response;
}

export async function loadTicketHistory(signal?: AbortSignal): Promise<TicketHistory> {
  const response = await request("", { signal });
  return parseHistory(await response.json());
}

export async function createTicketEntry(
  values: CreateTicketEntry,
  csrfToken: string,
): Promise<TicketEntry> {
  const response = await request("", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(values),
  });
  return parseEntry(await response.json(), "entry");
}

export async function deleteTicketEntry(id: string, csrfToken: string): Promise<void> {
  await request(`/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  });
}

function parseHistory(value: unknown): TicketHistory {
  if (!isObject(value) || !isObject(value.summary) || !Array.isArray(value.entries)) {
    throw new TicketHistoryError(503);
  }
  return {
    summary: parseSummary(value.summary),
    entries: value.entries.map((entry, index) => parseEntry(entry, `entries[${index}]`)),
  };
}

function parseSummary(value: Record<string, unknown>): TicketHistorySummary {
  return {
    entryCount: integer(value.entryCount),
    ticketCount: integer(value.ticketCount),
    amountSpent: number(value.amountSpent),
    amountWon: number(value.amountWon),
    netResult: number(value.netResult),
    returnPercentage: value.returnPercentage === null ? null : number(value.returnPercentage),
  };
}

function parseEntry(value: unknown, _path: string): TicketEntry {
  if (!isObject(value)) throw new TicketHistoryError(503);
  const playedOn = string(value.playedOn);
  const createdAt = string(value.createdAt);
  if (Number.isNaN(Date.parse(`${playedOn}T00:00:00Z`)) || Number.isNaN(Date.parse(createdAt))) {
    throw new TicketHistoryError(503);
  }
  return {
    id: string(value.id),
    gameId: integer(value.gameId),
    gameNumber: string(value.gameNumber),
    gameName: string(value.gameName),
    ticketPrice: number(value.ticketPrice),
    playedOn,
    ticketCount: integer(value.ticketCount),
    amountSpent: number(value.amountSpent),
    amountWon: number(value.amountWon),
    netResult: number(value.netResult),
    createdAt,
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new TicketHistoryError(503);
  return value;
}

function integer(value: unknown): number {
  const parsed = number(value);
  if (!Number.isInteger(parsed)) throw new TicketHistoryError(503);
  return parsed;
}

function string(value: unknown): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 500) {
    throw new TicketHistoryError(503);
  }
  return value;
}
