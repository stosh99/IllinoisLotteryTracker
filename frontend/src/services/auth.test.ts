import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AuthRequestError,
  deleteAccount,
  loadAuthSession,
  logoutSession,
  revokeSession,
  startDeleteReauthentication,
  validateGoogleAuthorizationUrl,
} from "./auth";

const authenticated = {
  authenticationAvailable: true,
  authenticated: true,
  user: { id: "08ec5c00-cdf8-487a-8db4-31f19be30f59", email: "p@example.test", emailVerified: true },
  session: {
    authenticatedAt: "2026-08-10T18:30:00Z",
    idleExpiresAt: "2026-08-11T18:30:00Z",
    absoluteExpiresAt: "2026-08-17T18:30:00Z",
  },
  csrfToken: "csrf-only-in-memory",
};

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("authentication transport", () => {
  it("loads and validates the discriminated same-origin session contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(authenticated), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadAuthSession()).resolves.toEqual(authenticated);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/session",
      expect.objectContaining({ credentials: "same-origin", cache: "no-store", redirect: "error" }),
    );
  });

  it("fails closed on contradictory or extra session fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ...authenticated, providerToken: "forbidden" }), {
          status: 200,
        }),
      ),
    );
    await expect(loadAuthSession()).rejects.toMatchObject({ code: "AUTH_UNAVAILABLE" });
  });

  it("attaches in-memory CSRF only to unsafe same-origin requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await logoutSession("csrf-value");
    await revokeSession("988977c9-3aa0-4de8-933a-d4454d707413", "csrf-value");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/logout",
      expect.objectContaining({
        method: "POST",
        body: "{}",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf-value" },
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/auth/sessions/988977c9-3aa0-4de8-933a-d4454d707413",
      expect.objectContaining({ method: "DELETE", headers: { "X-CSRF-Token": "csrf-value" } }),
    );
  });

  it("does not replay a failed unsafe request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ code: "AUTH_REQUIRED" }),
        { status: 401, headers: { "Content-Type": "application/problem+json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(logoutSession("csrf-value")).rejects.toBeInstanceOf(AuthRequestError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("accepts only the pinned Google authorization destination", () => {
    expect(
      validateGoogleAuthorizationUrl(
        "https://accounts.google.com/o/oauth2/v2/auth?state=bounded",
      ),
    ).toContain("accounts.google.com");
    for (const value of [
      "http://accounts.google.com/o/oauth2/v2/auth?state=x",
      "https://accounts.google.com.attacker.test/o/oauth2/v2/auth?state=x",
      "https://user@accounts.google.com/o/oauth2/v2/auth?state=x",
      "https://accounts.google.com/other?state=x",
      "https://accounts.google.com/o/oauth2/v2/auth?state=x#fragment",
    ]) {
      expect(() => validateGoogleAuthorizationUrl(value)).toThrow(AuthRequestError);
    }
  });

  it("uses strict CSRF JSON requests for reauth and deletion", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            authorizationUrl:
              "https://accounts.google.com/o/oauth2/v2/auth?state=bounded",
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await startDeleteReauthentication("csrf-value");
    await deleteAccount("DELETE MY ACCOUNT", "csrf-value");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/google/reauth-delete",
      expect.objectContaining({ method: "POST", body: "{}" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/account",
      expect.objectContaining({
        method: "DELETE",
        body: '{"confirmation":"DELETE MY ACCOUNT"}',
      }),
    );
  });
});
