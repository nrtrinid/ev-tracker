import { expect, test } from "@playwright/test";

const testEmail = process.env.PLAYWRIGHT_TEST_EMAIL;
const testPassword = process.env.PLAYWRIGHT_TEST_PASSWORD;
const hasAuth = !!testEmail && !!testPassword;

const balancesApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/balances(?:\?.*)?$/;
const transactionsApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/transactions(?:\?.*)?$/;
const betsApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/bets(?:\?.*)?$/;
const settingsApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/settings(?:\?.*)?$/;

async function loginIfNeeded(page: import("@playwright/test").Page) {
  if (!hasAuth) return;
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(testEmail!);
  await page.getByLabel(/password/i).fill(testPassword!);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL("/", { timeout: 15000 });
}

test.describe("Bankroll Center", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run the UI verification.");
    await loginIfNeeded(page);
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("opens from the pill and keeps transaction forms inside the drawer", async ({ page }) => {
    const balances = [
      {
        sportsbook: "DraftKings",
        deposits: 150,
        withdrawals: 20,
        adjustments: 0,
        net_deposits: 130,
        profit: 5,
        pending: 35,
        balance: 100,
      },
    ];
    const transactions = [
      {
        id: "tx-1",
        created_at: "2026-04-20T12:00:00Z",
        transaction_date: "2026-04-20T12:00:00Z",
        updated_at: "2026-04-20T12:00:00Z",
        sportsbook: "DraftKings",
        type: "deposit",
        amount: 150,
        notes: "Initial log",
      },
    ];
    const settings = {
      k_factor: 0.78,
      default_stake: null,
      preferred_sportsbooks: ["DraftKings"],
      kelly_multiplier: 0.25,
      bankroll_override: 1000,
      use_computed_bankroll: true,
      theme_preference: "light",
      k_factor_mode: "baseline",
      k_factor_min_stake: 100,
      k_factor_smoothing: 0.5,
      k_factor_clamp_min: 0.6,
      k_factor_clamp_max: 0.9,
      k_factor_observed: null,
      k_factor_weight: 0,
      k_factor_effective: 0.78,
      k_factor_bonus_stake_settled: 0,
      onboarding_state: null,
    };

    await page.route(balancesApiPattern, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(balances) });
    });
    await page.route(transactionsApiPattern, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "tx-2",
            created_at: "2026-04-21T12:00:00Z",
            transaction_date: "2026-04-21T12:00:00Z",
            updated_at: "2026-04-21T12:00:00Z",
            sportsbook: "DraftKings",
            type: "withdrawal",
            amount: 50,
            notes: null,
          }),
        });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(transactions) });
    });
    await page.route(betsApiPattern, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    });
    await page.route(settingsApiPattern, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(settings) });
    });

    await page.goto("/bets/stats");
    await page.getByTestId("bankroll-center-pill").click();

    const drawer = page.getByTestId("bankroll-details-sheet");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("Total bankroll")).toBeVisible();
    await drawer.getByRole("button", { name: /DraftKings/ }).click();
    await expect(drawer.getByRole("button", { name: "Log Withdrawal" })).toBeVisible();

    await drawer.getByRole("button", { name: "Log Withdrawal" }).click();
    await expect(drawer.getByRole("heading", { name: "Log Withdrawal" })).toBeVisible();
    await drawer.getByLabel("Amount").fill("120");
    await expect(drawer.getByText("Withdrawal would make the tracked balance negative.")).toBeVisible();

    await drawer.getByLabel("Amount").fill("50");
    await drawer.getByRole("button", { name: "Log Withdrawal" }).click();
    await expect(drawer.getByRole("heading", { name: "DraftKings" })).toBeVisible();
  });
});
