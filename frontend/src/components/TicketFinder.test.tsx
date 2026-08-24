import { describe, expect, it } from "vitest";

import { rankingDatasetFixture } from "../test/rankingDatasetFixture";
import { uniqueGames } from "./TicketFinder";

describe("uniqueGames", () => {
  it("orders games by ticket price and then by name", () => {
    const ordered = uniqueGames(rankingDatasetFixture);

    expect(ordered.length).toBeGreaterThan(1);
    for (let index = 1; index < ordered.length; index++) {
      const previous = ordered[index - 1]!;
      const current = ordered[index]!;
      expect(previous.ticketPrice).toBeLessThanOrEqual(current.ticketPrice);
      if (previous.ticketPrice === current.ticketPrice) {
        expect(previous.gameName.localeCompare(current.gameName)).toBeLessThan(0);
      }
    }
  });

  it("returns an empty list without a dataset", () => {
    expect(uniqueGames(null)).toEqual([]);
  });
});
