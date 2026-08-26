import { expect, test, type Page } from "@playwright/test";

import { gameDetailFixture } from "../src/test/gameDetailFixture";
import { rankingDatasetFixture } from "../src/test/rankingDatasetFixture";

const disabledSession = {
  authenticationAvailable: false,
  authenticated: false,
  user: null,
  session: null,
  csrfToken: null,
};

const anonymousSession = {
  authenticationAvailable: true,
  authenticated: false,
  user: null,
  session: null,
  csrfToken: null,
};

const authenticatedSession = {
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
  csrfToken: "browser-memory-only-csrf",
};

async function mockRankings(page: Page) {
  await page.route("**/api/v1/rankings", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rankingDatasetFixture) }),
  );
}

async function mockEmptyTicketHistory(page: Page) {
  // The entry form loads the selected game's prize tiers for the amount-won list.
  await page.route("**/api/v1/games/*", (route) => {
    const gameId = Number(new URL(route.request().url()).pathname.split("/").pop());
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...gameDetailFixture, gameId }),
    });
  });
  await page.route("**/api/v1/ticket-entries", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        summary: {
          entryCount: 0,
          ticketCount: 0,
          amountSpent: 0,
          amountWon: 0,
          netResult: 0,
          returnPercentage: null,
        },
        entries: [],
      }),
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "scratchoffdata.siteNotice",
      JSON.stringify({ version: "2026-08-25-v1", acknowledgedAt: "2026-08-25T12:00:00.000Z" }),
    );
  });
});

test("rankings remain usable when authentication is disabled", async ({ page }) => {
  await mockRankings(page);
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(disabledSession) }),
  );
  await page.goto("/");
  await expect(page.getByText(/Data valid as of/i)).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Account sign-in is not enabled yet.")).toBeVisible();
  expect(await page.evaluate(() => [Object.keys(localStorage), sessionStorage.length])).toEqual([
    ["scratchoffdata.siteNotice"],
    0,
  ]);
});

test("anonymous state presents a same-origin Google start navigation", async ({ page }) => {
  await mockRankings(page);
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(anonymousSession) }),
  );
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Log in" })).toHaveAttribute(
    "href",
    "/api/v1/auth/google/start?returnTo=%2F",
  );
});

test("authenticated account route works on direct load without client storage", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await mockRankings(page);
  await mockEmptyTicketHistory(page);
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(authenticatedSession) }),
  );
  await page.route("**/api/v1/auth/sessions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        sessions: [
          {
            id: "988977c9-3aa0-4de8-933a-d4454d707413",
            current: true,
            createdAt: "2026-08-10T18:30:00Z",
            lastSeenAt: "2026-08-10T19:05:00Z",
            idleExpiresAt: "2026-08-11T19:05:00Z",
            absoluteExpiresAt: "2026-08-17T18:30:00Z",
          },
        ],
      }),
    }),
  );
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Signed-in sessions" })).toBeVisible();
  await expect(page.getByText("Current session")).toBeVisible();
  expect(await page.evaluate(() => [Object.keys(localStorage), sessionStorage.length])).toEqual([
    ["scratchoffdata.siteNotice"],
    0,
  ]);
  expect(errors).toEqual([]);
});

test("stale deletion discards confirmation before one-time Google navigation", async ({ page }) => {
  await mockRankings(page);
  await mockEmptyTicketHistory(page);
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(authenticatedSession) }),
  );
  await page.route("**/api/v1/auth/sessions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"sessions":[]}' }),
  );
  await page.route("**/api/v1/account", async (route) => {
    if (route.request().method() === "DELETE") {
      await route.fulfill({
        status: 403,
        contentType: "application/problem+json",
        body: '{"code":"RECENT_AUTH_REQUIRED"}',
      });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/v1/auth/google/reauth-delete", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authorizationUrl:
          "https://accounts.google.com/o/oauth2/v2/auth?state=bounded",
      }),
    }),
  );
  await page.route("https://accounts.google.com/o/oauth2/v2/auth?*", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Fake Google</h1>" }),
  );
  await page.goto("/account");
  await page.getByLabel("Confirmation phrase").fill("DELETE MY ACCOUNT");
  await page.getByRole("button", { name: "Delete my account" }).click();
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await expect(page.locator('input[value="DELETE MY ACCOUNT"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(
    "https://accounts.google.com/o/oauth2/v2/auth?state=bounded",
  );
  expect(await page.evaluate(() => [Object.keys(localStorage), sessionStorage.length])).toEqual([
    ["scratchoffdata.siteNotice"],
    0,
  ]);
});

