import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthSessionContext } from "../context/AuthSessionProvider";
import type { AuthSessionContextValue } from "../context/AuthSessionProvider";
import { AccountSettings } from "./AccountSettings";

const context: AuthSessionContextValue = {
  state: {
    status: "authenticated",
    session: {
      authenticationAvailable: true,
      authenticated: true,
      user: {
        id: "08ec5c00-cdf8-487a-8db4-31f19be30f59",
        email: "player@example.test",
        emailVerified: true,
      },
      session: {
        authenticatedAt: "2026-08-10T18:30:00Z",
        idleExpiresAt: "2026-08-11T18:30:00Z",
        absoluteExpiresAt: "2026-08-17T18:30:00Z",
      },
      csrfToken: "memory-csrf",
    },
  },
  refresh: vi.fn(),
  logout: vi.fn(),
  logoutAll: vi.fn(),
  announceChange: vi.fn(),
};

afterEach(() => vi.unstubAllGlobals());

function renderSettings(navigateToProvider = vi.fn()) {
  render(
    <MemoryRouter>
      <AuthSessionContext.Provider value={context}>
        <AccountSettings navigateToProvider={navigateToProvider} />
      </AuthSessionContext.Provider>
    </MemoryRouter>,
  );
  return navigateToProvider;
}

describe("account deletion settings", () => {
  it("requires the exact phrase and discards it when recent auth is required", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: "RECENT_AUTH_REQUIRED" }), {
          status: 403,
          headers: { "Content-Type": "application/problem+json" },
        }),
      ),
    );
    renderSettings();
    const button = screen.getByRole("button", { name: "Delete my account" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("Confirmation phrase"), "DELETE MY ACCOUNT");
    await user.click(button);
    expect(await screen.findByRole("button", { name: "Continue with Google" })).toBeVisible();
    expect(screen.queryByDisplayValue("DELETE MY ACCOUNT")).not.toBeInTheDocument();
  });

  it("uses the validated authorization URL once for immediate navigation", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ code: "RECENT_AUTH_REQUIRED" }), {
          status: 403,
          headers: { "Content-Type": "application/problem+json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            authorizationUrl:
              "https://accounts.google.com/o/oauth2/v2/auth?state=bounded",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    renderSettings(navigate);
    await user.type(screen.getByLabelText("Confirmation phrase"), "DELETE MY ACCOUNT");
    await user.click(screen.getByRole("button", { name: "Delete my account" }));
    await user.click(await screen.findByRole("button", { name: "Continue with Google" }));
    expect(navigate).toHaveBeenCalledOnce();
    expect(navigate).toHaveBeenCalledWith(
      "https://accounts.google.com/o/oauth2/v2/auth?state=bounded",
    );
  });
});
