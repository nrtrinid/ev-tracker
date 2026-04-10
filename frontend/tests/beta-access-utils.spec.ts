import { expect, test } from "@playwright/test";

import {
  betaInviteCodeEnabled,
  normalizeInviteCode,
} from "@/lib/server/beta-access-utils";

test.describe("beta access utilities", () => {
  test("normalizeInviteCode ignores spacing, punctuation, and case", async () => {
    expect(normalizeInviteCode(" Daily-Drop ")).toBe("dailydrop");
    expect(normalizeInviteCode("DAILY drop!!")).toBe("dailydrop");
  });

  test("betaInviteCodeEnabled is false when no code is configured", async () => {
    expect(betaInviteCodeEnabled(undefined)).toBeFalsy();
    expect(betaInviteCodeEnabled("   ")).toBeFalsy();
  });

  test("betaInviteCodeEnabled is true for easy-to-share code words", async () => {
    expect(betaInviteCodeEnabled("dailydrop")).toBeTruthy();
    expect(betaInviteCodeEnabled("Daily Drop")).toBeTruthy();
  });
});
