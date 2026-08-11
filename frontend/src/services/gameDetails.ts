import type {
  AdjustmentStatus,
  GameDetail,
  GameOutcomeMetric,
  GamePrizeTier,
  OutcomeKey,
  OutcomeMetricStatus,
  TierStatus,
} from "../types/gameDetails";
import { OUTCOME_KEYS } from "../types/gameDetails";
import type { ConfidenceLabel } from "../types/rankings";

const adjustmentStatuses = new Set<AdjustmentStatus>([
  "applied",
  "reported_only",
  "reference_unavailable",
]);
const tierStatuses = new Set<TierStatus>(["available", "depleted", "unavailable"]);
const confidenceLabels = new Set<ConfidenceLabel>([
  "lumpy",
  "low",
  "moderate",
  "high",
]);
const outcomeKeys = new Set<OutcomeKey>(OUTCOME_KEYS);
const outcomeMetricStatuses = new Set<OutcomeMetricStatus>([
  "complete",
  "partial",
  "unavailable",
  "not_applicable",
]);

export async function loadGameDetail(
  gameId: number,
  signal?: AbortSignal,
): Promise<GameDetail> {
  const response = await fetch(`/api/v1/games/${gameId}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (response.status === 404) {
    throw new Error("This game is not part of the current published comparison.");
  }
  if (!response.ok) {
    throw new Error(`Game-detail request failed with HTTP ${response.status}.`);
  }
  const detail = assertGameDetail(await response.json());
  if (detail.gameId !== gameId) {
    throw contractError("gameId", "must match the requested game");
  }
  return detail;
}

export function assertGameDetail(document: unknown): GameDetail {
  if (!isObject(document)) throw contractError("response", "must be an object");
  const tiers = requiredArray(document, "tiers").map((tier, index) =>
    parseTier(tier, `tiers[${index}]`),
  );
  const outcomes = requiredArray(document, "outcomes").map((outcome, index) =>
    parseOutcome(outcome, `outcomes[${index}]`),
  );
  if (tiers.length === 0) throw contractError("tiers", "must not be empty");
  assertCompleteOutcomeSet(outcomes);
  return {
    generatedAt: requiredTimestamp(document, "generatedAt"),
    sourceObservedAt: requiredTimestamp(document, "sourceObservedAt"),
    catalogObservedAt: requiredTimestamp(document, "catalogObservedAt"),
    analyticsRunId: requiredInteger(document, "analyticsRunId", 1),
    modelVersion: requiredString(document, "modelVersion"),
    gameId: requiredInteger(document, "gameId", 1),
    gameNumber: requiredString(document, "gameNumber"),
    gameName: requiredString(document, "gameName"),
    ticketPrice: requiredNumber(document, "ticketPrice", 0, false),
    launchDate: optionalDate(document, "launchDate"),
    weeksInMarket: optionalInteger(document, "weeksInMarket", 0),
    publishedOverallOddsOneIn: optionalNumber(
      document,
      "publishedOverallOddsOneIn",
      1,
      false,
    ),
    estimatedOriginalTickets: optionalNumber(document, "estimatedOriginalTickets", 0),
    estimatedSoldTickets: optionalNumber(document, "estimatedSoldTickets", 0),
    estimatedRemainingTickets: optionalNumber(document, "estimatedRemainingTickets", 0),
    estimatedEvFull: optionalNumber(document, "estimatedEvFull", 0),
    estimatedEvExTop: optionalNumber(document, "estimatedEvExTop", 0),
    topPrizeAmount: optionalNumber(document, "topPrizeAmount", 0),
    topPrizesOriginal: optionalInteger(document, "topPrizesOriginal", 0),
    topPrizesRemaining: optionalInteger(document, "topPrizesRemaining", 0),
    outcomes,
    tiers,
  };
}

function parseOutcome(document: unknown, path: string): GameOutcomeMetric {
  if (!isObject(document)) throw contractError(path, "must be an object");
  return {
    outcomeKey: requiredEnum(document, "outcomeKey", outcomeKeys, path),
    probability: optionalNumber(document, "probability", 0, true, path),
    oneIn: optionalNumber(document, "oneIn", 0, false, path),
    metricStatus: requiredEnum(
      document,
      "metricStatus",
      outcomeMetricStatuses,
      path,
    ),
  };
}

function assertCompleteOutcomeSet(outcomes: GameOutcomeMetric[]): void {
  const observed = new Set(outcomes.map(({ outcomeKey }) => outcomeKey));
  if (outcomes.length !== OUTCOME_KEYS.length || observed.size !== OUTCOME_KEYS.length) {
    throw contractError("outcomes", "must contain each supported outcome exactly once");
  }
  for (const key of OUTCOME_KEYS) {
    if (!observed.has(key)) {
      throw contractError("outcomes", `is missing ${key}`);
    }
  }
}

function parseTier(document: unknown, path: string): GamePrizeTier {
  if (!isObject(document)) throw contractError(path, "must be an object");
  const originalCount = requiredInteger(document, "originalCount", 0, path);
  const claimedCount = requiredInteger(document, "claimedCount", 0, path);
  const reportedRemainingCount = requiredInteger(
    document,
    "reportedRemainingCount",
    0,
    path,
  );
  const estimatedPendingCount = requiredNumber(
    document,
    "estimatedPendingCount",
    0,
    true,
    path,
  );
  const estimatedRemainingCount = requiredNumber(
    document,
    "estimatedRemainingCount",
    0,
    true,
    path,
  );
  if (claimedCount !== originalCount - reportedRemainingCount) {
    throw contractError(path, "claimed and remaining counts must reconcile");
  }
  if (
    estimatedPendingCount > reportedRemainingCount ||
    estimatedRemainingCount > reportedRemainingCount
  ) {
    throw contractError(path, "estimated counts cannot exceed the official remainder");
  }
  return {
    prizeAmount: requiredNumber(document, "prizeAmount", 0, false, path),
    isTopPrize: requiredBoolean(document, "isTopPrize", path),
    originalCount,
    claimedCount,
    reportedRemainingCount,
    estimatedPendingCount,
    estimatedRemainingCount,
    adjustmentStatus: requiredEnum(
      document,
      "adjustmentStatus",
      adjustmentStatuses,
      path,
    ),
    lagDaysUsed: optionalInteger(document, "lagDaysUsed", 0, path),
    launchOneIn: optionalNumber(document, "launchOneIn", 0, false, path),
    currentOneIn: optionalNumber(document, "currentOneIn", 0, false, path),
    confidenceLabel: optionalEnum(
      document,
      "confidenceLabel",
      confidenceLabels,
      path,
    ),
    status: requiredEnum(document, "status", tierStatuses, path),
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredArray(object: Record<string, unknown>, key: string): unknown[] {
  const value = object[key];
  if (!Array.isArray(value)) throw contractError(key, "must be an array");
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

function requiredTimestamp(object: Record<string, unknown>, key: string): string {
  const value = requiredString(object, key);
  if (Number.isNaN(Date.parse(value))) {
    throw contractError(key, "must be a valid timestamp");
  }
  return value;
}

function optionalDate(object: Record<string, unknown>, key: string): string | null {
  const value = object[key];
  if (value === null) return null;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw contractError(key, "must be null or an ISO date");
  }
  return value;
}

function requiredBoolean(
  object: Record<string, unknown>,
  key: string,
  path: string,
): boolean {
  const value = object[key];
  if (typeof value !== "boolean") {
    throw contractError(`${path}.${key}`, "must be a boolean");
  }
  return value;
}

function requiredNumber(
  object: Record<string, unknown>,
  key: string,
  minimum: number,
  inclusive = true,
  path = "response",
): number {
  const value = object[key];
  const validMinimum = inclusive ? (value as number) >= minimum : (value as number) > minimum;
  if (typeof value !== "number" || !Number.isFinite(value) || !validMinimum) {
    throw contractError(`${path}.${key}`, "must be a valid nonnegative number");
  }
  return value;
}

function optionalNumber(
  object: Record<string, unknown>,
  key: string,
  minimum: number,
  inclusive = true,
  path = "response",
): number | null {
  if (object[key] === null) return null;
  return requiredNumber(object, key, minimum, inclusive, path);
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

function optionalInteger(
  object: Record<string, unknown>,
  key: string,
  minimum: number,
  path = "response",
): number | null {
  if (object[key] === null) return null;
  return requiredInteger(object, key, minimum, path);
}

function requiredEnum<T extends string>(
  object: Record<string, unknown>,
  key: string,
  values: ReadonlySet<T>,
  path: string,
): T {
  const value = object[key];
  if (typeof value !== "string" || !values.has(value as T)) {
    throw contractError(`${path}.${key}`, "has an unsupported value");
  }
  return value as T;
}

function optionalEnum<T extends string>(
  object: Record<string, unknown>,
  key: string,
  values: ReadonlySet<T>,
  path: string,
): T | null {
  if (object[key] === null) return null;
  return requiredEnum(object, key, values, path);
}

function contractError(path: string, detail: string): Error {
  return new Error(`Invalid game-detail response: ${path} ${detail}.`);
}
