import { test, expect, type Page } from "@playwright/test";

const testEmail = process.env.PLAYWRIGHT_TEST_EMAIL;
const testPassword = process.env.PLAYWRIGHT_TEST_PASSWORD;
const hasAuth = !!testEmail && !!testPassword;

async function loginIfNeeded(page: Page) {
  if (!hasAuth) return;
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(testEmail!);
  await page.getByLabel(/password/i).fill(testPassword!);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL("/", { timeout: 15000 });
}

async function mockScannerLatest(page: Page, payload: unknown) {
  await page.route("**/api/scan-latest*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
}

test.describe("scanner deeplinks", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run scanner deeplink tests.");
    await loginIfNeeded(page);
  });

  test("renders selection and homepage sportsbook CTAs with the correct labels and hrefs", async ({ page }) => {
    await mockScannerLatest(page, {
      sport: "basketball_nba",
      sides: [
        {
          surface: "straight_bets",
          sportsbook: "DraftKings",
          sportsbook_deeplink_url: "https://sportsbook.example/dk/add",
          sportsbook_deeplink_level: "selection",
          sport: "basketball_nba",
          event: "Lakers @ Warriors",
          commence_time: "2026-01-15T00:30:00Z",
          team: "Los Angeles Lakers",
          pinnacle_odds: 112,
          book_odds: 130,
          true_prob: 0.465,
          base_kelly_fraction: 0.04,
          book_decimal: 2.3,
          ev_percentage: 3.9,
        },
        {
          surface: "straight_bets",
          sportsbook: "FanDuel",
          sportsbook_deeplink_url: "https://sportsbook.example/fd",
          sportsbook_deeplink_level: "homepage",
          sport: "basketball_nba",
          event: "Celtics @ Knicks",
          commence_time: "2026-01-15T02:30:00Z",
          team: "Boston Celtics",
          pinnacle_odds: 105,
          book_odds: 118,
          true_prob: 0.49,
          base_kelly_fraction: 0.03,
          book_decimal: 2.18,
          ev_percentage: 2.1,
        },
      ],
      events_fetched: 2,
      events_with_both_books: 2,
      api_requests_remaining: "499",
      scanned_at: "2026-01-14T18:00:00Z",
    });

    await page.goto("/scanner");

    const draftKingsCard = page.locator(".card-hover").filter({ hasText: "Los Angeles Lakers" }).first();
    await expect(draftKingsCard).toBeVisible({ timeout: 10000 });
    await expect(draftKingsCard.getByRole("link", { name: /Place at DraftKings/i })).toHaveAttribute(
      "href",
      "https://sportsbook.example/dk/add"
    );
    await expect(draftKingsCard.getByRole("button", { name: /Review & Log/i })).toBeVisible();

    const fanDuelCard = page.locator(".card-hover").filter({ hasText: "Boston Celtics" }).first();
    await expect(fanDuelCard).toBeVisible({ timeout: 10000 });
    await expect(fanDuelCard.getByRole("link", { name: /^Open FanDuel$/i })).toHaveAttribute(
      "href",
      "https://sportsbook.example/fd"
    );
    await expect(fanDuelCard.getByRole("button", { name: /Review & Log/i })).toBeVisible();
  });
});
