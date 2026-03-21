import { expect, test } from "@playwright/test";

import {
  buildScannerActionModel,
  normalizeSportsbookDeeplink,
  shouldShowProfitBoostContextControls,
} from "@/app/scanner/scanner-ui-model";

test.describe("scanner ui model", () => {
  test("normalizes only http/https sportsbook deeplinks", async () => {
    expect(normalizeSportsbookDeeplink("https://example.com/bet")).toContain("https://");
    expect(normalizeSportsbookDeeplink("http://example.com/bet")).toContain("http://");
    expect(normalizeSportsbookDeeplink("javascript:alert(1)")).toBeNull();
    expect(normalizeSportsbookDeeplink("not-a-url")).toBeNull();
  });

  test("builds open-first action hierarchy when deeplink exists", async () => {
    const model = buildScannerActionModel({
      sportsbook: "FanDuel",
      sportsbookDeeplinkUrl: "https://sportsbook.example/open/abc",
    });

    expect(model.primary.kind).toBe("open");
    expect(model.primary.label).toBe("Open in FanDuel");
    expect(model.primary.label).not.toMatch(/place bet|bet now|auto bet/i);
    expect(model.secondary?.kind).toBe("log");
    expect(model.secondary?.label).toBe("Log Bet");
    expect(model.trustHint).toBe("Check line before placing");
  });

  test("falls back to log-only hierarchy when deeplink missing", async () => {
    const model = buildScannerActionModel({
      sportsbook: "DraftKings",
      sportsbookDeeplinkUrl: null,
    });

    expect(model.primary.kind).toBe("log");
    expect(model.primary.label).toBe("Log Bet");
    expect(model.secondary).toBeUndefined();
  });

  test("shows profit boost controls only in profit boost lens", async () => {
    expect(shouldShowProfitBoostContextControls("profit_boost")).toBeTruthy();
    expect(shouldShowProfitBoostContextControls("standard")).toBeFalsy();
    expect(shouldShowProfitBoostContextControls("bonus_bet")).toBeFalsy();
    expect(shouldShowProfitBoostContextControls("qualifier")).toBeFalsy();
  });
});
