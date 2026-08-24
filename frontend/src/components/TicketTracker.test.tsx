import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthSessionProvider } from "../context/AuthSessionProvider";
import { TicketTracker } from "./TicketTracker";

const authenticated = {
  authenticationAvailable: true,
  authenticated: true,
  user: { id: "08ec5c00-cdf8-487a-8db4-31f19be30f59", email: "p@example.test", emailVerified: true },
  session: {
    authenticatedAt: "2026-08-10T18:30:00Z",
    idleExpiresAt: "2026-08-11T18:30:00Z",
    absoluteExpiresAt: "2026-08-17T18:30:00Z",
  },
  csrfToken: "memory-csrf",
};

const history = {
  summary: {
    entryCount: 1,
    ticketCount: 2,
    amountSpent: 50,
    amountWon: 10,
    netResult: -40,
    returnPercentage: 20,
  },
  entries: [
    {
      id: "f7e01077-d6c1-4e08-a685-53539160d0f8",
      gameId: 102,
      gameNumber: "7665",
      gameName: "Mega Blast",
      ticketPrice: 25,
      playedOn: "2026-08-10",
      ticketCount: 2,
      amountSpent: 50,
      amountWon: 10,
      netResult: -40,
      createdAt: "2026-08-10T19:00:00Z",
    },
  ],
};

const gameDetail = {
  generatedAt: "2026-08-20T09:00:00Z",
  sourceObservedAt: "2026-08-20T08:00:00Z",
  catalogObservedAt: "2026-08-20T08:00:00Z",
  analyticsRunId: 7,
  modelVersion: "2.0.0",
  gameId: 102,
  gameNumber: "7665",
  gameName: "Mega Blast",
  ticketPrice: 25,
  launchDate: null,
  weeksInMarket: null,
  publishedOverallOddsOneIn: null,
  estimatedCurrentOverallOddsOneIn: null,
  estimatedOriginalTickets: null,
  estimatedSoldTickets: null,
  estimatedRemainingTickets: null,
  estimatedEvFull: null,
  estimatedEvExTop: null,
  topPrizeAmount: null,
  topPrizesOriginal: null,
  topPrizesRemaining: null,
  outcomes: [
    "any_win",
    "profit_full",
    "profit_ex_top",
    "moderate_10x_full",
    "moderate_10x_ex_top",
    "jackpot_top_odds",
  ].map((outcomeKey) => ({
    outcomeKey,
    probability: null,
    oneIn: null,
    metricStatus: "unavailable",
  })),
  tiers: [
    {
      prizeAmount: 10,
      isTopPrize: false,
      originalCount: 100,
      claimedCount: 40,
      reportedRemainingCount: 60,
      estimatedPendingCount: 0,
      estimatedRemainingCount: 60,
      adjustmentStatus: "applied",
      lagDaysUsed: null,
      launchOneIn: null,
      currentOneIn: null,
      confidenceLabel: null,
      status: "available",
    },
    {
      prizeAmount: 100,
      isTopPrize: true,
      originalCount: 10,
      claimedCount: 4,
      reportedRemainingCount: 6,
      estimatedPendingCount: 0,
      estimatedRemainingCount: 6,
      adjustmentStatus: "applied",
      lagDaysUsed: null,
      launchOneIn: null,
      currentOneIn: null,
      confidenceLabel: null,
      status: "available",
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("ticket tracker", () => {
  it("shows factual totals and submits a single-ticket result with a selectable prize", async () => {
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push({ url, method, body: typeof init?.body === "string" ? init.body : null });
      if (url.endsWith("/api/v1/auth/session")) return json(authenticated);
      if (url.endsWith("/api/v1/games/102")) return json(gameDetail);
      if (url.endsWith("/api/v1/ticket-entries") && method === "POST") {
        return json(history.entries[0], 201);
      }
      if (url.endsWith("/api/v1/ticket-entries")) return json(history);
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(
      <AuthSessionProvider>
        <TicketTracker games={[{ gameId: 102, gameNumber: "7665", gameName: "Mega Blast", ticketPrice: 25 }]} />
      </AuthSessionProvider>,
    );

    expect((await screen.findAllByText("−$40"))[0]).toBeVisible();
    expect(screen.getByRole("table", { name: "Saved ticket results" })).toHaveTextContent("Mega Blast");
    expect(screen.queryByLabelText("Number of tickets")).toBeNull();
    expect(screen.getByRole("heading", { name: "Track your results." })).toBeVisible();

    // One prize-bearing entry across two tickets: 1 winner, 1 loser, best prize $10.
    expect(screen.getByText("Winning tickets").closest("div")).toHaveTextContent("1");
    expect(screen.getByText("Losing tickets").closest("div")).toHaveTextContent("1");
    expect(screen.getByText("Biggest winner").closest("div")).toHaveTextContent("$10");

    // Amount won only offers $0 plus the game's actual prize amounts.
    const wonSelect = (await waitFor(() => {
      const select = screen.getByLabelText("Amount won") as HTMLSelectElement;
      expect(select).toBeEnabled();
      return select;
    })) as HTMLSelectElement;
    expect([...wonSelect.options].map((option) => option.textContent)).toEqual([
      "$0",
      "$10",
      "$100",
    ]);

    await user.selectOptions(wonSelect, "100");
    await user.click(screen.getByRole("button", { name: "Save ticket result" }));

    await waitFor(() => expect(requests.some((request) => request.method === "POST")).toBe(true));
    const posted = requests.find((request) => request.method === "POST")!;
    expect(JSON.parse(posted.body!)).toMatchObject({ gameId: 102, ticketCount: 1, amountWon: 100 });
  });

  it("disables the amount-won selector when prize data is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/auth/session")) return json(authenticated);
      if (url.endsWith("/api/v1/ticket-entries")) return json(history);
      return json({}, 404);
    }));
    render(
      <AuthSessionProvider>
        <TicketTracker games={[{ gameId: 102, gameNumber: "7665", gameName: "Mega Blast", ticketPrice: 25 }]} />
      </AuthSessionProvider>,
    );

    const wonSelect = (await screen.findByLabelText("Amount won")) as HTMLSelectElement;
    expect(wonSelect).toBeDisabled();
    expect([...wonSelect.options].map((option) => option.textContent)).toEqual(["$0"]);
  });

  it("filters the game selector by ticket price like the header search", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/auth/session")) return json(authenticated);
      if (url.endsWith("/api/v1/ticket-entries")) return json(history);
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(
      <AuthSessionProvider>
        <TicketTracker
          games={[
            { gameId: 102, gameNumber: "7665", gameName: "Mega Blast", ticketPrice: 25 },
            { gameId: 205, gameNumber: "7801", gameName: "Lucky Ten", ticketPrice: 10 },
          ]}
        />
      </AuthSessionProvider>,
    );

    // The entry form's Game select is the first one; the chart renders its own.
    const gameSelect = (await screen.findAllByLabelText("Game"))[0] as HTMLSelectElement;
    expect(gameSelect.options).toHaveLength(2);

    await user.selectOptions(screen.getByLabelText("Ticket price"), "10");
    expect(gameSelect.options).toHaveLength(1);
    expect(gameSelect.value).toBe("205");
    expect(gameSelect.options[0]!.textContent).toContain("Lucky Ten");

    await user.selectOptions(screen.getByLabelText("Ticket price"), "all");
    expect(gameSelect.options).toHaveLength(2);
  });

});

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