test("fake-provider journey logs in, rejects replay, rotates, and deletes", async ({ page }) => {
  let authenticated = false;
  let currentAttempt = "";
  let attemptConsumed = false;
  let intent: "login" | "reauth_delete" = "login";
  let sessionVersion = 0;
  let deletionAttempts = 0;
  let providerTarget = "";
  let callbackTarget = "";
  let callbackLocation = "";
  const authorizationRequests: URL[] = [];
  const unexpectedExternal: string[] = [];

  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      !["127.0.0.1", "accounts.google.com"].includes(url.hostname) &&
      url.protocol !== "data:"
    ) {
      unexpectedExternal.push(request.url());
    }
  });
  await mockRankings(page);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
      route.fulfill({
        status,
        contentType: status === 204 ? undefined : "application/json",
        body: status === 204 ? undefined : JSON.stringify(body),
        headers,
      });
    if (url.pathname === "/api/v1/rankings") {
      await route.fallback();
      return;
    }
    if (url.pathname === "/api/v1/auth/session") {
      await json(200, authenticated ? {
        ...authenticatedSession,
        csrfToken: `csrf-${sessionVersion}`,
        session: {
          ...authenticatedSession.session,
          authenticatedAt: `2026-08-10T18:${30 + sessionVersion}:00Z`,
        },
      } : anonymousSession);
      return;
    }
    if (url.pathname === "/api/v1/auth/google/start") {
      expect(url.searchParams.get("returnTo")).toBe("/");
      intent = "login";
      currentAttempt = `attempt-${sessionVersion + 1}`;
      attemptConsumed = false;
      providerTarget =
        `https://accounts.google.com/o/oauth2/v2/auth?response_type=code` +
        `&scope=openid%20email&state=${currentAttempt}&nonce=nonce` +
        `&code_challenge=pkce-challenge&code_challenge_method=S256`;
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "Fake local login start",
        headers: { "cache-control": "no-store" },
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/google/callback") {
      const state = url.searchParams.get("state");
      if (attemptConsumed || state !== currentAttempt) {
        callbackLocation = "/?authResult=failed";
        await route.fulfill({
          status: 200,
          contentType: "text/html",
          body: "Rejected callback",
          headers: { "cache-control": "no-store" },
        });
        return;
      }
      attemptConsumed = true;
      authenticated = true;
      sessionVersion += 1;
      callbackLocation =
        intent === "reauth_delete" ? "/account?authResult=success" : "/?authResult=success";
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "Accepted callback",
        headers: {
          "cache-control": "no-store",
          "set-cookie": `ilt_session_dev=opaque-session-${sessionVersion}; HttpOnly; SameSite=Lax; Path=/`,
        },
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/logout") {
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-csrf-token"]).toBe(`csrf-${sessionVersion}`);
      authenticated = false;
      await json(204, undefined, {
        "set-cookie": "ilt_session_dev=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/",
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/sessions") {
      await json(200, {
        sessions: authenticated ? [{
          id: "988977c9-3aa0-4de8-933a-d4454d707413",
          current: true,
          createdAt: "2026-08-10T18:30:00Z",
          lastSeenAt: "2026-08-10T19:05:00Z",
          idleExpiresAt: "2026-08-11T19:05:00Z",
          absoluteExpiresAt: "2026-08-17T18:30:00Z",
        }] : [],
      });
      return;
    }
    if (url.pathname === "/api/v1/ticket-entries") {
      await json(200, {
        summary: {
          entryCount: 0,
          ticketCount: 0,
          amountSpent: 0,
          amountWon: 0,
          netResult: 0,
          returnPercentage: null,
        },
        entries: [],
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/google/reauth-delete") {
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-csrf-token"]).toBe(`csrf-${sessionVersion}`);
      intent = "reauth_delete";
      currentAttempt = `reauth-${sessionVersion}`;
      attemptConsumed = false;
      await json(200, {
        authorizationUrl:
          `https://accounts.google.com/o/oauth2/v2/auth?response_type=code` +
          `&scope=openid%20email&state=${currentAttempt}&nonce=nonce` +
          `&code_challenge=reauth-challenge&code_challenge_method=S256&prompt=select_account`,
      });
      return;
    }
    if (url.pathname === "/api/v1/account" && request.method() === "DELETE") {
      expect(request.headers()["x-csrf-token"]).toBe(`csrf-${sessionVersion}`);
      deletionAttempts += 1;
      if (deletionAttempts === 1) {
        await json(403, { code: "RECENT_AUTH_REQUIRED" });
      } else {
        authenticated = false;
        await json(204, undefined, {
          "set-cookie": "ilt_session_dev=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/",
        });
      }
      return;
    }
    await json(404, { code: "NOT_FOUND" });
  });
  await page.route("https://accounts.google.com/o/oauth2/v2/auth?*", async (route) => {
    const authorization = new URL(route.request().url());
    authorizationRequests.push(authorization);
    expect(authorization.searchParams.get("response_type")).toBe("code");
    expect(authorization.searchParams.get("scope")).toBe("openid email");
    expect(authorization.searchParams.get("code_challenge_method")).toBe("S256");
    expect(authorization.searchParams.has("access_type")).toBe(false);
    expect(authorization.searchParams.get("scope")).not.toContain("profile");
    callbackTarget =
      `http://127.0.0.1:4173/api/v1/auth/google/callback?` +
      `code=fake-code&state=${authorization.searchParams.get("state")}`;
    await route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Fake Google</h1>" });
  });

  await page.goto("/");
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("link", { name: "Log in" }).click();
  await page.goto(providerTarget);
  await page.goto(callbackTarget);
  await page.goto(callbackLocation);
  await expect(page.getByText("Account", { exact: true })).toBeVisible();
  expect(authorizationRequests).toHaveLength(1);
  expect(await page.evaluate(() => document.cookie)).toBe("");
  expect(await page.evaluate(() => [Object.keys(localStorage), sessionStorage.length])).toEqual([
    ["scratchoffdata.siteNotice"],
    0,
  ]);
  await page.reload();
  await page.getByText("Account", { exact: true }).click();
  await expect(page.getByText("player@example.test")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
  await page.goto(
    `http://127.0.0.1:4173/api/v1/auth/google/callback?code=replayed&state=${currentAttempt}`,
  );
  await page.goto(callbackLocation);
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
  await expect(page).not.toHaveURL(/authResult=/);
  expect(authenticated).toBe(false);

  await page.getByRole("link", { name: "Log in" }).click();
  await page.goto(providerTarget);
  await page.goto(callbackTarget);
  await page.goto(callbackLocation);
  await page.goto("/account");
  await page.getByLabel("Confirmation phrase").fill("DELETE MY ACCOUNT");
  await page.getByRole("button", { name: "Delete my account" }).click();
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/accounts\.google\.com/);
  expect(authorizationRequests.at(-1)?.searchParams.get("prompt")).toBe("select_account");
  await page.goto(callbackTarget);
  await page.goto(callbackLocation);
  expect(sessionVersion).toBe(3);
  await page.getByLabel("Confirmation phrase").fill("DELETE MY ACCOUNT");
  await page.getByRole("button", { name: "Delete my account" }).click();
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
  expect(authenticated).toBe(false);
  expect(deletionAttempts).toBe(2);
  expect(await page.evaluate(() => document.cookie)).toBe("");
  expect(await page.evaluate(() => [Object.keys(localStorage), sessionStorage.length])).toEqual([
    ["scratchoffdata.siteNotice"],
    0,
  ]);
  expect(unexpectedExternal).toEqual([]);
});
