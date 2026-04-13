import { expect, test } from "@playwright/test";

import { getTrackerSettlementState } from "@/lib/tracker-settlement-state";
import type { Bet } from "@/lib/types";

function buildBet(overrides: Partial<Bet> = {}): Bet {
  return {
    id: "bet-1",
    created_at: "2026-04-10T00:00:00Z",
    event_date: "2026-04-10",
    settled_at: null,
    sport: "NBA",
    event: "Lakers @ Warriors",
    market: "ML",
    surface: "straight_bets",
    sportsbook: "FanDuel",
    promo_type: "standard",
    odds_american: 130,
    odds_decimal: 2.3,
    stake: 10,
    boost_percent: null,
    winnings_cap: null,
    payout_override: null,
    notes: null,
    opposing_odds: null,
    result: "pending",
    win_payout: 23,
    ev_per_dollar: 0.05,
    ev_total: 0.5,
    real_profit: null,
    pinnacle_odds_at_entry: 120,
    latest_pinnacle_odds: null,
    latest_pinnacle_updated_at: null,
    pinnacle_odds_at_close: null,
    clv_updated_at: null,
    commence_time: "2026-04-11T02:00:00Z",
    clv_team: "Lakers",
    clv_sport_key: "basketball_nba",
    clv_event_id: "evt-1",
    true_prob_at_entry: 0.48,
    clv_ev_percent: null,
    beat_close: null,
    is_paper: false,
    strategy_cohort: null,
    auto_logged: false,
    auto_log_run_at: null,
    auto_log_run_key: null,
    scan_ev_percent_at_log: null,
    book_odds_at_log: null,
    reference_odds_at_log: null,
    source_event_id: null,
    source_market_key: null,
    source_selection_key: null,
    participant_name: null,
    participant_id: null,
    selection_side: null,
    line_value: null,
    selection_meta: null,
    ...overrides,
  };
}

test.describe("tracker settlement state", () => {
  test("treats unsupported straight markets as manual-only", async () => {
    const state = getTrackerSettlementState(
      buildBet({
        market: "Spread",
        commence_time: "2026-04-10T22:00:00Z",
      }),
      new Date("2026-04-10T23:00:00Z"),
    );

    expect(state.kind).toBe("manual_only");
    expect(state.showManualControlsByDefault).toBe(true);
  });

  test("keeps upcoming moneyline bets in the auto-settle state", async () => {
    const state = getTrackerSettlementState(
      buildBet({
        commence_time: "2026-04-11T02:00:00Z",
      }),
      new Date("2026-04-11T00:00:00Z"),
    );

    expect(state.kind).toBe("awaiting_auto_settle");
    expect(state.title).toBe("Open ticket");
    expect(state.showManualControlsByDefault).toBe(false);
  });

  test("escalates stale auto-settle bets into needs-grading", async () => {
    const state = getTrackerSettlementState(
      buildBet({
        commence_time: "2026-04-09T00:00:00Z",
      }),
      new Date("2026-04-10T20:00:00Z"),
    );

    expect(state.kind).toBe("needs_grading");
    expect(state.showManualControlsByDefault).toBe(true);
  });

  test("uses the latest parlay leg time before escalating", async () => {
    const state = getTrackerSettlementState(
      buildBet({
        market: "Parlay",
        surface: "parlay",
        commence_time: null,
        clv_team: null,
        clv_sport_key: null,
        selection_meta: {
          type: "parlay",
          legs: [
            {
              id: "leg-1",
              surface: "straight_bets",
              eventId: "evt-1",
              marketKey: "h2h",
              selectionKey: "evt-1:lakers",
              sportsbook: "FanDuel",
              oddsAmerican: 130,
              referenceOddsAmerican: 120,
              referenceSource: "pinnacle",
              display: "Lakers ML",
              event: "Lakers @ Warriors",
              sport: "basketball_nba",
              commenceTime: "2026-04-09T01:00:00Z",
              correlationTags: [],
            },
            {
              id: "leg-2",
              surface: "player_props",
              eventId: "evt-2",
              marketKey: "player_points",
              selectionKey: "evt-2|player_points|jokic|over|24.5",
              sportsbook: "FanDuel",
              oddsAmerican: 105,
              referenceOddsAmerican: -110,
              referenceSource: "median",
              display: "Nikola Jokic Over 24.5",
              event: "Nuggets @ Suns",
              sport: "basketball_nba",
              commenceTime: "2026-04-10T18:00:00Z",
              correlationTags: [],
            },
          ],
        },
      }),
      new Date("2026-04-10T23:00:00Z"),
    );

    expect(state.kind).toBe("awaiting_auto_settle");
    expect(state.showManualControlsByDefault).toBe(false);
  });
});
