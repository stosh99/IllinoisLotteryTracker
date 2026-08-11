import { afterEach, describe, expect, it, vi } from "vitest";

import { rankingDatasetFixture } from "../test/rankingDatasetFixture";
import { assertRankingDataset, loadRankingDataset } from "./rankings";

describe("ranking response validation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the same-origin API when no endpoint override is configured", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => rankingDatasetFixture,
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadRankingDataset()).resolves.toEqual(rankingDatasetFixture);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/rankings",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("accepts the complete live contract", () => {
    expect(assertRankingDataset(rankingDatasetFixture)).toEqual(rankingDatasetFixture);
  });

  it("rejects a contradictory publication status", () => {
    const invalid = structuredClone(rankingDatasetFixture);
    invalid.status.reasonCode = "ANALYTICS_MODEL_UNAVAILABLE";

    expect(() => assertRankingDataset(invalid)).toThrow(
      /available must be true exactly when reasonCode is AVAILABLE/i,
    );
  });

  it("rejects rows when publication is unavailable", () => {
    const invalid = structuredClone(rankingDatasetFixture);
    invalid.status = {
      ...invalid.status,
      available: false,
      reasonCode: "ANALYTICS_MODEL_UNAVAILABLE",
      modelVersion: null,
      analyticsRunId: null,
    };

    expect(() => assertRankingDataset(invalid)).toThrow(
      /unavailable ranking responses must not include ranking rows/i,
    );
  });

  it("rejects a row missing a required nullable field", () => {
    const invalid = structuredClone(rankingDatasetFixture);
    const firstRow = invalid.rankings[0] as unknown as Record<string, unknown>;
    delete firstRow.estimatedEvExTop;

    expect(() => assertRankingDataset(invalid)).toThrow(
      /rankings\[0\]\.estimatedEvExTop must be a finite number/i,
    );
  });

  it("rejects a row from a different analytics run", () => {
    const invalid = structuredClone(rankingDatasetFixture);
    invalid.rankings[0]!.analyticsRunId += 1;

    expect(() => assertRankingDataset(invalid)).toThrow(
      /rankings\[0\]\.analyticsRunId must match status\.analyticsRunId/i,
    );
  });

  it("rejects a row with a mismatched data cutoff", () => {
    const invalid = structuredClone(rankingDatasetFixture);
    invalid.rankings[0]!.sourceObservedAt = "2026-08-09T07:04:43Z";

    expect(() => assertRankingDataset(invalid)).toThrow(
      /rankings\[0\]\.sourceObservedAt must match status\.sourceObservedAt/i,
    );
  });

  it("rejects a response that attempts to enable demo mode", () => {
    const invalid = structuredClone(rankingDatasetFixture) as unknown as Record<
      string,
      unknown
    >;
    invalid.mode = "demo";

    expect(() => assertRankingDataset(invalid)).toThrow(/mode has an unsupported value/i);
  });
});
