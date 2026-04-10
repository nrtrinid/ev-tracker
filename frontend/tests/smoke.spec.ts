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
const settingsApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/settings$/;

type MockOnboardingState = {
  version: number;
  completed: string[];
  dismissed: string[];
  last_seen_at: string;
};

async function loginIfNeeded(page: import("@playwright/test").Page) {
  if (!hasAuth) return;
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(testEmail!);
  await page.getByLabel(/password/i).fill(testPassword!);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL("/", { timeout: 15000 });
}

async function installSettingsOnboardingMock(page: import("@playwright/test").Page) {
  let mockedOnboardingState: MockOnboardingState | null = null;
  let baseSettings: Record<string, unknown> | null = null;

  await page.route(settingsApiPattern, async (route) => {
    const method = route.request().method();

    if (method === "GET") {
      const response = await route.fetch();
      const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      baseSettings = data;
      await route.fulfill({
        response,
        json: mockedOnboardingState
          ? { ...data, onboarding_state: mockedOnboardingState }
          : data,
      });
      return;
    }

    if (method === "PATCH") {
      try {
        const payload = route.request().postDataJSON() as { onboarding_state?: MockOnboardingState };
        if (payload?.onboarding_state) {
          mockedOnboardingState = payload.onboarding_state;
        }
      } catch {
        // Ignore malformed payloads in test setup and fall through to the current mocked state.
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...(baseSettings ?? {}),
          onboarding_state:
            mockedOnboardingState ??
            (baseSettings?.onboarding_state as MockOnboardingState | undefined) ?? {
              version: 1,
              completed: [],
              dismissed: [],
              last_seen_at: new Date().toISOString(),
            },
        }),
      });
      return;
    }

    await route.continue();
  });

  return {
    setState(completed: string[], dismissed: string[]) {
      mockedOnboardingState = {
        version: 1,
        completed,
        dismissed,
        last_seen_at: new Date().toISOString(),
      };
    },
  };
}

async function syncLocalOnboardingState(
  page: import("@playwright/test").Page,
  completed: string[],
  dismissed: string[]
) {
  await page.evaluate(
    ({ nextCompleted, nextDismissed }) => {
      const prefix = "ev-tracker-betting-platform";
      const matchingKeys = Object.keys(window.localStorage).filter((key) =>
        key.startsWith(`${prefix}:`)
      );
      const keysToUpdate = matchingKeys.length > 0 ? matchingKeys : [`${prefix}:guest`];

      for (const key of keysToUpdate) {
        const raw = window.localStorage.getItem(key);
        const parsed = raw ? JSON.parse(raw) : {};
        window.localStorage.setItem(
          key,
          JSON.stringify({
            ...parsed,
            tutorialSession: null,
            scannerReviewCandidate: null,
            onboardingCompleted: nextCompleted,
            onboardingDismissed: nextDismissed,
          })
        );
      }
    },
    {
      nextCompleted: completed,
      nextDismissed: dismissed,
    }
  );
}

async function resetOnboarding(page: import("@playwright/test").Page) {
  const settingsMock = await installSettingsOnboardingMock(page);
  settingsMock.setState([], []);
  await page.goto("/");
  await syncLocalOnboardingState(page, [], []);
  await page.reload();
}

