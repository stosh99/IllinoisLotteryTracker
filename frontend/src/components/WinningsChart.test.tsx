import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { TicketEntry } from "../types/ticketEntries";
import { buildDailySeries, WinningsChart } from "./WinningsChart";

function entry(overrides: Partial<TicketEntry>): TicketEntry {
  return {
    id: crypto.randomUUID(),
    gameId: 68,
    gameNumber: "7664",
    gameName: "$250,000 CROSSWORD",
    ticketPrice: 10,
    playedOn: "2026-08-10",
    ticketCount: 1,
    amountSpent: 10,
    amountWon: 0,
    netResult: -10,
    createdAt: "2026-08-10T12:00:00Z",
    ...overrides,
  };
}

describe("buildDailySeries", () => {
  it("fills every day from the first entry through the end date", () => {
    const series = buildDailySeries(
      [
        entry({ playedOn: "2026-08-10", netResult: -10 }),
        entry({ playedOn: "2026-08-12", netResult: 40, amountWon: 50 }),
        entry({ playedOn: "2026-08-12", netResult: -10 }),
      ],
      "2026-08-14",
    );

    expect(series.map((point) => point.date)).toEqual([
      "2026-08-10",
      "2026-08-11",
      "2026-08-12",
      "2026-08-13",
      "2026-08-14",
    ]);
    expect(series.map((point) => point.cumulative)).toEqual([-10, -10, 20, 20, 20]);
    expect(series.map((point) => point.hasEntry)).toEqual([true, false, true, false, false]);
    expect(series[2]!.dayNet).toBe(30);
  });

  it("returns an empty series without entries", () => {
    expect(buildDailySeries([], "2026-08-14")).toEqual([]);
  });
});

describe("winnings chart", () => {
  const entries = [
    entry({ gameId: 68, ticketPrice: 10, netResult: -10 }),
    entry({
      gameId: 69,
      gameNumber: "7665",
      gameName: "$1,000,000 CROSSWORD 50X",
      ticketPrice: 25,
      amountSpent: 25,
      netResult: -25,
      playedOn: "2026-08-11",
    }),
  ];

  it("derives price pills from history and keeps pills and game selection exclusive", async () => {
    const user = userEvent.setup();
    const { container } = render(<WinningsChart entries={entries} />);

    expect(screen.getByRole("group", { name: "Filter chart by ticket price" })).toBeVisible();
    const entryDots = () => container.querySelectorAll("circle.is-entry").length;
    expect(entryDots()).toBe(2);

    // Pills come from the user's own denominations only.
    expect(screen.getByRole("button", { name: "$10" })).toBeVisible();
    expect(screen.getByRole("button", { name: "$25" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "$1" })).toBeNull();

    // Default: All is highlighted and the game selector is empty.
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    const gameSelect = screen.getByLabelText("Game") as HTMLSelectElement;
    expect(gameSelect.value).toBe("");
    expect([...gameSelect.options].map((option) => option.value)).toEqual(["", "68", "69"]);

    // Choosing a pill highlights it and keeps the game selector empty.
    await user.click(screen.getByRole("button", { name: "$10" }));
    expect(entryDots()).toBe(1);
    expect(screen.getByRole("button", { name: "$10" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
    expect(gameSelect.value).toBe("");
    expect([...gameSelect.options].map((option) => option.value)).toEqual(["", "68"]);

    // Choosing a game clears every pill highlight.
    await user.click(screen.getByRole("button", { name: "All" }));
    await user.selectOptions(gameSelect, "69");
    expect(entryDots()).toBe(1);
    expect(gameSelect.value).toBe("69");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "$25" })).toHaveAttribute("aria-pressed", "false");

    // Clearing the game selection returns to All.
    await user.selectOptions(gameSelect, "");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(entryDots()).toBe(2);
  });

  it("colors segments and dots by daily direction", () => {
    const { container } = render(
      <WinningsChart
        entries={[
          entry({ playedOn: "2026-08-10", netResult: -10 }),
          entry({ playedOn: "2026-08-12", amountWon: 50, netResult: 40 }),
        ]}
      />,
    );

    // Day 1 loss dot is red; day 3 win dot is green; the gap day is a small grey dot.
    expect(container.querySelectorAll(".winnings-chart__dot.is-entry.is-negative")).toHaveLength(1);
    expect(container.querySelectorAll(".winnings-chart__dot.is-entry.is-positive")).toHaveLength(1);
    expect(container.querySelectorAll(".winnings-chart__dot.is-neutral").length).toBeGreaterThan(0);
    // Flat day-over-day segments are solid grey; the winning day's segment is green.
    expect(container.querySelectorAll(".winnings-chart__segment.is-neutral").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".winnings-chart__segment.is-positive")).toHaveLength(1);
    expect(container.querySelectorAll(".winnings-chart__segment.is-negative")).toHaveLength(0);
  });

  it("shows an empty message when there is no history at all", () => {
    render(<WinningsChart entries={[]} />);

    expect(screen.getByText("No saved results for this selection yet.")).toBeVisible();
  });
});
