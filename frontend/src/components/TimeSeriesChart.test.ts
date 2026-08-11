import { describe, expect, it } from "vitest";

import { buildSegmentedPaths, linearTicks } from "./TimeSeriesChart";

describe("time-series chart geometry", () => {
  it("breaks paths across structural segments", () => {
    const paths = buildSegmentedPaths(
      [
        { observedAt: "2026-05-01T00:00:00Z", value: 10, segment: 0 },
        { observedAt: "2026-05-02T00:00:00Z", value: 20, segment: 0 },
        { observedAt: "2026-05-03T00:00:00Z", value: 15, segment: 1 },
      ],
      (value) => value / 86_400_000,
      (value) => 100 - value,
    );

    expect(paths).toHaveLength(2);
    expect(paths[0]!.d).toContain(" L");
    expect(paths[1]!.d).not.toContain(" L");
  });

  it("builds inclusive evenly spaced ticks", () => {
    expect(linearTicks(0, 100, 5)).toEqual([0, 25, 50, 75, 100]);
  });
});