test.describe("smoke", () => {
  test.beforeEach(async ({ page }) => {
    if (hasAuth) await loginIfNeeded(page);
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
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

    // Fill minimal fields: Sportsbook, Sport, Odds, Stake.
    // Quick Log defaults to a standard moneyline bet unless setup is expanded.
    await page.getByRole("button", { name: "DraftKings" }).click();
    await page.getByRole("button", { name: "NFL" }).click();
    await page.getByPlaceholder("150").fill("100");
    await page.getByPlaceholder("$25").fill("10");

    // Submit (second "Log Bet" is the submit inside the drawer)
    await page.getByRole("button", { name: "Log Bet" }).last().click();

    const drawerHeading = page.getByRole("heading", { name: "Log Bet" });
    const closeDrawerButton = page.getByRole("button", { name: "Close" });
    await expect
      .poll(async () => {
        const drawerVisible = await drawerHeading.isVisible().catch(() => false);
        const successVisible = await page.getByText(/Bet logged!/i).isVisible().catch(() => false);
        return drawerVisible || successVisible;
      }, { timeout: 10000 })
      .toBe(true);

    if (await drawerHeading.isVisible().catch(() => false)) {
      await closeDrawerButton.click();
      await expect(drawerHeading).not.toBeVisible({ timeout: 5000 });
    }

    // Find the first open bet and click "Mark Win" to settle
    const markWinButton = page.getByRole("button", { name: "Mark Win" }).first();
    await expect(markWinButton).toBeVisible({ timeout: 10000 });
    await markWinButton.click();

    // Toast or UI shows win confirmation
    await expect(page.getByText(/Marked as Win/i)).toBeVisible({ timeout: 5000 });
  });

  test("straight-bets tutorial runs as a local practice loop", async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run smoke tests.");

    await resetOnboarding(page);

    await page.goto("/");
    await expect(page.getByRole("button", { name: /Start Walkthrough/i })).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /Start Walkthrough/i }).click();

    await expect(page.getByText(/Simulated Daily Drops Board/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /Practice Log Ticket/i }).first()).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /Practice Log Ticket/i }).first().click();

    await expect(page.getByRole("heading", { name: "Log Bet" })).toBeVisible({ timeout: 5000 });
    await page.getByPlaceholder("150").fill("132");
    await page.getByPlaceholder("$25").fill("10");
    await page.getByRole("button", { name: /Save Practice Ticket/i }).click();
    await expect(page.getByRole("heading", { name: "Log Bet" })).not.toBeVisible({ timeout: 10000 });

    await page.getByRole("link", { name: /^Bets$/i }).click();
    await expect(page).toHaveURL(/\/bets/, { timeout: 10000 });
    await expect(page.getByText(/Tutorial Practice Ticket/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /Finish Tutorial/i })).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /Finish Tutorial/i }).click();

    await expect(page).toHaveURL(/\/?\?onboarding=complete/, { timeout: 10000 });
    await expect(page.getByText(/Tutorial Complete/i).first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /Start Walkthrough/i })).not.toBeVisible({ timeout: 10000 });

    await page.goto("/bets");
    await expect(page.getByText(/Tutorial Practice Ticket/i)).not.toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /Finish Tutorial/i })).not.toBeVisible({ timeout: 10000 });
  });

  test("beginner guidance appears across home, scanner, and parlay", async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run smoke tests.");

    await resetOnboarding(page);

    await page.goto("/");
    await expect(page.getByRole("button", { name: /Start Walkthrough/i })).toBeVisible({ timeout: 10000 });

    await page.goto("/scanner");
    await expect(page.getByRole("button", { name: /Run Tutorial Scan/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /Standard EV/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByPlaceholder(/search/i)).toBeVisible({ timeout: 10000 });

    await page.goto("/parlay");
    await expect(page.getByText(/Optional Step/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("heading", { name: /Parlay Builder/i })).toBeVisible({ timeout: 10000 });
  });

  test("skipping the tutorial clears onboarding cards", async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run smoke tests.");

    await resetOnboarding(page);

    await page.goto("/");
    await expect(page.getByRole("button", { name: /Start Walkthrough/i })).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /Hide coach/i }).click();

    await expect(page.getByRole("button", { name: /Start Walkthrough/i })).not.toBeVisible({ timeout: 10000 });
    await page.reload();
    await expect(page.getByRole("button", { name: /Start Walkthrough/i })).not.toBeVisible({ timeout: 10000 });

    await page.goto("/scanner");
    await expect(page.getByRole("button", { name: /Reload Tutorial Lines|Run Tutorial Scan/i })).not.toBeVisible({ timeout: 10000 });
  });
});
