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
    expect(screen.getAllByText("Estimated tickets sold").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Official report").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Estimate").length).toBeGreaterThan(0);
    const dependenceHeading = screen.getByRole("heading", {
      name: "How much estimated return depends on the top prize?",
    });
    const dependence = dependenceHeading.closest("section")!;
    expect(within(dependence).getByText("74.2¢ per $1")).toBeVisible();
    expect(within(dependence).getByText("70.4¢ per $1")).toBeVisible();
    expect(within(dependence).getByText("3.8¢ per $1")).toBeVisible();
    expect(within(dependence).getByText(/5.1% of full estimated return/i)).toBeVisible();
    expect(
      within(dependence).getByRole("img", { name: /estimated return comes from prizes below the top tier/i }),
    ).toBeVisible();
    expect(within(dependence).getByText(/not a prediction for one ticket/i)).toBeVisible();

    const table = screen.getByRole("table", {
      name: /current prize tiers for Lakefront 10X/i,
    });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByRole("columnheader", { name: /^Claimed/ })).toBeVisible();
    expect(
      within(table).getByRole("columnheader", { name: /Estimated chance now/i }),
    ).toBeVisible();
    expect(
      within(table).getByRole("columnheader", { name: "Current count used" }),
    ).toBeVisible();
    expect(within(table).getByText("143.5")).toBeVisible();
    expect(within(table).getByText(/6.5 estimated pending/i)).toBeVisible();
    expect(within(table).getByText("1 in 15,679")).toBeVisible();
    expect(screen.getByText(/only to prize tiers over \$600/i)).toBeVisible();
    expect(screen.getByText(/fewer than 300 starting prizes/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Estimated tickets sold" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Prizes claimed by tier" })).toBeVisible();
    expect(
      screen.getByRole("img", { name: /estimated tickets sold over time/i }),
    ).toBeVisible();
    expect(
      screen.getByRole("img", { name: /percentage of prizes claimed/i }),
    ).toBeVisible();
    expect(screen.getByText("About 2,750,001")).toBeVisible();
    expect(screen.getByText("4 of 4 tiers")).toBeVisible();
    expect(screen.queryByText("2.0.0")).not.toBeInTheDocument();
  });
});
