import type {
  GameHistory,
  TicketSalesHistoryPoint,
  TierClaimHistoryPoint,
  TierClaimHistorySeries,
} from "../types/gameHistory";

export async function loadGameHistory(
  gameId: number,
  signal?: AbortSignal,
): Promise<GameHistory> {
  const response = await fetch(`/api/v1/games/${gameId}/history`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (response.status === 404) {
    throw new Error("Historical data is unavailable for this current game.");
  }
  if (!response.ok) {
    throw new Error(`Game-history request failed with HTTP ${response.status}.`);
  }
  const history = assertGameHistory(await response.json());
  if (history.gameId !== gameId) {
    throw contractError("gameId", "must match the requested game");
  }
  return history;
}

export function assertGameHistory(document: unknown): GameHistory {
  if (!isObject(document)) throw contractError("response", "must be an object");
  const sourceObservedAt = requiredTimestamp(document, "sourceObservedAt");
  const salesPoints = requiredArray(document, "salesPoints").map((point, index) =>
    parseSalesPoint(point, `salesPoints[${index}]`),
  );
  const tierSeries = requiredArray(document, "tierSeries").map((series, index) =>
    parseTierSeries(series, `tierSeries[${index}]`),
  );
  assertChronological(salesPoints, "salesPoints");
  for (const [index, series] of tierSeries.entries()) {
    assertChronological(series.points, `tierSeries[${index}].points`);
  }
  if (tierSeries.length === 0) throw contractError("tierSeries", "must not be empty");
  const cutoff = Date.parse(sourceObservedAt);
  if (salesPoints.some((point) => Date.parse(point.observedAt) > cutoff)) {
    throw contractError("salesPoints", "cannot extend beyond the published cutoff");
  }
  if (
    tierSeries.some((series) =>
      series.points.some((point) => Date.parse(point.observedAt) > cutoff),
    )
  ) {
    throw contractError("tierSeries", "cannot extend beyond the published cutoff");
  }
  return {
    generatedAt: requiredTimestamp(document, "generatedAt"),
    sourceObservedAt,
    modelVersion: requiredString(document, "modelVersion"),
    gameId: requiredInteger(document, "gameId", 1),
    gameNumber: requiredString(document, "gameNumber"),
    gameName: requiredString(document, "gameName"),
    salesPoints,
    tierSeries,
  };
}

function parseSalesPoint(document: unknown, path: string): TicketSalesHistoryPoint {
  if (!isObject(document)) throw contractError(path, "must be an object");
  const original = requiredNumber(document, "estimatedOriginalTickets", 0, path);
  const sold = requiredNumber(document, "estimatedSoldTickets", 0, path);
  const remaining = requiredNumber(document, "estimatedRemainingTickets", 0, path);
  if (Math.abs(original - sold - remaining) > 0.11) {
    throw contractError(path, "ticket estimates must reconcile");
  }
  return {
    observedAt: requiredTimestamp(document, "observedAt", path),
    estimatedOriginalTickets: original,
    estimatedSoldTickets: sold,
    estimatedRemainingTickets: remaining,
    segment: requiredInteger(document, "segment", 0, path),
  };
}

function parseTierSeries(document: unknown, path: string): TierClaimHistorySeries {
  if (!isObject(document)) throw contractError(path, "must be an object");
  const points = requiredArray(document, "points", path).map((point, index) =>
    parseTierPoint(point, `${path}.points[${index}]`),
  );
  if (points.length === 0) throw contractError(`${path}.points`, "must not be empty");
  return {
    prizeAmount: requiredNumber(document, "prizeAmount", 0, path, false),
    points,
  };
}

function parseTierPoint(document: unknown, path: string): TierClaimHistoryPoint {
  if (!isObject(document)) throw contractError(path, "must be an object");
  const original = requiredInteger(document, "originalCount", 0, path);
  const claimed = requiredInteger(document, "claimedCount", 0, path);
  const remaining = requiredInteger(document, "remainingCount", 0, path);
  const fraction = optionalNumber(document, "claimedFraction", 0, path, true, 1);
  if (claimed !== original - remaining) {
    throw contractError(path, "claimed and remaining counts must reconcile");
  }
  const expectedFraction = original === 0 ? null : claimed / original;
  if (
    (expectedFraction === null) !== (fraction === null) ||
    (expectedFraction !== null && fraction !== null && Math.abs(expectedFraction - fraction) > 1e-9)
  ) {
    throw contractError(path, "claimed fraction must match official counts");
  }
  return {
    observedAt: requiredTimestamp(document, "observedAt", path),
    originalCount: original,
    claimedCount: claimed,
    remainingCount: remaining,
    claimedFraction: fraction,
    segment: requiredInteger(document, "segment", 0, path),
  };
}

function assertChronological(
  points: Array<{ observedAt: string; segment: number }>,
  path: string,
): void {
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1]!;
    const current = points[index]!;
    if (Date.parse(current.observedAt) < Date.parse(previous.observedAt)) {
      throw contractError(path, "must be chronological");
    }
    if (current.segment < previous.segment) {
      throw contractError(path, "segments must be monotonic");
    }
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredArray(
  object: Record<string, unknown>,
  key: string,
  path = "response",
): unknown[] {
  const value = object[key];
  if (!Array.isArray(value)) throw contractError(`${path}.${key}`, "must be an array");
  return value;
}

function requiredString(
  object: Record<string, unknown>,
  key: string,
  path = "response",
): string {
  const value = object[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw contractError(`${path}.${key}`, "must be a non-empty string");
  }
  return value;
}

function requiredTimestamp(
  object: Record<string, unknown>,
  key: string,
  path = "response",
): string {
  const value = requiredString(object, key, path);
  if (Number.isNaN(Date.parse(value))) {
    throw contractError(`${path}.${key}`, "must be a valid timestamp");
  }
  return value;
}

function requiredNumber(
  object: Record<string, unknown>,
  key: string,
  minimum: number,
  path: string,
  inclusive = true,
  maximum?: number,
): number {
  const value = object[key];
  const validMinimum = inclusive ? (value as number) >= minimum : (value as number) > minimum;
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    !validMinimum ||
    (maximum !== undefined && value > maximum)
  ) {
    throw contractError(`${path}.${key}`, "must be a finite number in range");
  }
  return value;
}

function optionalNumber(
  object: Record<string, unknown>,
  key: string,
  minimum: number,
  path: string,
  inclusive = true,
  maximum?: number,
): number | null {
  if (object[key] === null) return null;
  return requiredNumber(object, key, minimum, path, inclusive, maximum);
}

function requiredInteger(
  object: Record<string, unknown>,
  key: string,
  minimum: number,
  path = "response",
): number {
  const value = object[key];
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw contractError(`${path}.${key}`, `must be an integer >= ${minimum}`);
  }
  return value as number;
}

function contractError(path: string, detail: string): Error {
  return new Error(`Invalid game-history response: ${path} ${detail}.`);
}
