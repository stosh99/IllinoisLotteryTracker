import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import App from "./App";
import { rankingDatasetFixture } from "./test/rankingDatasetFixture";
import type { RankingDataset } from "./types/rankings";

describe("initial ranking experience", () => {
  it("labels published data and renders an accessible comparison", () => {
    render(<App datasetOverride={rankingDatasetFixture} />);

    expect(screen.getByText(/Data valid as of/i)).toHaveTextContent(
      "Data valid as of 08/08/2026 · 2:04 AM CDT",
    );
    expect(screen.getByRole("table")).toHaveAccessibleName(/ranked instant-ticket/i);
    expect(screen.getAllByText("Prairie Gold").length).toBeGreaterThan(0);
    expect(screen.queryByText("DATA STATUS")).not.toBeInTheDocument();
    expect(screen.queryByText("test-1.0.0")).not.toBeInTheDocument();
    expect(screen.getAllByRole("radiogroup", { name: "Choose your player type" })).toHaveLength(1);
    expect(screen.queryByText("Explore the comparison")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /I can’t decide\. Show me every ticket/i }),
    ).toHaveAttribute("href", "/tickets");
    expect(
      within(screen.getByRole("radiogroup", { name: "Change player type" }))
        .getAllByRole("radio"),
    ).toHaveLength(6);

    const cardCarousel = screen.getByRole("region", { name: "Ranked game cards" });
    expect(within(cardCarousel).getAllByRole("article")).toHaveLength(8);
    expect(within(cardCarousel).getByText("Lakefront 10X")).toBeVisible();
    expect(within(cardCarousel).getByText("Lincoln Lucky Lines")).toBeVisible();
    expect(
      within(cardCarousel).getByText(/\$37\.95 per \$50 ticket over the long run/i),
    ).toBeVisible();
    expect(within(cardCarousel).getByText("About 71.6¢ in prizes per $1 over the long run")).toBeVisible();
    expect(within(cardCarousel).getAllByText("Why rank #1").length).toBeGreaterThan(0);
    expect(
      within(cardCarousel).getAllByText(/ordered by estimated return without the top prize/i).length,
    ).toBeGreaterThan(0);
    expect(
      within(cardCarousel).getAllByText(/full estimated return comes from the top prize/i).length,
    ).toBeGreaterThan(0);
    expect(
      within(cardCarousel).getByRole("link", { name: "View details for Lakefront 10X" }),
    ).toHaveAttribute("href", "/games/102");
    expect(cardCarousel).toHaveTextContent("2 out of 5 left");
    expect(screen.getByRole("table")).toHaveTextContent("2 out of 5 left");
    const rankingTable = screen.getByRole("table");
    expect(rankingTable).toHaveTextContent("Lincoln Lucky Lines");
    expect(
      within(rankingTable).getByRole("link", { name: "View details for Lakefront 10X" }),
    ).toHaveAttribute("href", "/games/102");
    expect(
      screen.getByRole("button", { name: "Show previous ranked games" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Show more ranked games" })).toBeVisible();
    expect(screen.getByText(/Showing cards 1–[1-8] of 8 games/)).toBeVisible();
    expect(
      screen.getByRole("heading", {
        name: "Know which numbers are reported—and which are estimated.",
      }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: /what does .?\$7\.42 return/i })).toBeVisible();
  });

  it("stores meaningful comparison choices in the URL", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);

    await user.click(
      within(screen.getByRole("radiogroup", { name: "Choose your player type" }))
        .getByRole("radio", { name: /overall value/i }),
    );
    await user.click(screen.getByRole("button", { name: "$10" }));

    expect(window.location.search).toBe("?strategy=value_full&price=10");
    expect(screen.getAllByText("Lakefront 10X").length).toBeGreaterThan(0);
    expect(screen.queryByText("Prairie Gold")).not.toBeInTheDocument();
  });

  it("keeps ticket search in the global finder instead of repeating it in the ranking filters", () => {
    render(<App datasetOverride={rankingDatasetFixture} />);

    expect(screen.queryByRole("searchbox", { name: "Search tickets" })).not.toBeInTheDocument();
    expect(screen.getByRole("search", { name: "Find a ticket" })).toBeVisible();
  });

  it("opens a game from the live header finder by name or number", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);

    const finder = screen.getByRole("search", { name: "Find a ticket" });
    await user.selectOptions(within(finder).getByLabelText("Ticket denomination"), "10");
    await user.type(within(finder).getByRole("combobox", { name: "Game name or number" }), "DEMO-102");
    await user.click(within(finder).getByRole("option", { name: "$10 · DEMO-102 — Lakefront 10X" }));
    await user.click(within(finder).getByRole("button", { name: "Go" }));

    expect(window.location.pathname).toBe("/games/102");
  });

  it("keeps the important caveats in a compact header popover", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);

    const trigger = screen.getByRole("button", { name: "Read this first" });
    expect(screen.queryByRole("dialog", { name: "Important information" })).not.toBeInTheDocument();
    await user.click(trigger);
    const popover = screen.getByRole("dialog", { name: "Important information" });
    expect(popover).toHaveTextContent("game-wide prize pool");
    expect(popover).toHaveTextContent("not affiliated with the Illinois Lottery");
  });

  it("offers a jackpot-inclusive profit comparison without duplicate odds", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);

    await user.click(
      within(screen.getByRole("radiogroup", { name: "Choose your player type" }))
        .getByRole("radio", { name: /best chance of profit/i }),
    );

    expect(window.location.search).toBe("?strategy=profit_full");
    expect(
      screen.getByRole("heading", {
        name: "Which tickets give me the best chance of winning more than they cost?",
      }),
    ).toBeVisible();
    expect(screen.queryByText(/chance of profit without the jackpot/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/winning more than the ticket price/i).length).toBeGreaterThan(0);
  });

  it("carries configured state into real detail hrefs and copied links", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    window.history.replaceState(
      {},
      "",
      "/?strategy=value_full&price=10&authResult=failed",
    );
    render(<App datasetOverride={rankingDatasetFixture} />);

    const detailLinks = screen.getAllByRole("link", {
      name: "View details for Lakefront 10X",
    });
    for (const link of detailLinks) {
      expect(link).toHaveAttribute(
        "href",
        "/games/102?strategy=value_full&price=10",
      );
    }

    await user.click(screen.getByRole("button", { name: "Copy this view" }));
    expect(writeText).toHaveBeenCalledWith(
      `${window.location.origin}/?strategy=value_full&price=10#rankings`,
    );
    expect(screen.getByText("Comparison link copied.")).toBeVisible();
  });

  it("reports clipboard failure without claiming success", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    render(<App datasetOverride={rankingDatasetFixture} />);

    await user.click(screen.getByRole("button", { name: "Copy this view" }));
    expect(screen.getByText(/copy unavailable/i)).toBeVisible();
    expect(screen.queryByText("Comparison link copied.")).not.toBeInTheDocument();
  });

  it("supports arrow-key navigation through the comparison goals", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);

    const chooser = screen.getByRole("radiogroup", { name: "Choose your player type" });
    const practical = within(chooser).getByRole("radio", { name: /practical value/i });
    practical.focus();
    await user.keyboard("{ArrowRight}");

    const overall = within(chooser).getByRole("radio", { name: /overall value/i });
    expect(overall).toHaveFocus();
    expect(overall).toHaveAttribute("aria-checked", "true");
    expect(practical).toHaveAttribute("tabindex", "-1");
    expect(window.location.search).toBe("?strategy=value_full");
  });

  it("limits the initial DOM and progressively reveals a large ranking", async () => {
    const user = userEvent.setup();
    const template = rankingDatasetFixture.rankings.find(
      (record) => record.strategyKey === "value_ex_top",
    )!;
    const scaled: RankingDataset = {
      ...rankingDatasetFixture,
      rankings: Array.from({ length: 20 }, (_, index) => ({
        ...template,
        gameId: 10_000 + index,
        gameNumber: `SCALE-${index + 1}`,
        gameName: `Scale game ${index + 1}`,
        metricValue: 1 - index / 100,
        rankOverall: index + 1,
        rankWithinTicketPrice: index + 1,
      })),
    };
    render(<App datasetOverride={scaled} />);

    expect(within(screen.getByRole("region", { name: "Ranked game cards" })).getAllByRole("article"))
      .toHaveLength(20);
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(13);

    await user.click(screen.getByRole("button", { name: "Show next 8" }));
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(21);
    expect(screen.getByText("Showing 20 of 20 complete results.")).toBeVisible();
  });

  it("hides ranking rows when publication is blocked", () => {
    const blocked: RankingDataset = {
      ...rankingDatasetFixture,
      mode: "live",
      status: {
        ...rankingDatasetFixture.status,
        available: false,
        reasonCode: "ANALYTICS_MODEL_UNAVAILABLE",
        modelVersion: null,
        analyticsRunId: null,
      },
      rankings: [],
    };

    render(<App datasetOverride={blocked} />);

    expect(
      screen.getByRole("heading", { name: /cannot calculate a trustworthy comparison/i }),
    ).toBeVisible();
    expect(screen.queryByText("ANALYTICS_MODEL_UNAVAILABLE")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Prairie Gold")).not.toBeInTheDocument();
  });
});
