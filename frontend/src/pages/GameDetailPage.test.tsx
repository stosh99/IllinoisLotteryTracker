import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "../App";
import { tierChanceTrend } from "./GameDetailPage";
import { gameDetailFixture } from "../test/gameDetailFixture";
import { gameHistoryFixture } from "../test/gameHistoryFixture";

describe("game detail page", () => {
  it("uses a two-percent materiality band for tier chance changes", () => {
    const tier = gameDetailFixture.tiers[0]!;

    expect(tierChanceTrend({ ...tier, launchOneIn: 100, currentOneIn: 98 })).toBe(
      "better",
    );
    expect(tierChanceTrend({ ...tier, launchOneIn: 100, currentOneIn: 102.1 })).toBe(
      "worse",
    );
    expect(tierChanceTrend({ ...tier, launchOneIn: 100, currentOneIn: 99 })).toBe(
      "same",
    );
  });

  it("lays out current game facts and every prize tier without hover", () => {
    window.history.replaceState({}, "", "/games/102");
    render(
      <App
        gameDetailOverride={gameDetailFixture}
        gameHistoryOverride={gameHistoryFixture}
      />,
    );

    expect(screen.getByRole("heading", { name: "Lakefront 10X" })).toBeVisible();
    expect(screen.getAllByText("2 out of 5 left").length).toBeGreaterThanOrEqual(2);
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

    const outcomeHeading = screen.getByRole("heading", {
      name: "What are my chances?",
    });
    const outcomeLadder = outcomeHeading.closest("section")!;
    expect(within(outcomeLadder).getByText("Win any prize")).toBeVisible();
    expect(within(outcomeLadder).getByText("Make a profit")).toBeVisible();
    expect(within(outcomeLadder).getByText("Win at least 10×")).toBeVisible();
    expect(within(outcomeLadder).queryByText("Without the jackpot")).not.toBeInTheDocument();
    expect(within(outcomeLadder).getByText("1 in 11.7")).toBeVisible();
    expect(within(outcomeLadder).getByText("8.55% estimated chance")).toBeVisible();
    expect(within(outcomeLadder).getByText("1 in 43.86")).toBeVisible();
    expect(within(outcomeLadder).getByText("1 in 1,125,000")).toBeVisible();
    expect(within(outcomeLadder).getByText("0.00009% estimated chance")).toBeVisible();
    expect(within(outcomeLadder).getByText(/do not add the percentages/i)).toBeVisible();
    expect(within(outcomeLadder).getByText("2 out of 5 left")).toBeVisible();
    const jackpotLane = within(outcomeLadder)
      .getByRole("heading", { name: "Top prize" })
      .closest("aside")!;
    expect(
      Array.from(jackpotLane.querySelectorAll("dd, .outcome-ladder__exact strong")).map(
        (element) => element.textContent,
      ),
    ).toEqual(["$500K", "2 out of 5 left", "1 in 1,125,000"]);

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
    const tableGuide = screen
      .getByText("How to read this table")
      .closest<HTMLDivElement>(".prize-tier-note")!;
    expect(within(tableGuide).getByText("What the data labels mean")).toBeVisible();
    expect(
      table.compareDocumentPosition(tableGuide) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByText(/official count used/i)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Estimated tickets sold" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Prizes claimed by tier" })).toBeVisible();
    expect(
      screen.getByRole("img", { name: /estimated tickets sold over time/i }),
    ).toBeVisible();
    expect(
      screen.getByRole("img", { name: /percentage of prizes claimed/i }),
    ).toBeVisible();
    expect(screen.getByText("4 of 4 tiers")).toBeVisible();
    expect(screen.queryByText("2.0.0")).not.toBeInTheDocument();
  });

  it("shows an honest unavailable state for an incomplete outcome", () => {
    const detail = structuredClone(gameDetailFixture);
    detail.outcomes[1]!.metricStatus = "partial";
    window.history.replaceState({}, "", "/games/102");
    render(
      <App
        gameDetailOverride={detail}
        gameHistoryOverride={gameHistoryFixture}
      />,
    );

    const profitCard = screen.getByRole("heading", { name: "Make a profit" }).closest<HTMLDivElement>(
      ".outcome-ladder__break-even",
    )!;
    expect(within(profitCard).getByText("Current estimate is incomplete")).toBeVisible();
  });

  it("distinguishes a missing prize tier from an incomplete estimate", () => {
    const detail = structuredClone(gameDetailFixture);
    detail.outcomes[0]!.metricStatus = "not_applicable";
    window.history.replaceState({}, "", "/games/102");
    render(
      <App
        gameDetailOverride={detail}
        gameHistoryOverride={gameHistoryFixture}
      />,
    );

    expect(screen.getByText("No matching prize tier in this game")).toBeVisible();
  });

  it("preserves comparison context in the compact return control", () => {
    window.history.replaceState(
      {},
      "",
      "/games/102?strategy=value_full&price=10&private=discard-me",
    );
    render(
      <App
        gameDetailOverride={gameDetailFixture}
        gameHistoryOverride={gameHistoryFixture}
      />,
    );

    expect(screen.getByRole("link", { name: /Back to comparison/ })).toHaveAttribute(
      "href",
      "/?strategy=value_full&price=10#rankings",
    );
    expect(screen.queryByRole("button", { name: "Copy this game view" })).not.toBeInTheDocument();
  });
});
