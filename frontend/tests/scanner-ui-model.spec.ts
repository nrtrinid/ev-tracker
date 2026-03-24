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
    expect(normalizeSportsbookDeeplink("https://sports.{state}.betmgm.com/en/sports")).toBeNull();
  });

  test("builds selection-level open-first action hierarchy", async () => {
    const model = buildScannerActionModel({
      sportsbook: "FanDuel",
      sportsbookDeeplinkUrl: "https://sportsbook.example/open/abc",
      sportsbookDeeplinkLevel: "selection",
    });

    expect(model.primary.kind).toBe("open");
    expect(model.primary.label).toBe("Place at FanDuel");
    expect(model.primary.label).not.toMatch(/bet now|auto bet/i);
    expect(model.secondary?.kind).toBe("log");
    expect(model.secondary?.label).toBe("Review & Log");
    expect(model.trustHint).toBe("Place the ticket at the book, then come back here to log it.");
  });

  test("builds destination-aware event action hierarchy", async () => {
    const model = buildScannerActionModel({
      sportsbook: "DraftKings",
      sportsbookDeeplinkUrl: "https://sportsbook.example/event/abc",
      sportsbookDeeplinkLevel: "event",
    });

    expect(model.primary.kind).toBe("open");
    expect(model.primary.label).toBe("Open Event at DraftKings");
    expect(model.secondary?.label).toBe("Review & Log");
    expect(model.trustHint).toBe("This opens the event at the book, so find the line there before you log it.");
  });

  test("builds destination-aware homepage action hierarchy", async () => {
    const model = buildScannerActionModel({
      sportsbook: "BetMGM",
      sportsbookDeeplinkUrl: "https://sports.betmgm.com/",
      sportsbookDeeplinkLevel: "homepage",
    });

    expect(model.primary.kind).toBe("open");
    expect(model.primary.label).toBe("Open BetMGM");
    expect(model.secondary?.label).toBe("Review & Log");
    expect(model.trustHint).toBe("This opens the sportsbook home page, so navigate to the game before you log it.");
  });

  test("falls back to log-only hierarchy when deeplink missing", async () => {
    const model = buildScannerActionModel({
      sportsbook: "DraftKings",
      sportsbookDeeplinkUrl: null,
    });

    expect(model.primary.kind).toBe("log");
    expect(model.primary.label).toBe("Review & Log");
    expect(model.secondary).toBeUndefined();
  });

  test("defaults legacy deeplink payloads to event-level copy", async () => {
    const model = buildScannerActionModel({
      sportsbook: "DraftKings",
      sportsbookDeeplinkUrl: "https://sportsbook.example/event/legacy",
    });

    expect(model.primary.kind).toBe("open");
    expect(model.primary.label).toBe("Open Event at DraftKings");
  });

  test("shows profit boost controls only in profit boost lens", async () => {
    expect(shouldShowProfitBoostContextControls("profit_boost")).toBeTruthy();
    expect(shouldShowProfitBoostContextControls("standard")).toBeFalsy();
    expect(shouldShowProfitBoostContextControls("bonus_bet")).toBeFalsy();
    expect(shouldShowProfitBoostContextControls("qualifier")).toBeFalsy();
  });
});
