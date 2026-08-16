import { describe, expect, it } from "vitest";

import { gameDetailFixture } from "../test/gameDetailFixture";
import { buildOutcomeRows, formatOutcomeProbability } from "./outcomeLadder";

describe("outcome ladder", () => {
  it("keeps the three player outcomes, their no-jackpot context, and jackpot in order", () => {
    const rows = buildOutcomeRows([...gameDetailFixture.outcomes].reverse());

    expect(rows.map(({ key }) => key)).toEqual([
      "any_win",
      "profit_full",
      "profit_ex_top",
      "moderate_10x_full",
      "moderate_10x_ex_top",
      "jackpot_top_odds",
    ]);
    expect(rows.map(({ lane }) => lane)).toEqual([
      "primary",
      "primary",
      "supporting",
      "primary",
      "supporting",
      "jackpot",
    ]);
  });

  it("normalizes only the three primary outcome bars", () => {
    const rows = buildOutcomeRows(gameDetailFixture.outcomes);

    expect(rows.find(({ key }) => key === "any_win")?.relativeWidth).toBe(100);
    expect(rows.find(({ key }) => key === "profit_full")?.relativeWidth).toBeCloseTo(32.91, 1);
    expect(rows.find(({ key }) => key === "moderate_10x_full")?.relativeWidth).toBeCloseTo(8.78, 1);
    expect(rows.find(({ key }) => key === "profit_ex_top")?.relativeWidth).toBe(0);
    expect(rows.find(({ key }) => key === "jackpot_top_odds")?.relativeWidth).toBe(0);
  });

  it("does not portray partial or missing metrics as zero", () => {
    const metrics = gameDetailFixture.outcomes.map((metric) =>
      metric.outcomeKey === "moderate_10x_full"
        ? { ...metric, metricStatus: "partial" as const }
        : metric,
    );
    const partial = buildOutcomeRows(metrics).find(({ key }) => key === "moderate_10x_full")!;

    expect(partial.available).toBe(false);
    expect(partial.probability).toBeNull();
    expect(partial.oneIn).toBeNull();
    expect(formatOutcomeProbability(partial.probability)).toBe("Unavailable");
  });

  it("keeps useful percentage precision from common outcomes through jackpot odds", () => {
    expect(formatOutcomeProbability(0.25974)).toBe("26%");
    expect(formatOutcomeProbability(0.0228)).toBe("2.28%");
    expect(formatOutcomeProbability(0.000000888889)).toBe("0.00009%");
  });
});
