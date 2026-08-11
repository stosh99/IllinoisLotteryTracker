import { describe, expect, it } from "vitest";

import {
  formatCentsPerDollar,
  formatLongRunReturn,
  formatOneIn,
  formatRelativeToLaunch,
} from "./strategies";

describe("player-facing metric language", () => {
  it("translates a payout ratio into cents per dollar", () => {
    expect(formatCentsPerDollar(0.716)).toBe(
      "About 71.6¢ in prizes per $1 over the long run",
    );
  });

  it("anchors estimated return to ticket price and the long run", () => {
    expect(formatLongRunReturn(7.42, 10)).toBe(
      "$7.42 per $10 ticket over the long run",
    );
    expect(formatLongRunReturn(null, 10)).toBe("Unavailable");
  });

  it("keeps useful precision for published overall odds", () => {
    expect(formatOneIn(3.92)).toBe("1 in 3.92");
    expect(formatOneIn(15_679.44)).toBe("1 in 15,679");
  });

  it("states the direction of a launch comparison", () => {
    expect(formatRelativeToLaunch(1.015)).toBe("1.5% higher than at launch");
    expect(formatRelativeToLaunch(0.98)).toBe("2% lower than at launch");
    expect(formatRelativeToLaunch(1)).toBe("About the same as at launch");
  });
});
