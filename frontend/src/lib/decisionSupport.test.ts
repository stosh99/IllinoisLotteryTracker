import { describe, expect, it } from "vitest";

import { rankingDatasetFixture } from "../test/rankingDatasetFixture";
import type { RankingRecord } from "../types/rankings";
import {
  calculateJackpotDependence,
  explainRank,
  formatCentsPerDollarValue,
  formatShare,
} from "./decisionSupport";

function rowsFor(strategyKey: RankingRecord["strategyKey"]): RankingRecord[] {
  return rankingDatasetFixture.rankings
    .filter((record) => record.strategyKey === strategyKey)
    .sort((left, right) => left.rankOverall - right.rankOverall);
}

describe("ranking explanations", () => {
  it("distinguishes a sole leader from tied leaders", () => {
    const rows = rowsFor("value_ex_top");
    expect(explainRank(rows[0]!, rows, false).comparison).toMatch(/strongest result/i);
    expect(explainRank(rows[0]!, rows, false).comparison).not.toMatch(/tied/i);

    const tied = rows.map((record, index) => ({
      ...record,
      rankOverall: index < 2 ? 1 : record.rankOverall,
    }));
    expect(explainRank(tied[0]!, tied, false).comparison).toMatch(/tied/i);
  });

  it("uses a cents-per-dollar leader gap for return strategies", () => {
    const rows = rowsFor("value_ex_top");
    const explanation = explainRank(rows[1]!, rows, false);

    expect(explanation.heading).toBe("Why rank #2");
    expect(explanation.basis).toMatch(/return without the top prize/i);
    expect(explanation.comparison).toMatch(/¢ per \$1 below the leader/i);
  });

  it("compares one-in-X values for probability strategies", () => {
    const rows = rowsFor("jackpot_top_odds");
    const explanation = explainRank(rows[1]!, rows, false);

    expect(explanation.basis).toMatch(/chance of winning the top prize/i);
    expect(explanation.comparison).toMatch(/1 in .+; the leader is 1 in/i);
  });

  it("states that the profit comparison excludes the top prize", () => {
    const rows = rowsFor("profit_ex_top");
    expect(explainRank(rows[1]!, rows, false).basis).toMatch(
      /winning more than the ticket price, excluding the top prize/i,
    );
  });

  it("falls back to percentages when one-in-X is unavailable", () => {
    const rows = rowsFor("money_back_exact").map((record) => ({
      ...record,
      oneInValue: null,
    }));
    expect(explainRank(rows[1]!, rows, false).comparison).toMatch(/%.*leader.*%/i);
  });

  it("uses the price-filter rank when the view is filtered", () => {
    const rows = rowsFor("value_full").filter((record) => record.ticketPrice === 10);
    const leader = rows.find((record) => record.rankWithinTicketPrice === 1)!;
    expect(explainRank(leader, rows, true).heading).toBe("Why rank #1");
  });
});

describe("jackpot dependence", () => {
  it("decomposes full estimated return without changing its units", () => {
    const result = calculateJackpotDependence(10, 7.42, 7.04)!;

    expect(result.fullReturnPerDollar).toBeCloseTo(0.742);
    expect(result.nonTopReturnPerDollar).toBeCloseTo(0.704);
    expect(result.topContributionPerDollar).toBeCloseTo(0.038);
    expect(result.topShare).toBeCloseTo(0.38 / 7.42);
    expect(result.nonTopShare + result.topShare).toBeCloseTo(1);
    expect(formatCentsPerDollarValue(result.topContributionPerDollar)).toBe("3.8¢ per $1");
    expect(formatShare(result.topShare)).toBe("5.1%");
  });

  it.each([
    [0, 7.42, 7.04],
    [10, null, 7.04],
    [10, 0, 0],
    [10, 7.42, null],
    [10, 7.42, -1],
    [10, 7.42, 8],
  ])("rejects unsupported inputs", (ticketPrice, full, exTop) => {
    expect(calculateJackpotDependence(ticketPrice, full, exTop)).toBeNull();
  });

  it("tolerates only a display-rounding difference", () => {
    expect(calculateJackpotDependence(10, 7.42, 7.424)).not.toBeNull();
    expect(calculateJackpotDependence(10, 7.42, 7.426)).toBeNull();
  });
});
