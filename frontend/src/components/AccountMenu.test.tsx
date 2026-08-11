import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { rankingDatasetFixture } from "../test/rankingDatasetFixture";

const anonymous = {
  authenticationAvailable: true,
  authenticated: false,
  user: null,
  session: null,
  csrfToken: null,
};

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

afterEach(() => vi.unstubAllGlobals());

function sessionFetch(document: object) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(document), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

describe("account controls", () => {
  it("shows an ordinary top-level sign-in link only when auth is anonymous", async () => {
    sessionFetch(anonymous);
    render(<App datasetOverride={rankingDatasetFixture} />);
    const link = await screen.findByRole("link", { name: "Sign in with Google" });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start?returnTo=%2F");
  });

  it("exposes account actions through a native disclosure", async () => {
    const user = userEvent.setup();
    sessionFetch(authenticated);
    render(<App datasetOverride={rankingDatasetFixture} />);
    const summary = await screen.findByText("Account", { selector: "summary" });
    await user.click(summary);
    expect(screen.getByText("p@example.test")).toBeVisible();
    expect(screen.getByRole("link", { name: "Manage sessions" })).toHaveAttribute(
      "href",
      "/account",
    );
  });

  it("displays only allowlisted auth results and removes them from the URL", async () => {
    window.history.replaceState({}, "", "/?authResult=expired&strategy=value_full");
    sessionFetch(anonymous);
    render(<App datasetOverride={rankingDatasetFixture} />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "That sign-in attempt expired. Please try again.",
    );
    await waitFor(() => expect(window.location.search).toBe("?strategy=value_full"));
  });
});
