import { expect, test, type Page } from "@playwright/test";

import { gameDetailFixture } from "../src/test/gameDetailFixture";
import { gameHistoryFixture } from "../src/test/gameHistoryFixture";
import { rankingDatasetFixture } from "../src/test/rankingDatasetFixture";

const disabledSession = {
  authenticationAvailable: false,
  authenticated: false,
  user: null,
  session: null,
  csrfToken: null,
};

const GAME_COUNT = new Set(
  rankingDatasetFixture.rankings.map((record) => record.gameId),
).size;

async function mockPublicPages(page: Page) {
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(disabledSession),
    }),
  );
  await page.route("**/api/v1/rankings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(rankingDatasetFixture),
    }),
  );
  await page.route("**/api/v1/games/102/history", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(gameHistoryFixture),
    }),
  );
  await page.route("**/api/v1/games/102", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(gameDetailFixture),
    }),
  );
}

async function visibleCardRange(page: Page) {
  return page.locator(".leader-track").evaluate((track) => {
    const viewport = track.getBoundingClientRect();
    const positions = [...track.querySelectorAll<HTMLElement>(".leader-card")]
      .filter((card) => {
        const bounds = card.getBoundingClientRect();
        const midpoint = bounds.left + bounds.width / 2;
        return midpoint >= viewport.left && midpoint <= viewport.right;
      })
      .map((card) => Number(card.dataset.position));
    return {
      first: positions[0] ?? 0,
      last: positions.at(-1) ?? 0,
      count: positions.length,
    };
  });
}

async function carouselLabelMatchesViewport(page: Page) {
  const range = await visibleCardRange(page);
  const label = await page.locator(".leader-carousel__toolbar p").textContent();
  const total = await page.locator(".leader-card").count();
  const expected = `Showing cards ${range.first}–${range.last} of ${total} ${total === 1 ? "game" : "games"}`;
  return label === expected;
}

test.beforeEach(async ({ page }) => {
  await mockPublicPages(page);
});

