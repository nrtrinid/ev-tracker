import { expect, test } from "@playwright/test";

import {
  buildParlayCartLeg,
  buildParlayCartLegFromPickEmCard,
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
  reference_odds: -110,
  reference_source: "market_median",
  reference_bookmakers: ["bovada", "betmgm"],
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

const BASE_SPREAD_SIDE: MarketSide = {
  ...BASE_SIDE,
  market_key: "spreads",
  selection_key: "evt-1|spreads|lakers|+4.5",
  team: "Lakers",
  selection_side: "home",
  line_value: 4.5,
};

const BASE_TOTAL_SIDE: MarketSide = {
  ...BASE_SIDE,
  market_key: "totals",
  selection_key: "evt-1|totals|over|221.5",
  team: "Over",
  selection_side: "over",
  line_value: 221.5,
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

  test("buildScannerLogBetInitialValues preserves spread line metadata", async () => {
    const out = buildScannerLogBetInitialValues({
      side: BASE_SPREAD_SIDE,
      activeLens: "standard",
      boostPercent: 30,
      sportDisplayMap: { basketball_nba: "NBA" },
      kellyMultiplier: 1,
      bankroll: 1000,
    });

    expect(out.event).toBe("Lakers +4.5");
    expect(out.market).toBe("Spread");
    expect(out.selection_side).toBe("Lakers");
    expect(out.line_value).toBe(4.5);
    expect(out.source_market_key).toBe("spreads");
  });

  test("buildScannerLogBetInitialValues preserves totals metadata", async () => {
    const out = buildScannerLogBetInitialValues({
      side: BASE_TOTAL_SIDE,
      activeLens: "standard",
      boostPercent: 30,
      sportDisplayMap: { basketball_nba: "NBA" },
      kellyMultiplier: 1,
      bankroll: 1000,
    });

    expect(out.event).toBe("Game Total Over 221.5");
    expect(out.market).toBe("Total");
    expect(out.selection_side).toBe("over");
    expect(out.line_value).toBe(221.5);
  });

  test("buildParlayCartLeg builds stable ids for props", async () => {
    const out = buildParlayCartLeg(BASE_PROP_SIDE);

    expect(out.surface).toBe("player_props");
    expect(out.marketKey).toBe("player_points");
    expect(out.selectionKey).toBe("evt-2|player_points|jokic|over|24.5");
    expect(out.display).toBe("Nikola Jokic Over 24.5");
    expect(out.referenceOddsAmerican).toBe(-110);
    expect(out.referenceSource).toBe("market_median");
    expect(out.participantName).toBe("Nikola Jokic");
    expect(out.marketDisplay).toBe("player_points");
  });

  test("buildParlayCartLeg carries reference pricing for straight bets", async () => {
    const out = buildParlayCartLeg(BASE_SIDE);

    expect(out.surface).toBe("straight_bets");
    expect(out.referenceOddsAmerican).toBe(108);
    expect(out.referenceTrueProbability).toBe(0.48);
    expect(out.referenceSource).toBe("pinnacle");
    expect(out.team).toBe("Lakers");
    expect(out.marketDisplay).toBe("Moneyline");
  });

  test("buildParlayCartLeg uses de-vigged true probability for straight-bet fair odds", async () => {
    const out = buildParlayCartLeg({
      ...BASE_SIDE,
      book_odds: 250,
      pinnacle_odds: 227,
      true_prob: 100 / 340,
      book_decimal: 3.5,
    });

    expect(out.referenceOddsAmerican).toBe(240);
    expect(out.referenceTrueProbability).toBeCloseTo(100 / 340, 8);
    expect(out.selectionMeta).toMatchObject({ rawPinnacleOdds: 227 });
  });

  test("buildParlayCartLeg formats spread and total legs distinctly", async () => {
    const spreadLeg = buildParlayCartLeg(BASE_SPREAD_SIDE);
    const totalLeg = buildParlayCartLeg(BASE_TOTAL_SIDE);

    expect(spreadLeg.display).toBe("Lakers +4.5");
    expect(spreadLeg.marketDisplay).toBe("Spread");
    expect(spreadLeg.selectionSide).toBe("Lakers");

    expect(totalLeg.display).toBe("Game Total Over 221.5");
    expect(totalLeg.marketDisplay).toBe("Total");
    expect(totalLeg.selectionSide).toBe("over");
    expect(totalLeg.lineValue).toBe(221.5);
  });

  test("buildParlayCartLegFromPickEmCard maps consensus winner into a pick'em slip leg", async () => {
    const out = buildParlayCartLegFromPickEmCard({
      comparison_key: "evt-2|player_points|jokic|24.5",
      event_id: "evt-2",
      sport: "basketball_nba",
      event: "Nuggets @ Suns",
      commence_time: "2026-03-21T03:00:00Z",
      player_name: "Nikola Jokic",
      participant_id: "pp-123",
      team: "Nuggets",
      opponent: "Suns",
      market_key: "player_points",
      market: "player_points",
      line_value: 24.5,
      exact_line_bookmakers: ["FanDuel", "BetMGM"],
      exact_line_bookmaker_count: 2,
      consensus_over_prob: 0.57,
      consensus_under_prob: 0.43,
      consensus_side: "over",
      confidence_label: "solid",
      best_over_sportsbook: "FanDuel",
      best_over_odds: 105,
      best_over_deeplink_url: "https://example.com/over",
      best_under_sportsbook: "BetMGM",
      best_under_odds: -120,
      best_under_deeplink_url: "https://example.com/under",
    });

    expect(out).not.toBeNull();
    expect(out?.sportsbook).toBe("FanDuel");
    expect(out?.selectionSide).toBe("over");
    expect(out?.referenceSource).toBe("pickem_consensus");
    expect(out?.selectionMeta).toMatchObject({
      pickEmComparisonKey: "evt-2|player_points|jokic|24.5",
      sportsbookDeeplinkUrl: "https://example.com/over",
    });
  });
});
