import { test, expect } from "@playwright/test";

import {
  evaluateAdminAccess,
  parseAdminAllowlist,
} from "@/lib/server/admin-access-utils";

test.describe("admin access utilities", () => {
  test("parseAdminAllowlist normalizes case/spacing and drops empties", async () => {
    const parsed = parseAdminAllowlist(" Admin@One.com, ,ops@example.com ,TEAM@EXAMPLE.COM");

    expect(parsed).toEqual([
      "admin@one.com",
      "ops@example.com",
      "team@example.com",
    ]);
  });

  test("evaluateAdminAccess fails closed when allowlist is empty", async () => {
    const decision = evaluateAdminAccess("ops@example.com", []);

    expect(decision.ok).toBeFalsy();
    expect(decision.error).toBe("allowlist_not_configured");
  });

  test("evaluateAdminAccess denies non-admin users", async () => {
    const decision = evaluateAdminAccess("user@example.com", ["ops@example.com"]);

    expect(decision.ok).toBeFalsy();
    expect(decision.error).toBe("forbidden");
  });

  test("evaluateAdminAccess allows normalized admin match", async () => {
    const decision = evaluateAdminAccess("Ops@Example.Com", ["ops@example.com"]);

    expect(decision.ok).toBeTruthy();
    expect(decision.error).toBeUndefined();
  });
});
