import { describe, expect, it } from "vitest";

import {
  absolutePublicUrl,
  comparisonHref,
  gameDetailHref,
  parseViewState,
  serializeViewState,
  viewStateLabel,
} from "./urlState";

describe("ranking URL state", () => {
  it("parses supported filters", () => {
    expect(
      parseViewState("?strategy=moderate_10x&price=20"),
    ).toEqual({
      strategy: "moderate_10x_full",
      ticketPrice: 20,
    });
  });

  it("maps old non-jackpot profit links into the current profit view", () => {
    const state = parseViewState("?strategy=profit_ex_top&price=5");
    expect(state).toEqual({ strategy: "profit_full", ticketPrice: 5 });
    expect(serializeViewState(state)).toBe("strategy=profit_full&price=5");
    expect(viewStateLabel(state)).toBe("Best chance of profit · $5 tickets");
  });

  it("falls back safely for invalid values", () => {
    expect(parseViewState("?strategy=secret_score&price=-10")).toEqual({
      strategy: "value_ex_top",
      ticketPrice: "all",
    });
  });

  it("omits default values from shared URLs", () => {
    expect(
      serializeViewState({
        strategy: "value_ex_top",
        ticketPrice: "all",
      }),
    ).toBe("");

    expect(
      serializeViewState({
        strategy: "value_full",
        ticketPrice: 10,
      }),
    ).toBe("strategy=value_full&price=10");
  });

  it("builds deterministic comparison and detail links", () => {
    const state = { strategy: "value_full" as const, ticketPrice: 10 as const };
    expect(comparisonHref(state)).toBe("/?strategy=value_full&price=10#rankings");
    expect(comparisonHref(state, "methodology")).toBe(
      "/?strategy=value_full&price=10#methodology",
    );
    expect(gameDetailHref(102, state)).toBe(
      "/games/102?strategy=value_full&price=10",
    );
    expect(viewStateLabel(state)).toBe("Overall value · $10 tickets");
  });

  it("keeps default links canonical and rejects invalid game ids", () => {
    expect(comparisonHref({ strategy: "value_ex_top", ticketPrice: "all" })).toBe(
      "/#rankings",
    );
    expect(
      viewStateLabel({ strategy: "value_ex_top", ticketPrice: "all" }),
    ).toBe("Practical value · all ticket prices");
    expect(() => gameDetailHref(0, { strategy: "value_ex_top", ticketPrice: "all" }))
      .toThrow(/positive integer/i);
  });

  it("creates absolute public URLs without inheriting transient parameters", () => {
    expect(
      absolutePublicUrl(
        "/?strategy=value_full&price=10#rankings",
        "https://tracker.example.test",
      ),
    ).toBe("https://tracker.example.test/?strategy=value_full&price=10#rankings");
    expect(() => absolutePublicUrl("/#rankings", "file:///tmp/index.html"))
      .toThrow(/HTTP origin/i);
  });
});
