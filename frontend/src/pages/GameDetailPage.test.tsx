import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "../App";
import { gameDetailFixture } from "../test/gameDetailFixture";
import { gameHistoryFixture } from "../test/gameHistoryFixture";

describe("game detail page", () => {
  it("lays out current game facts and every prize tier without hover", () => {
    window.history.replaceState({}, "", "/games/102");
    render(
      <App
        gameDetailOverride={gameDetailFixture}
        gameHistoryOverride={gameHistoryFixture}
      />,
    );

    expect(screen.getByRole("heading", { name: "Lakefront 10X" })).toBeVisible();
    expect(screen.getByText("2 out of 5 left")).toBeVisible();
    expect(screen.getByText("Est. tickets sold")).toBeVisible();

    const table = screen.getByRole("table", {
      name: /current prize tiers for Lakefront 10X/i,
    });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByRole("columnheader", { name: "Claimed" })).toBeVisible();
    expect(
      within(table).getByRole("columnheader", { name: "Est. odds now" }),
    ).toBeVisible();
    expect(within(table).getByText("143.5")).toBeVisible();
    expect(within(table).getByText(/6.5 pending/i)).toBeVisible();
    expect(within(table).getByText("1 in 15,679")).toBeVisible();
    expect(screen.getByText(/eligible prize tiers over \$600/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Estimated tickets sold" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Prizes claimed by tier" })).toBeVisible();
    expect(
      screen.getByRole("img", { name: /estimated tickets sold over time/i }),
    ).toBeVisible();
    expect(
      screen.getByRole("img", { name: /percentage of prizes claimed/i }),
    ).toBeVisible();
    expect(screen.getByText("≈ 2,750,000")).toBeVisible();
    expect(screen.getByText("4 of 4 tiers")).toBeVisible();
  });
});
