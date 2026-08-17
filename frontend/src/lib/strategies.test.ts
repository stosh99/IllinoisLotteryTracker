import { describe, expect, it } from "vitest";

import {
  formatCentsPerDollar,
  formatLongRunReturn,
  formatOneIn,
  formatRelativeToLaunch,
  getMetricScale,
  metricBarWidth,
} from "./strategies";

describe("player-facing metric language", () => {
  it("translates a payout ratio into cents per dollar", () => {
    expect(formatCentsPerDollar(0.716)).toBe("71.6¢ per $1.00");
  });

  it("uses stable disclosed scales for value and chance comparisons", () => {
    expect(metricBarWidth(0.5, "value_ex_top")).toBe(0);
    expect(metricBarWidth(0.75, "value_ex_top")).toBe(50);
    expect(metricBarWidth(1, "value_full")).toBe(100);
    expect(metricBarWidth(0.2, "any_win")).toBe(50);
    expect(metricBarWidth(0.15, "profit_full")).toBe(50);
    expect(metricBarWidth(0.025, "moderate_10x_full")).toBe(50);
    expect(getMetricScale("any_win").label).toBe("Bar scale: 0%–40% chance");
  });

  it("uses a logarithmic jackpot scale across orders of magnitude", () => {
    expect(metricBarWidth(0, "jackpot_top_odds")).toBe(0);
    expect(metricBarWidth(1 / 10_000_000, "jackpot_top_odds")).toBe(0);
    expect(metricBarWidth(1 / 100_000, "jackpot_top_odds")).toBeCloseTo(40);
    expect(metricBarWidth(1 / 100, "jackpot_top_odds")).toBe(100);
    expect(getMetricScale("jackpot_top_odds").mode).toBe("logarithmic");
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
