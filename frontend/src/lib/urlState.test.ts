import { describe, expect, it } from "vitest";

import { parseViewState, serializeViewState } from "./urlState";

describe("ranking URL state", () => {
  it("parses supported filters", () => {
    expect(
      parseViewState("?strategy=moderate_10x&price=20"),
    ).toEqual({
      strategy: "moderate_10x",
      ticketPrice: 20,
    });
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
});
