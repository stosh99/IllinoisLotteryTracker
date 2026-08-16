import {
  STRATEGY_KEYS,
  type ConfidenceLabel,
  type DataMode,
  type MetricStatus,
  type RankingDataset,
  type RankingReasonCode,
  type RankingRecord,
  type RankingStatus,
  type StrategyKey,
} from "../types/rankings";

const configuredRankingsUrl = import.meta.env.VITE_RANKINGS_URL as string | undefined;
const rankingsUrl = configuredRankingsUrl?.trim() || "/api/v1/rankings";
const strategyKeys = new Set<string>(STRATEGY_KEYS);
const reasonCodes = new Set<RankingReasonCode>([
  "AVAILABLE",
  "ANALYTICS_MODEL_UNAVAILABLE",
  "SOURCE_UNAVAILABLE",
  "CATALOG_UNAVAILABLE",
  "SOURCE_STALE",
  "CATALOG_STALE",
  "ANALYTICS_UNAVAILABLE",
]);
const metricStatuses = new Set<MetricStatus>([
  "complete",
  "partial",
  "unavailable",
  "not_applicable",
]);
const confidenceLabels = new Set<ConfidenceLabel>([
  "lumpy",
  "low",
  "moderate",
  "high",
]);

export async function loadRankingDataset(
  signal?: AbortSignal,
): Promise<RankingDataset> {
  const response = await fetch(rankingsUrl, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Ranking request failed with HTTP ${response.status}.`);
  }
  const document: unknown = await response.json();
  return assertRankingDataset(document);
}

export function assertRankingDataset(document: unknown): RankingDataset {
  if (!isObject(document)) {
    throw new Error("Ranking response is not a JSON object.");
  }

  const mode = requiredEnum<DataMode>(
    document,
    "mode",
    new Set<DataMode>(["live"]),
  );
  const generatedAt = requiredTimestamp(document, "generatedAt");
  const status = parseRankingStatus(document.status);
  if (!Array.isArray(document.rankings)) {
    throw contractError("rankings", "must be an array");
  }

  const rankings = document.rankings.map((row, index) =>
    parseRankingRecord(row, `rankings[${index}]`),
  );
  if (!status.available && rankings.length > 0) {
    throw new Error("Unavailable ranking responses must not include ranking rows.");
  }
  if (status.available) {
    requireAvailableStatusEvidence(status);
  }
  for (const [index, row] of rankings.entries()) {
    assertRowMatchesStatus(row, status, index);
  }

  return { generatedAt, mode, status, rankings };
}

function parseRankingStatus(document: unknown): RankingStatus {
  if (!isObject(document)) {
    throw contractError("status", "must be an object");
  }
  const available = requiredBoolean(document, "available", "status");
  const reasonCode = requiredEnum<RankingReasonCode>(
    document,
    "reasonCode",
    reasonCodes,
    "status",
  );
  if (available !== (reasonCode === "AVAILABLE")) {
    throw contractError(
      "status",
      "available must be true exactly when reasonCode is AVAILABLE",
    );
  }

  return {
    available,
    reasonCode,
    sourceObservedAt: optionalTimestamp(document, "sourceObservedAt", "status"),
    catalogObservedAt: optionalTimestamp(document, "catalogObservedAt", "status"),
    modelVersion: optionalString(document, "modelVersion", "status"),
    sourceRunId: optionalInteger(document, "sourceRunId", "status", 1),
    catalogRunId: optionalInteger(document, "catalogRunId", "status", 1),
    analyticsRunId: optionalInteger(document, "analyticsRunId", "status", 1),
  };
}

function parseRankingRecord(document: unknown, path: string): RankingRecord {
  if (!isObject(document)) {
    throw contractError(path, "must be an object");
  }
  const metricStatus = requiredEnum<MetricStatus>(
    document,
    "metricStatus",
    metricStatuses,
    path,
  );
  if (metricStatus !== "complete") {
    throw contractError(`${path}.metricStatus`, "ranking rows must be complete");
  }

  return {
    analyticsRunId: requiredInteger(document, "analyticsRunId", path, 1),
    gameId: requiredInteger(document, "gameId", path, 1),
    gameNumber: requiredString(document, "gameNumber", path),
    gameName: requiredString(document, "gameName", path),
    ticketPrice: requiredNumber(document, "ticketPrice", path, 0, false),
    strategyKey: requiredEnum<StrategyKey>(
      document,
      "strategyKey",
      strategyKeys,
      path,
    ),
    metricValue: requiredNumber(document, "metricValue", path, 0),
    oneInValue: optionalNumber(document, "oneInValue", path, 0, false),
    launchMetricValue: optionalNumber(document, "launchMetricValue", path, 0),
    relativeToLaunch: optionalNumber(document, "relativeToLaunch", path, 0),
    targetTierCount: requiredInteger(document, "targetTierCount", path, 0),
    targetCountCoverage: requiredNumber(
      document,
      "targetCountCoverage",
      path,
      0,
      true,
      1,
    ),
    targetValueCoverage: requiredNumber(
      document,
      "targetValueCoverage",
      path,
      0,
      true,
      1,
    ),
    metricStatus,
    lowestConfidence: requiredEnum<ConfidenceLabel>(
      document,
      "lowestConfidence",
      confidenceLabels,
      path,
    ),
    containsLumpyTier: requiredBoolean(document, "containsLumpyTier", path),
    sourceObservedAt: requiredTimestamp(document, "sourceObservedAt", path),
    catalogObservedAt: requiredTimestamp(document, "catalogObservedAt", path),
    modelVersion: requiredString(document, "modelVersion", path),
    rankOverall: requiredInteger(document, "rankOverall", path, 1),
    rankWithinTicketPrice: requiredInteger(
      document,
      "rankWithinTicketPrice",
      path,
      1,
    ),
    estimatedEvFull: optionalNumber(document, "estimatedEvFull", path, 0),
    estimatedEvExTop: optionalNumber(document, "estimatedEvExTop", path, 0),
    topPrizeAmount: optionalNumber(document, "topPrizeAmount", path, 0),
    topPrizesOriginal: optionalInteger(
      document,
      "topPrizesOriginal",
      path,
      0,
    ),
    topPrizesRemaining: optionalInteger(
      document,
      "topPrizesRemaining",
      path,
      0,
    ),
    weeksInMarket: optionalInteger(document, "weeksInMarket", path, 0),
    profitExTopProbability: optionalNumber(
      document,
      "profitExTopProbability",
      path,
      0,
      true,
    ),
    oneInProfitExTop: optionalNumber(document, "oneInProfitExTop", path, 0, false),
    tenXExTopProbability: optionalNumber(
      document,
      "tenXExTopProbability",
      path,
      0,
      true,
    ),
    oneInTenXExTop: optionalNumber(document, "oneInTenXExTop", path, 0, false),
  };
}

function requireAvailableStatusEvidence(status: RankingStatus): void {
  const required: Array<[keyof RankingStatus, unknown]> = [
    ["sourceObservedAt", status.sourceObservedAt],
    ["catalogObservedAt", status.catalogObservedAt],
    ["modelVersion", status.modelVersion],
    ["sourceRunId", status.sourceRunId],
    ["catalogRunId", status.catalogRunId],
    ["analyticsRunId", status.analyticsRunId],
  ];
  for (const [field, value] of required) {
    if (value === null) {
      throw contractError(`status.${field}`, "is required when rankings are available");
    }
  }
}

function assertRowMatchesStatus(
  row: RankingRecord,
  status: RankingStatus,
  index: number,
): void {
  const path = `rankings[${index}]`;
  const comparisons: Array<[string, unknown, unknown]> = [
    ["analyticsRunId", row.analyticsRunId, status.analyticsRunId],
    ["sourceObservedAt", row.sourceObservedAt, status.sourceObservedAt],
    ["catalogObservedAt", row.catalogObservedAt, status.catalogObservedAt],
    ["modelVersion", row.modelVersion, status.modelVersion],
  ];
  for (const [field, rowValue, statusValue] of comparisons) {
    if (rowValue !== statusValue) {
      throw contractError(
        `${path}.${field}`,
        `must match status.${field}`,
      );
    }
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

function optionalString(
  object: Record<string, unknown>,
  key: string,
  path: string,
): string | null {
  const value = object[key];
  if (value === null) return null;
  if (typeof value !== "string" || value.trim() === "") {
    throw contractError(`${path}.${key}`, "must be null or a non-empty string");
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

function optionalTimestamp(
  object: Record<string, unknown>,
  key: string,
  path: string,
): string | null {
  const value = object[key];
  if (value === null) return null;
  if (typeof value !== "string" || Number.isNaN(Date.parse(value))) {
    throw contractError(`${path}.${key}`, "must be null or a valid timestamp");
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

function requiredInteger(
  object: Record<string, unknown>,
  key: string,
  path: string,
  minimum: number,
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
  path: string,
  minimum: number,
): number | null {
  const value = object[key];
  if (value === null) return null;
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw contractError(
      `${path}.${key}`,
      `must be null or an integer >= ${minimum}`,
    );
  }
  return value as number;
}

function requiredNumber(
  object: Record<string, unknown>,
  key: string,
  path: string,
  minimum: number,
  inclusive = true,
  maximum?: number,
): number {
  const value = object[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw contractError(`${path}.${key}`, "must be a finite number");
  }
  const meetsMinimum = inclusive ? value >= minimum : value > minimum;
  if (
    !meetsMinimum ||
    (maximum !== undefined && value > maximum)
  ) {
    const lowerBound = `${inclusive ? ">=" : ">"} ${minimum}`;
    const upperBound = maximum === undefined ? "" : ` and <= ${maximum}`;
    throw contractError(
      `${path}.${key}`,
      `must be a finite number ${lowerBound}${upperBound}`,
    );
  }
  return value;
}

function optionalNumber(
  object: Record<string, unknown>,
  key: string,
  path: string,
  minimum: number,
  inclusive = true,
): number | null {
  const value = object[key];
  if (value === null) return null;
  return requiredNumber(object, key, path, minimum, inclusive);
}

function requiredEnum<T extends string>(
  object: Record<string, unknown>,
  key: string,
  allowed: ReadonlySet<string>,
  path = "response",
): T {
  const value = object[key];
  if (typeof value !== "string" || !allowed.has(value)) {
    throw contractError(`${path}.${key}`, "has an unsupported value");
  }
  return value as T;
}

function contractError(path: string, detail: string): Error {
  return new Error(`Ranking response field ${path} ${detail}.`);
}
