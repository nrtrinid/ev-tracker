import { test, expect } from "@playwright/test";

/**
 * Smoke tests need an authenticated session. Playwright uses a fresh browser context per run,
 * so "log in once manually" does not persist. Either:
 * - Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD in the environment; the tests
 *   will log in via the login page before each run.
 * - Or tests will skip with a clear message.
 */
const testEmail = process.env.PLAYWRIGHT_TEST_EMAIL;
const testPassword = process.env.PLAYWRIGHT_TEST_PASSWORD;
const hasAuth = !!testEmail && !!testPassword;

async function loginIfNeeded(page: import("@playwright/test").Page) {
  if (!hasAuth) return;
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(testEmail!);
  await page.getByLabel(/password/i).fill(testPassword!);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL("/", { timeout: 15000 });
}

test.describe("smoke", () => {
  test.beforeEach(async ({ page }) => {
    if (hasAuth) await loginIfNeeded(page);
  });

  test("authenticated landing shows Log Bet", async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run smoke tests.");
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Log Bet/i })).toBeVisible({ timeout: 10000 });
  });

  test("log bet then settle as win and see confirmation", async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run smoke tests.");
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Log Bet/i }).first()).toBeVisible({ timeout: 10000 });

    // Open Log Bet drawer
    await page.getByRole("button", { name: /Log Bet/i }).first().click();
    await expect(page.getByRole("heading", { name: "Log Bet" })).toBeVisible({ timeout: 5000 });

    // Fill minimal fields: Sportsbook, Sport, Odds, Stake, Market (Promo defaults to Standard)
    await page.getByRole("button", { name: "DraftKings" }).click();
    await page.getByRole("button", { name: "NFL" }).click();
    await page.getByPlaceholder("150").fill("100");
    await page.getByPlaceholder("$25").fill("10");
    await page.getByRole("button", { name: "ML", exact: true }).click();

    // Submit (second "Log Bet" is the submit inside the drawer)
    await page.getByRole("button", { name: "Log Bet" }).last().click();

    // Drawer closes and toast or list updates
    await expect(page.getByRole("heading", { name: "Log Bet" })).not.toBeVisible({ timeout: 5000 });

    // Find the first pending bet and click "Won" to settle
    const wonButton = page.getByRole("button", { name: "Won" }).first();
    await expect(wonButton).toBeVisible({ timeout: 10000 });
    await wonButton.click();

    // Toast or UI shows win confirmation
    await expect(page.getByText(/Marked as Win|profit/i)).toBeVisible({ timeout: 5000 });
  });
});
