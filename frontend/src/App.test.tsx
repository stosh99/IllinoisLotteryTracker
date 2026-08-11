import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "./App";
import { rankingDatasetFixture } from "./test/rankingDatasetFixture";
import type { RankingDataset } from "./types/rankings";

describe("initial ranking experience", () => {
  it("labels published data and renders an accessible comparison", () => {
    render(<App datasetOverride={rankingDatasetFixture} />);

    expect(
      screen.getByRole("heading", { name: "Comparison ready" }),
    ).toBeVisible();
    expect(screen.getByText("DATA STATUS")).toBeVisible();
    expect(screen.getByRole("table")).toHaveAccessibleName(/ranked instant-ticket/i);
    expect(screen.getAllByText("Prairie Gold").length).toBeGreaterThan(0);
    expect(screen.getByText("Official prize counts")).toBeVisible();
    expect(screen.getByText("Games-for-sale list")).toBeVisible();
    expect(screen.getByText("Page updated")).toBeVisible();
    expect(screen.queryByText("test-1.0.0")).not.toBeInTheDocument();

    const cardCarousel = screen.getByRole("region", { name: "Ranked game cards" });
    expect(within(cardCarousel).getAllByRole("article")).toHaveLength(8);
    expect(within(cardCarousel).getByText("Lakefront 10X")).toBeVisible();
    expect(within(cardCarousel).getByText("Lincoln Lucky Lines")).toBeVisible();
    expect(
      within(cardCarousel).getByText(/\$35\.80 per \$50 ticket over the long run/i),
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

    await user.click(screen.getByRole("radio", { name: /overall value/i }));
    await user.click(screen.getByRole("button", { name: "$10" }));

    expect(window.location.search).toBe("?strategy=value_full&price=10");
    expect(screen.getAllByText("Lakefront 10X").length).toBeGreaterThan(0);
    expect(screen.queryByText("Prairie Gold")).not.toBeInTheDocument();
  });

  it("supports arrow-key navigation through the comparison goals", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);

    const practical = screen.getByRole("radio", { name: /practical value/i });
    practical.focus();
    await user.keyboard("{ArrowRight}");

    const overall = screen.getByRole("radio", { name: /overall value/i });
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