test("comparison explains estimates and keeps the carousel counter truthful", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Comparison ready" })).toBeVisible();
  await expect(page.getByText("Official report", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Calculated", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Estimate", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Lag-adjusted estimate", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/in prizes per \$1 over the long run/).first()).toBeVisible();
  await expect(page.getByText(/per \$\d+ ticket over the long run/).first()).toBeVisible();
  await expect(page.getByText(/prize sample/).first()).toBeVisible();
  await expect(page.getByText("Why rank #1", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/full estimated return comes from the top prize/i).first()).toBeVisible();
  await expect(page.getByText(/model version/i)).toHaveCount(0);

  await expect(page.locator(".leader-card")).toHaveCount(GAME_COUNT);
  await expect.poll(() => carouselLabelMatchesViewport(page)).toBe(true);

  for (const [goal, basis] of [
    [/Practical value/, /return without the top prize/],
    [/Overall value/, /return including all prizes/],
    [/Money back/, /winning exactly the ticket price/],
    [/Come out ahead/, /winning more than the ticket price, excluding the top prize/],
    [/10× upside/, /winning at least 10×, excluding the top prize/],
    [/Jackpot chase/, /winning the top prize/],
  ]) {
    await page.getByRole("radio", { name: goal }).click();
    await expect(page.getByRole("radio", { name: goal })).toBeChecked();
    await expect(page.locator(".leader-card__metric strong").first()).not.toHaveText("");
    await expect(page.locator(".rank-explanation").first()).toContainText(basis);
    await expect.poll(() => carouselLabelMatchesViewport(page)).toBe(true);
  }

  const next = page.getByRole("button", { name: "Show more ranked games" });
  for (let step = 0; step < GAME_COUNT && !(await next.isDisabled()); step += 1) {
    const previousFirst = (await visibleCardRange(page)).first;
    await next.click();
    await expect.poll(async () => (await visibleCardRange(page)).first).toBeGreaterThan(
      previousFirst,
    );
    await expect.poll(() => carouselLabelMatchesViewport(page)).toBe(true);
  }
  await expect(next).toBeDisabled();
  expect((await visibleCardRange(page)).last).toBe(GAME_COUNT);

  const previous = page.getByRole("button", { name: "Show previous ranked games" });
  for (let step = 0; step < GAME_COUNT && !(await previous.isDisabled()); step += 1) {
    const previousFirst = (await visibleCardRange(page)).first;
    await previous.click();
    await expect.poll(async () => (await visibleCardRange(page)).first).toBeLessThan(
      previousFirst,
    );
    await expect.poll(() => carouselLabelMatchesViewport(page)).toBe(true);
  }
  expect((await visibleCardRange(page)).first).toBe(1);

  await page.getByRole("button", { name: "$10", exact: true }).click();
  await expect(page.locator(".leader-card")).toHaveCount(2);
  await expect.poll(() => carouselLabelMatchesViewport(page)).toBe(true);

  const selectedGoal = page.getByRole("radio", { checked: true });
  await selectedGoal.press("ArrowRight");
  await expect(page.getByRole("radio", { name: /Practical value/ })).toBeChecked();

  await page.getByRole("link", { name: "See how the estimates work" }).click();
  await expect(page.getByText(/does not mean one \$10 ticket is likely to pay \$7.42/i)).toBeVisible();

  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
});

test("game detail distinguishes official facts, calculations, and estimates", async ({ page }) => {
  await page.goto("/games/102");

  await expect(page.getByRole("heading", { name: "Lakefront 10X" })).toBeVisible();
  await expect(page.getByText("1 in 3.92", { exact: true })).toBeVisible();
  await expect(page.getByText("About 2,750,001", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "How much estimated return depends on the top prize?" })).toBeVisible();
  await expect(page.getByText("74.2¢ per $1", { exact: true })).toBeVisible();
  await expect(page.getByText("70.4¢ per $1", { exact: true })).toBeVisible();
  await expect(page.getByText("3.8¢ per $1", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: /estimated return comes from prizes below the top tier/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What could one ticket return?" })).toBeVisible();
  await expect(page.getByText("Exactly money back", { exact: true })).toBeVisible();
  await expect(page.getByText("Any ordinary profit", { exact: true })).toBeVisible();
  await expect(page.getByText("At least 5× the ticket price", { exact: true })).toBeVisible();
  await expect(page.getByText("At least 10× the ticket price", { exact: true })).toBeVisible();
  await expect(page.getByText(/do not add these three percentages/i)).toBeVisible();
  await expect(page.getByText("0.00009% estimated chance", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Every prize tier, in one view" })).toBeVisible();
  await expect(page.getByText("24-day working assumption", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("fewer than 300 starting prizes", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Estimated tickets sold" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Prizes claimed by tier" })).toBeVisible();
  await expect(page.getByText(/model version/i)).toHaveCount(0);

  await page.getByText("View exact sales-history data").click();
  await expect(page.getByRole("columnheader", { name: "Estimated sold" })).toBeVisible();
  await page.getByText("View exact selected-tier history").click();
  await expect(page.getByRole("table").last()).toBeVisible();

  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);

  await page.getByRole("link", { name: "Back to comparison" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Comparison ready" })).toBeVisible();
});

test("configured comparison state survives history, detail navigation, and sharing", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://127.0.0.1:4173",
  });
  await page.goto("/?strategy=value_full&price=10#rankings");

  await expect(page.getByRole("radio", { name: /Overall value/ })).toBeChecked();
  await expect(page.getByRole("button", { name: "$10", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.reload();
  await expect(page.getByRole("radio", { name: /Overall value/ })).toBeChecked();

  await page.getByRole("radio", { name: /Money back/ }).click();
  await expect(page).toHaveURL(/strategy=money_back_exact&price=10/);
  await page.goBack();
  await expect(page.getByRole("radio", { name: /Overall value/ })).toBeChecked();
  await expect(page).toHaveURL(/strategy=value_full&price=10/);
  await page.goForward();
  await expect(page.getByRole("radio", { name: /Money back/ })).toBeChecked();
  await page.goBack();

  const lakefront = page.getByRole("link", { name: "View details for Lakefront 10X" }).first();
  await expect(lakefront).toHaveAttribute(
    "href",
    "/games/102?strategy=value_full&price=10",
  );
  await lakefront.click();
  await expect(page).toHaveURL(/\/games\/102\?strategy=value_full&price=10$/);
  await expect(page.getByText("Returns to Overall value · $10 tickets")).toBeVisible();
  await expect(page.locator(".site-header nav a").filter({ hasText: "Compare games" })).toHaveAttribute(
    "href",
    "/?strategy=value_full&price=10#rankings",
  );

  await page.getByRole("button", { name: "Copy this game view" }).click();
  await expect(page.getByText("Game link copied.")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "http://127.0.0.1:4173/games/102?strategy=value_full&price=10",
  );

  await page.getByRole("link", { name: "Back to comparison" }).click();
  await expect(page).toHaveURL(/\?strategy=value_full&price=10#rankings$/);
  await expect(page.getByRole("radio", { name: /Overall value/ })).toBeChecked();
  await expect(page.getByRole("button", { name: "$10", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.getByRole("button", { name: "Copy this view" }).click();
  await expect(page.getByText("Comparison link copied.")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "http://127.0.0.1:4173/?strategy=value_full&price=10#rankings",
  );
});

test("invalid public state falls back and copies a canonical default link", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://127.0.0.1:4173",
  });
  await page.goto("/?strategy=secret_score&price=-10&private=discard-me");

  await expect(page.getByRole("radio", { name: /Practical value/ })).toBeChecked();
  await expect(page.getByRole("button", { name: "All", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Copy this view" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "http://127.0.0.1:4173/#rankings",
  );
});

test("paused comparison uses player language and hides internal reason codes", async ({ page }) => {
  const paused = structuredClone(rankingDatasetFixture);
  paused.status.available = false;
  paused.status.reasonCode = "SOURCE_STALE";
  paused.rankings = [];
  await page.route("**/api/v1/rankings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(paused),
    }),
  );

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Current comparison paused" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "The official prize counts are out of date" })).toBeVisible();
  await expect(page.getByText("SOURCE_STALE", { exact: true })).toHaveCount(0);
});
