import { describe, expect, it } from "vitest";

import { rankingDatasetFixture } from "../test/rankingDatasetFixture";
import { directoryGames } from "./AllTicketsPage";

describe("all-ticket directory", () => {
  it("deduplicates the six strategy rows and sorts games alphabetically", () => {
    const games = directoryGames(rankingDatasetFixture);

    expect(games).toHaveLength(8);
    expect(games.map((game) => game.gameName)).toEqual(
      [...games.map((game) => game.gameName)].sort((left, right) =>
        left.localeCompare(right),
      ),
    );
    expect(games.find((game) => game.gameNumber === "DEMO-102")).toMatchObject({
      gameId: 102,
      gameName: "Lakefront 10X",
      ticketPrice: 10,
      topPrizeAmount: 500_000,
      topPrizesOriginal: 5,
      topPrizesRemaining: 2,
    });
  });
});
