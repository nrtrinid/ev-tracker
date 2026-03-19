import { test, expect } from "@playwright/test";

const email = process.env.PLAYWRIGHT_NON_ADMIN_EMAIL;
const password = process.env.PLAYWRIGHT_NON_ADMIN_PASSWORD;
const hasNonAdminCreds = !!email && !!password;

async function loginAsNonAdmin(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email!);
  await page.getByLabel(/password/i).fill(password!);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL("/", { timeout: 15000 });
}

test.describe("operator access control", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!hasNonAdminCreds, "Set PLAYWRIGHT_NON_ADMIN_EMAIL and PLAYWRIGHT_NON_ADMIN_PASSWORD to run access tests.");
    await loginAsNonAdmin(page);
  });

  test("non-admin cannot access /admin/ops page", async ({ page }) => {
    await page.goto("/admin/ops");

    // notFound() should return Next.js 404 surface.
    await expect(page.getByText(/404|not found|could not be found/i).first()).toBeVisible({ timeout: 10000 });
  });

  test("non-admin cannot call /api/ops/status bridge directly", async ({ page }) => {
    const response = await page.request.get("/api/ops/status");

    expect([401, 403]).toContain(response.status());
    const body = await response.json().catch(() => ({}));
    expect(String(body.error || "").length).toBeGreaterThan(0);
  });
});
