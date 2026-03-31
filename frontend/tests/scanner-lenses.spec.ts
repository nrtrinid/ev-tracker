import { expect, test } from "@playwright/test";

import { rankScannerSidesByLens } from "@/app/scanner/scanner-lenses";
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

test.describe("scanner lens ranking", () => {
  test("filters to selected books before lens ranking", async () => {
    const results = rankScannerSidesByLens({
      sides: [
        BASE_SIDE,
        { ...BASE_SIDE, sportsbook: "FanDuel", team: "Warriors" },
      ],
      selectedBooks: ["DraftKings"],
      activeLens: "standard",
      boostPercent: 30,
    });

    expect(results).toHaveLength(1);
    expect(results[0].sportsbook).toBe("DraftKings");
  });

  test("standard lens keeps only +EV sides sorted descending", async () => {
    const results = rankScannerSidesByLens({
      sides: [
        { ...BASE_SIDE, team: "A", ev_percentage: 0.5 },
        { ...BASE_SIDE, team: "B", ev_percentage: 3.2 },
        { ...BASE_SIDE, team: "C", ev_percentage: -0.4 },
      ],
      selectedBooks: ["DraftKings"],
      activeLens: "standard",
      boostPercent: 30,
    });

    expect(results.map((s) => s.team)).toEqual(["B", "A"]);
  });

  test("profit boost lens computes and sorts boosted ev", async () => {
    const results = rankScannerSidesByLens({
      sides: [
        { ...BASE_SIDE, team: "A", book_decimal: 2.2, true_prob: 0.5 },
        { ...BASE_SIDE, team: "B", book_decimal: 1.9, true_prob: 0.6 },
      ],
      selectedBooks: ["DraftKings"],
      activeLens: "profit_boost",
      boostPercent: 30,
    });

    expect(results.every((s) => typeof s._boostedEV === "number")).toBeTruthy();
    expect((results[0]._boostedEV ?? 0) >= (results[1]._boostedEV ?? 0)).toBeTruthy();
  });

  test("qualifier lens enforces odds guardrail", async () => {
    const results = rankScannerSidesByLens({
      sides: [
        { ...BASE_SIDE, team: "A", book_odds: -300 },
        { ...BASE_SIDE, team: "B", book_odds: -120 },
        { ...BASE_SIDE, team: "C", book_odds: 180 },
      ],
      selectedBooks: ["DraftKings"],
      activeLens: "qualifier",
      boostPercent: 30,
    });

    expect(results.map((s) => s.team)).toEqual(["B"]);
  });
});
