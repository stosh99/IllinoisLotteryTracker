import { describe, expect, it } from "vitest";

import { gameDetailFixture } from "../test/gameDetailFixture";
import { buildOutcomeRows, formatOutcomeProbability } from "./outcomeLadder";

describe("outcome ladder", () => {
  it("keeps break-even, nested ordinary outcomes, and jackpot in their defined order", () => {
    const rows = buildOutcomeRows([...gameDetailFixture.outcomes].reverse());

    expect(rows.map(({ key }) => key)).toEqual([
      "money_back_exact",
      "profit_ex_top",
      "moderate_5x",
      "moderate_10x",
      "jackpot_top_odds",
    ]);
    expect(rows.map(({ lane }) => lane)).toEqual([
      "break-even",
      "ordinary",
      "ordinary",
      "ordinary",
      "jackpot",
    ]);
    expect(rows.filter(({ lane }) => lane === "ordinary").map(({ depth }) => depth))
      .toEqual([0, 1, 2]);
  });

  it("normalizes only the nested ordinary-outcome bars", () => {
    const rows = buildOutcomeRows(gameDetailFixture.outcomes);

    expect(rows.find(({ key }) => key === "profit_ex_top")?.relativeWidth).toBe(100);
    expect(rows.find(({ key }) => key === "moderate_5x")?.relativeWidth).toBeCloseTo(48.55, 1);
    expect(rows.find(({ key }) => key === "moderate_10x")?.relativeWidth).toBeCloseTo(26.68, 1);
    expect(rows.find(({ key }) => key === "money_back_exact")?.relativeWidth).toBe(0);
    expect(rows.find(({ key }) => key === "jackpot_top_odds")?.relativeWidth).toBe(0);
  });

  it("does not portray partial or missing metrics as zero", () => {
    const metrics = gameDetailFixture.outcomes.map((metric) =>
      metric.outcomeKey === "moderate_5x"
        ? { ...metric, metricStatus: "partial" as const }
        : metric,
    );
    const partial = buildOutcomeRows(metrics).find(({ key }) => key === "moderate_5x")!;

    expect(partial.available).toBe(false);
    expect(partial.probability).toBeNull();
    expect(partial.oneIn).toBeNull();
    expect(formatOutcomeProbability(partial.probability)).toBe("Unavailable");
  });

  it("keeps useful percentage precision from common outcomes through jackpot odds", () => {
    expect(formatOutcomeProbability(0.111)).toBe("11.1%");
    expect(formatOutcomeProbability(0.0228)).toBe("2.28%");
    expect(formatOutcomeProbability(0.000000888889)).toBe("0.00009%");
  });
});
