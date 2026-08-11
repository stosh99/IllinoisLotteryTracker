import { afterEach, describe, expect, it, vi } from "vitest";

import { gameHistoryFixture } from "../test/gameHistoryFixture";
import { assertGameHistory, loadGameHistory } from "./gameHistory";

describe("game-history response validation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts chronological sales and tier series", () => {
    expect(assertGameHistory(gameHistoryFixture)).toEqual(gameHistoryFixture);
  });

  it("loads history from the game-scoped endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => gameHistoryFixture,
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadGameHistory(102)).resolves.toEqual(gameHistoryFixture);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/games/102/history",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("rejects sales estimates that do not reconcile", () => {
    const invalid = structuredClone(gameHistoryFixture);
    invalid.salesPoints[0]!.estimatedRemainingTickets = 1;
    expect(() => assertGameHistory(invalid)).toThrow(/ticket estimates must reconcile/i);
  });

  it("rejects tier points that are not chronological", () => {
    const invalid = structuredClone(gameHistoryFixture);
    invalid.tierSeries[0]!.points.reverse();
    expect(() => assertGameHistory(invalid)).toThrow(/must be chronological/i);
  });
});
