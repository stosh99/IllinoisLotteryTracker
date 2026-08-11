import { describe, expect, it } from "vitest";

import { formatCardRange, getCarouselPageStarts } from "./LeaderCards";

describe("leader-card carousel labels", () => {
  it("describes only the visible card positions and total game count", () => {
    expect(formatCardRange(4, 3, 8)).toBe("Showing cards 5–7 of 8 games");
    expect(formatCardRange(5, 3, 8)).toBe("Showing cards 6–8 of 8 games");
  });

  it("keeps the final page full without losing the preceding page boundary", () => {
    expect(getCarouselPageStarts(8, 3)).toEqual([0, 3, 5]);
    expect(getCarouselPageStarts(7, 3)).toEqual([0, 3, 4]);
  });
});
