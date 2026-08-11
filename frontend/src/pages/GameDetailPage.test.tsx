import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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
      name: "What could one ticket return?",
    });
    const outcomeLadder = outcomeHeading.closest("section")!;
    expect(within(outcomeLadder).getByText("Exactly money back")).toBeVisible();
    expect(within(outcomeLadder).getByText("Any ordinary profit")).toBeVisible();
    expect(within(outcomeLadder).getByText("At least 5× the ticket price")).toBeVisible();
    expect(within(outcomeLadder).getByText("At least 10× the ticket price")).toBeVisible();
    expect(within(outcomeLadder).getByText("1 in 11.7")).toBeVisible();
    expect(within(outcomeLadder).getByText("8.55% estimated chance")).toBeVisible();
    expect(within(outcomeLadder).getByText("1 in 1,125,000")).toBeVisible();
    expect(within(outcomeLadder).getByText("0.00009% estimated chance")).toBeVisible();
    expect(within(outcomeLadder).getByText(/do not add these three percentages/i)).toBeVisible();
    expect(within(outcomeLadder).getByText("2 out of 5 left")).toBeVisible();

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

  it("shows an honest unavailable state for an incomplete outcome", () => {
    const detail = structuredClone(gameDetailFixture);
    detail.outcomes[2]!.metricStatus = "partial";
    window.history.replaceState({}, "", "/games/102");
    render(
      <App
        gameDetailOverride={detail}
        gameHistoryOverride={gameHistoryFixture}
      />,
    );

    const ordinary = screen.getByRole("heading", { name: "Ordinary profit" }).closest("div")
      ?.parentElement?.parentElement!;
    expect(within(ordinary).getByText("Current estimate is incomplete")).toBeVisible();
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

  it("preserves comparison context in return and copied game links", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
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

    expect(screen.getByText("Returns to Overall value · $10 tickets")).toBeVisible();
    expect(screen.getByRole("link", { name: /Back to comparison/ })).toHaveAttribute(
      "href",
      "/?strategy=value_full&price=10#rankings",
    );
    await user.click(screen.getByRole("button", { name: "Copy this game view" }));
    expect(writeText).toHaveBeenCalledWith(
      `${window.location.origin}/games/102?strategy=value_full&price=10`,
    );
    expect(screen.getByText("Game link copied.")).toBeVisible();
  });
});
