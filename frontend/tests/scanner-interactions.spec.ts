import { expect, test } from "@playwright/test";

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

test.describe("scanner interaction guards", () => {
  test("filter interactions do not trigger extra scan endpoint requests", async ({ page }) => {
    test.skip(
      !hasAuth,
      "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run scanner interaction guards."
    );

    await loginIfNeeded(page);

    let scanLatestCalls = 0;
    let scanMarketsCalls = 0;

    await page.route("**/api/scan-latest**", async (route) => {
      scanLatestCalls += 1;
      await route.continue();
    });

    await page.route("**/api/scan-markets**", async (route) => {
      scanMarketsCalls += 1;
      await route.continue();
    });

    await page.goto("/scanner");

    const searchInput = page.getByPlaceholder(/search/i);
    const tutorialScanButton = page.getByRole("button", { name: /reload tutorial lines|run tutorial scan/i });
    const tutorialModeVisible = await tutorialScanButton.isVisible().catch(() => false);

    if (tutorialModeVisible) {
      const scanButton = tutorialScanButton;
      await expect(scanButton).toBeVisible({ timeout: 10000 });
      await scanButton.click();
      const practiceButton = page.getByRole("button", { name: /practice log bet/i }).first();
      await expect(practiceButton).toBeVisible({ timeout: 20000 });

      await page.waitForTimeout(350);
      const tutorialBaselineLatest = scanLatestCalls;
      const tutorialBaselineScan = scanMarketsCalls;

      await practiceButton.click();
      await expect(page.getByRole("heading", { name: "Log Bet" })).toBeVisible({ timeout: 5000 });
      await page.getByRole("button", { name: "Close" }).click();
      await expect(page.getByRole("heading", { name: "Log Bet" })).not.toBeVisible({ timeout: 5000 });

      await page.waitForTimeout(500);

      expect(scanLatestCalls).toBe(tutorialBaselineLatest);
      expect(scanMarketsCalls).toBe(tutorialBaselineScan);
      return;
    }

    const liveScanButton = page.getByRole("button", { name: /find plays|refresh plays/i });
    const searchVisible = await searchInput.isVisible().catch(() => false);
    if (!searchVisible) {
      await expect(liveScanButton).toBeVisible({ timeout: 10000 });
      await liveScanButton.click();
    }

    await expect(searchInput).toBeVisible({ timeout: 20000 });

    await page.waitForTimeout(350);
    const baselineLatest = scanLatestCalls;
    const baselineScan = scanMarketsCalls;

    await searchInput.fill("lakers");
    await page.getByRole("button", { name: "Starting Soon" }).click();
    await page.getByRole("button", { name: /^more$/i }).click();
    await page.getByRole("menuitemradio", { name: "1.5%+" }).click();

    await page.waitForTimeout(500);

    expect(scanLatestCalls).toBe(baselineLatest);
    expect(scanMarketsCalls).toBe(baselineScan);
  });
});
