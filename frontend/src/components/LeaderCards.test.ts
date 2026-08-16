import { describe, expect, it } from "vitest";

import { rankingDatasetFixture } from "../test/rankingDatasetFixture";
import {
  formatCardRange,
  getCarouselPageStarts,
  getVisibleCardRange,
  primaryMetric,
  sampleDescription,
  secondaryMetric,
} from "./LeaderCards";

describe("leader-card carousel labels", () => {
  it("describes only the visible card positions and total game count", () => {
    expect(formatCardRange(4, 3, 8)).toBe("Showing cards 5–7 of 8 games");
    expect(formatCardRange(5, 3, 8)).toBe("Showing cards 6–8 of 8 games");
  });

  it("keeps the final page full without losing the preceding page boundary", () => {
    expect(getCarouselPageStarts(8, 3)).toEqual([0, 3, 5]);
    expect(getCarouselPageStarts(7, 3)).toEqual([0, 3, 4]);
  });

  it("derives the range from card midpoints instead of stale rank state", () => {
    const cards = Array.from({ length: 8 }, (_, index) => ({
      start: index * 120,
      end: index * 120 + 100,
    }));

    expect(getVisibleCardRange(cards, 240, 580)).toEqual({
      activeIndex: 2,
      visibleCount: 3,
    });
    expect(getVisibleCardRange(cards, 300, 640)).toEqual({
      activeIndex: 3,
      visibleCount: 2,
    });
  });

  it("uses one-in and percentage forms for probability strategies", () => {
    const record = rankingDatasetFixture.rankings.find(
      (candidate) => candidate.strategyKey === "any_win",
    )!;

    expect(primaryMetric(record)).toMatch(/^1 in /);
    expect(secondaryMetric(record)).toMatch(/estimated chance$/);
  });

  it("describes prize-sample size without calling it a winning confidence", () => {
    const record = rankingDatasetFixture.rankings.find(
      (candidate) => candidate.strategyKey === "jackpot_top_odds" && candidate.containsLumpyTier,
    )!;

    expect(sampleDescription(record)).toBe("Very small prize sample");
  });
});
