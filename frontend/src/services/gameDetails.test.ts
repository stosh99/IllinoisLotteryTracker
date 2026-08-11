import { afterEach, describe, expect, it, vi } from "vitest";

import { gameDetailFixture } from "../test/gameDetailFixture";
import { assertGameDetail, loadGameDetail } from "./gameDetails";

describe("game-detail response validation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts the complete current-detail contract", () => {
    expect(assertGameDetail(gameDetailFixture)).toEqual(gameDetailFixture);
  });

  it("loads a game through the same-origin API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => gameDetailFixture,
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadGameDetail(102)).resolves.toEqual(gameDetailFixture);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/games/102",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("rejects tier counts that do not reconcile", () => {
    const invalid = structuredClone(gameDetailFixture);
    invalid.tiers[0]!.claimedCount = 2;

    expect(() => assertGameDetail(invalid)).toThrow(
      /claimed and remaining counts must reconcile/i,
    );
  });

  it("rejects a response with no prize tiers", () => {
    const invalid = { ...gameDetailFixture, tiers: [] };
    expect(() => assertGameDetail(invalid)).toThrow(/tiers must not be empty/i);
  });

  it("rejects duplicate or missing outcome metrics", () => {
    const invalid = structuredClone(gameDetailFixture);
    invalid.outcomes[1] = { ...invalid.outcomes[0]! };

    expect(() => assertGameDetail(invalid)).toThrow(
      /each supported outcome exactly once/i,
    );
  });
});
