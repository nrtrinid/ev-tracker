import { expect, test } from "@playwright/test";

import {
  buildScannerLogBetInitialValues,
  parseScannerCustomBoostInput,
  toggleScannerBookSelection,
} from "@/app/scanner/scanner-state-utils";
import type { MarketSide } from "@/lib/types";

const BASE_SIDE: MarketSide = {
  event_id: "evt-1",
  sportsbook: "DraftKings",
  sport: "basketball_nba",
  event: "Lakers @ Warriors",
  commence_time: "2026-03-21T01:00:00Z",
  team: "Lakers",
  pinnacle_odds: 108,
  book_odds: 130,
  true_prob: 0.48,
  base_kelly_fraction: 0.025,
  book_decimal: 2.3,
  ev_percentage: 2.4,
  scanner_duplicate_state: "new",
  best_logged_odds_american: null,
  current_odds_american: 130,
  matched_pending_bet_id: null,
};

test.describe("scanner state utils", () => {
  test("toggleScannerBookSelection keeps at least one selected book", async () => {
    expect(toggleScannerBookSelection(["DraftKings"], "DraftKings")).toEqual(["DraftKings"]);
    expect(toggleScannerBookSelection(["DraftKings", "FanDuel"], "FanDuel")).toEqual([
      "DraftKings",
    ]);
    expect(toggleScannerBookSelection(["DraftKings"], "FanDuel")).toEqual([
      "DraftKings",
      "FanDuel",
    ]);
  });

  test("parseScannerCustomBoostInput enforces bounds", async () => {
    expect(parseScannerCustomBoostInput("30")).toBe(30);
    expect(parseScannerCustomBoostInput("0")).toBeNull();
    expect(parseScannerCustomBoostInput("201")).toBeNull();
    expect(parseScannerCustomBoostInput("abc")).toBeNull();
  });

  test("buildScannerLogBetInitialValues maps profit boost lens", async () => {
    const out = buildScannerLogBetInitialValues({
      side: BASE_SIDE,
      activeLens: "profit_boost",
      boostPercent: 30,
      sportDisplayMap: { basketball_nba: "NBA" },
      kellyMultiplier: 1,
      bankroll: 1000,
    });

    expect(out.promo_type).toBe("boost_custom");
    expect(out.boost_percent).toBe(30);
    expect(out.sport).toBe("NBA");
    expect(out.current_odds_american).toBe(130);
  });

  test("buildScannerLogBetInitialValues maps bonus bet lens", async () => {
    const out = buildScannerLogBetInitialValues({
      side: BASE_SIDE,
      activeLens: "bonus_bet",
      boostPercent: 50,
      sportDisplayMap: {},
      kellyMultiplier: 1,
      bankroll: 1000,
    });

    expect(out.promo_type).toBe("bonus_bet");
    expect(out.boost_percent).toBeUndefined();
  });
});
