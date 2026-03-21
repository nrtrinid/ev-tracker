import { expect, test } from "@playwright/test";

import {
  buildParlayCartLeg,
  buildScannerLogBetInitialValues,
  parseScannerCustomBoostInput,
  toggleScannerBookSelection,
} from "@/app/scanner/scanner-state-utils";
import type { MarketSide } from "@/lib/types";

const BASE_SIDE: MarketSide = {
  surface: "straight_bets",
  event_id: "evt-1",
  market_key: "h2h",
  selection_key: "evt-1:lakers",
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

const BASE_PROP_SIDE: MarketSide = {
  surface: "player_props",
  event_id: "evt-2",
  market_key: "player_points",
  selection_key: "evt-2|player_points|jokic|over|24.5",
  sportsbook: "FanDuel",
  sport: "basketball_nba",
  event: "Nuggets @ Suns",
  commence_time: "2026-03-21T03:00:00Z",
  market: "player_points",
  player_name: "Nikola Jokic",
  participant_id: null,
  team: "Nuggets",
  opponent: "Suns",
  selection_side: "over",
  line_value: 24.5,
  display_name: "Nikola Jokic Over 24.5",
  pinnacle_odds: -110,
  book_odds: 105,
  true_prob: 0.52,
  base_kelly_fraction: 0.022,
  book_decimal: 2.05,
  ev_percentage: 6.6,
  scanner_duplicate_state: "new",
  best_logged_odds_american: null,
  current_odds_american: 105,
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

  test("buildScannerLogBetInitialValues maps player props identity fields", async () => {
    const out = buildScannerLogBetInitialValues({
      side: BASE_PROP_SIDE,
      activeLens: "standard",
      boostPercent: 30,
      sportDisplayMap: { basketball_nba: "NBA" },
      kellyMultiplier: 1,
      bankroll: 1000,
    });

    expect(out.surface).toBe("player_props");
    expect(out.market).toBe("Prop");
    expect(out.participant_name).toBe("Nikola Jokic");
    expect(out.source_market_key).toBe("player_points");
    expect(out.source_selection_key).toBe("evt-2|player_points|jokic|over|24.5");
  });

  test("buildParlayCartLeg builds stable ids for props", async () => {
    const out = buildParlayCartLeg(BASE_PROP_SIDE);

    expect(out.surface).toBe("player_props");
    expect(out.marketKey).toBe("player_points");
    expect(out.selectionKey).toBe("evt-2|player_points|jokic|over|24.5");
    expect(out.display).toBe("Nikola Jokic Over 24.5");
  });
});
