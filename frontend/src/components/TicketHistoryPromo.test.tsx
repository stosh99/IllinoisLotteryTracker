import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthSessionProvider } from "../context/AuthSessionProvider";
import { TicketHistoryHint, TICKET_HINT_STORAGE_KEY } from "./TicketHistoryHint";
import { TicketHistoryPromo } from "./TicketHistoryPromo";

const sessions = {
  disabled: {
    authenticationAvailable: false,
    authenticated: false,
    user: null,
    session: null,
    csrfToken: null,
  },
  anonymous: {
    authenticationAvailable: true,
    authenticated: false,
    user: null,
    session: null,
    csrfToken: null,
  },
  authenticated: {
    authenticationAvailable: true,
    authenticated: true,
    user: { id: "08ec5c00-cdf8-487a-8db4-31f19be30f59", email: "p@example.test", emailVerified: true },
    session: {
      authenticatedAt: "2026-08-10T18:30:00Z",
      idleExpiresAt: "2026-08-11T18:30:00Z",
      absoluteExpiresAt: "2026-08-17T18:30:00Z",
    },
    csrfToken: "memory-csrf",
  },
};

function mockSession(kind: keyof typeof sessions) {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify(sessions[kind]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  ));
}

function renderWithAuth(children: React.ReactNode) {
  return render(
    <MemoryRouter>
      <AuthSessionProvider>{children}</AuthSessionProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("ticket history promo (hero panel row)", () => {
  it("pitches the feature to signed-out visitors and returns them to /account", async () => {
    mockSession("anonymous");
    renderWithAuth(<TicketHistoryPromo />);

    const link = await screen.findByRole("link", { name: /record what you spend and win/i });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start?returnTo=%2Faccount");
    expect(link).toHaveTextContent(/private ticket history/i);
  });

  it("becomes a shortcut to their history for signed-in users", async () => {
    mockSession("authenticated");
    renderWithAuth(<TicketHistoryPromo />);

    const link = await screen.findByRole("link", { name: /my ticket history/i });
    expect(link).toHaveAttribute("href", "/account#ticket-history");
  });

  it("renders nothing while authentication is disabled", async () => {
    mockSession("disabled");
    const { container } = renderWithAuth(<TicketHistoryPromo />);

    await vi.waitFor(() => expect(container.querySelectorAll("a")).toHaveLength(0));
  });
});

describe("ticket history hint (header callout)", () => {
  it("shows for signed-out visitors and stays dismissed once closed", async () => {
    mockSession("anonymous");
    const user = userEvent.setup();
    renderWithAuth(<TicketHistoryHint />);

    expect(await screen.findByText("Track your plays. Log in to start.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByRole("note")).toBeNull();
    expect(window.localStorage.getItem(TICKET_HINT_STORAGE_KEY)).toBe("2026-08-28-v1");
  });

  it("never shows again after a recorded dismissal", async () => {
    window.localStorage.setItem(TICKET_HINT_STORAGE_KEY, "2026-08-28-v1");
    mockSession("anonymous");
    const { container } = renderWithAuth(<TicketHistoryHint />);

    await vi.waitFor(() => expect(container.querySelector(".ticket-history-hint")).toBeNull());
  });

  it("does not show for signed-in users or while auth is disabled", async () => {
    for (const kind of ["authenticated", "disabled"] as const) {
      mockSession(kind);
      const { container, unmount } = renderWithAuth(<TicketHistoryHint />);
      await vi.waitFor(() => expect(container.querySelector(".ticket-history-hint")).toBeNull());
      unmount();
      vi.unstubAllGlobals();
    }
  });
});
