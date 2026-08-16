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

afterEach(() => vi.unstubAllGlobals());

describe("ticket tracker", () => {
  it("shows factual totals and submits a bounded private result", async () => {
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push({ url, method, body: typeof init?.body === "string" ? init.body : null });
      if (url.endsWith("/api/v1/auth/session")) return json(authenticated);
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

    expect((await screen.findAllByText("−$40.00"))[0]).toBeVisible();
    expect(screen.getByRole("table", { name: "Saved ticket results" })).toHaveTextContent("Mega Blast");
    await user.clear(screen.getByLabelText("Number of tickets"));
    await user.type(screen.getByLabelText("Number of tickets"), "3");
    await user.clear(screen.getByLabelText("Total amount won"));
    await user.type(screen.getByLabelText("Total amount won"), "15");
    expect(screen.getByText("$75.00")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save ticket result" }));

    await waitFor(() => expect(requests.some((request) => request.method === "POST")).toBe(true));
    const posted = requests.find((request) => request.method === "POST")!;
    expect(JSON.parse(posted.body!)).toMatchObject({ gameId: 102, ticketCount: 3, amountWon: 15 });
  });
});

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
