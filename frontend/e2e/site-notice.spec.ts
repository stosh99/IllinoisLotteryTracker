import { expect, test, type Page } from "@playwright/test";

import { gameDetailFixture } from "../src/test/gameDetailFixture";
import { rankingDatasetFixture } from "../src/test/rankingDatasetFixture";

const KEY = "scratchoffdata.siteNotice";
const VERSION = "2026-08-25-v1";

async function mockApplication(page: Page) {
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticationAvailable: false,
        authenticated: false,
        user: null,
        session: null,
        csrfToken: null,
      }),
    }),
  );
  await page.route("**/api/v1/rankings", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rankingDatasetFixture) }),
  );
  await page.route("**/api/v1/games/102/history", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"status":{"available":false},"series":[]}' }),
  );
  await page.route("**/api/v1/games/102", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(gameDetailFixture) }),
  );
}

test.beforeEach(async ({ page }) => mockApplication(page));

test("first visit blocks the page until acknowledged and persists the return visit", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Scratch-Off Data");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    "https://scratchoffdata.com/",
  );
  const favicon = page.locator('link[rel="icon"]');
  await expect(favicon).toHaveAttribute("href", /3\.7\.54-2\.68/);
  expect(await favicon.getAttribute("href")).not.toContain("M26%2022");
  const dialog = page.getByRole("dialog", { name: "Before you use the estimates" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "I understand and continue" })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "Leave site" })).toHaveAttribute(
    "href",
    "https://www.illinoislottery.com/",
  );
  await expect(page.locator("#site-background")).toHaveAttribute("inert", "");

  await page.keyboard.press("Escape");
  await page.locator(".site-notice-backdrop").click({ position: { x: 2, y: 2 } });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "I understand and continue" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Scratch-Off Data home" })).toHaveText(
    "Scratch-Off Data",
  );
  await expect(page.locator(".brand--footer")).toHaveText("Scratch-Off Data");

  const firstValue = await page.evaluate((key) => localStorage.getItem(key), KEY);
  expect(JSON.parse(firstValue ?? "")).toMatchObject({ version: VERSION });
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Important information" })).toBeVisible();
});

test("old and malformed values require the current notice", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(
    ([key, value]) => localStorage.setItem(key, value),
    [KEY, JSON.stringify({ version: "old", acknowledgedAt: "2025-01-01T00:00:00Z" })],
  );
  await page.reload();
  await expect(page.getByRole("dialog", { name: "Before you use the estimates" })).toBeVisible();

  await page.evaluate((key) => localStorage.setItem(key, "malformed"), KEY);
  await page.reload();
  await expect(page.getByRole("dialog", { name: "Before you use the estimates" })).toBeVisible();
});

test("voluntary reopening closes with Escape, restores focus, and preserves timestamp", async ({ page }) => {
  const original = JSON.stringify({ version: VERSION, acknowledgedAt: "2026-08-25T10:00:00.000Z" });
  await page.goto("/");
  await page.evaluate(([key, value]) => localStorage.setItem(key, value), [KEY, original]);
  await page.goto("/games/102");
  await expect(page.getByRole("heading", { name: "Lakefront 10X" })).toBeVisible();

  const trigger = page.getByRole("button", { name: "Important information" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Before you use the estimates" });
  await expect(dialog.getByRole("button", { name: "Close" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "I understand and continue" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await page.evaluate((key) => localStorage.getItem(key), KEY)).toBe(original);
});

test("mobile notice fills the dynamic viewport and keeps controls reachable", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-390", "mobile-only layout assertion");
  await page.goto("/account");
  const notice = page.locator(".site-notice");
  const viewport = page.viewportSize()!;
  const box = await notice.boundingBox();
  expect(box?.width).toBe(viewport.width);
  expect(box?.height).toBe(viewport.height);
  await expect(page.getByRole("button", { name: "I understand and continue" })).toBeInViewport();
});
