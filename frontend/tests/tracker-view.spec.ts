import { expect, test } from "@playwright/test";

import { getTrackerSource, matchesTrackerSourceFilter } from "@/lib/tracker-source";
import { buildTrackedBetCardTitle } from "@/lib/straight-bet-labels";
import {
  buildTrackerViewQuery,
  matchesTrackerFilters,
  parseTrackerSourceFilter,
  parseTrackerTab,
} from "@/lib/tracker-view";
import type { Bet } from "@/lib/types";

function makeBet(overrides: Partial<Bet> = {}): Bet {
  const createdAt = overrides.created_at ?? "2026-04-01T12:00:00Z";
  return {
    id: overrides.id ?? "bet-1",
    created_at: createdAt,
    event_date: overrides.event_date ?? createdAt.slice(0, 10),
    settled_at: overrides.settled_at ?? createdAt,
    sport: overrides.sport ?? "NBA",
    event: overrides.event ?? "Lakers ML",
    market: overrides.market ?? "Moneyline",
    surface: overrides.surface ?? "straight_bets",
    sportsbook: overrides.sportsbook ?? "DraftKings",
    promo_type: overrides.promo_type ?? "standard",
    odds_american: overrides.odds_american ?? 100,
    odds_decimal: overrides.odds_decimal ?? 2,
    stake: overrides.stake ?? 10,
    boost_percent: overrides.boost_percent ?? null,
    winnings_cap: overrides.winnings_cap ?? null,
    notes: overrides.notes ?? null,
    opposing_odds: overrides.opposing_odds ?? null,
    result: overrides.result ?? "win",
    win_payout: overrides.win_payout ?? 20,
    ev_per_dollar: overrides.ev_per_dollar ?? 0.2,
    ev_total: overrides.ev_total ?? 2,
    real_profit: overrides.real_profit ?? 10,
    pinnacle_odds_at_entry: overrides.pinnacle_odds_at_entry ?? null,
    latest_pinnacle_odds: overrides.latest_pinnacle_odds ?? null,
    latest_pinnacle_updated_at: overrides.latest_pinnacle_updated_at ?? null,
    pinnacle_odds_at_close: overrides.pinnacle_odds_at_close ?? null,
    clv_updated_at: overrides.clv_updated_at ?? null,
    commence_time: overrides.commence_time ?? null,
    clv_team: overrides.clv_team ?? null,
    clv_sport_key: overrides.clv_sport_key ?? null,
    clv_event_id: overrides.clv_event_id ?? null,
    true_prob_at_entry: overrides.true_prob_at_entry ?? 0.6,
    clv_ev_percent: overrides.clv_ev_percent ?? null,
    beat_close: overrides.beat_close ?? null,
    is_paper: overrides.is_paper ?? false,
    strategy_cohort: overrides.strategy_cohort ?? null,
    auto_logged: overrides.auto_logged ?? false,
    auto_log_run_at: overrides.auto_log_run_at ?? null,
    auto_log_run_key: overrides.auto_log_run_key ?? null,
    scan_ev_percent_at_log: overrides.scan_ev_percent_at_log ?? null,
    book_odds_at_log: overrides.book_odds_at_log ?? null,
    reference_odds_at_log: overrides.reference_odds_at_log ?? null,
    source_event_id: overrides.source_event_id ?? null,
    source_market_key: overrides.source_market_key ?? null,
    source_selection_key: overrides.source_selection_key ?? null,
    participant_name: overrides.participant_name ?? null,
    participant_id: overrides.participant_id ?? null,
    selection_side: overrides.selection_side ?? null,
    line_value: overrides.line_value ?? null,
    selection_meta: overrides.selection_meta ?? null,
  };
}

test.describe("tracker source helpers", () => {
  test("classifies standard bets as core and non-standard bets as promos", async () => {
    expect(getTrackerSource(makeBet({ surface: "player_props", promo_type: "standard" }))).toBe("core");
    expect(getTrackerSource(makeBet({ surface: "straight_bets", market: "Spread", promo_type: "standard" }))).toBe("core");
    expect(getTrackerSource(makeBet({ surface: "parlay", promo_type: "standard" }))).toBe("core");
    expect(getTrackerSource(makeBet({ promo_type: "boost_30" }))).toBe("promos");
  });

  test("matches source and text filters together", async () => {
    const coreParlay = makeBet({
      surface: "parlay",
      event: "Celtics + Nuggets Parlay",
      sportsbook: "FanDuel",
      promo_type: "standard",
    });
    const promoBet = makeBet({
      event: "Kings ML",
      sportsbook: "DraftKings",
      promo_type: "bonus_bet",
    });
    const thunderBet = makeBet({
      event: "Los Angeles Lakers @ Oklahoma City Thunder",
      sportsbook: "FanDuel",
      promo_type: "standard",
    });

    expect(matchesTrackerSourceFilter(coreParlay, "core")).toBe(true);
    expect(matchesTrackerSourceFilter(promoBet, "core")).toBe(false);
    expect(matchesTrackerFilters(coreParlay, { source: "core", sportsbook: "FanDuel", search: "nuggets" })).toBe(true);
    expect(matchesTrackerFilters(coreParlay, { source: "core", sportsbook: "DraftKings", search: "nuggets" })).toBe(false);
    expect(matchesTrackerFilters(promoBet, { source: "promos", sportsbook: "all", search: "kings" })).toBe(true);
    expect(matchesTrackerFilters(thunderBet, { source: "core", sportsbook: "FanDuel", search: "okc" })).toBe(true);
  });

  test("rebuilds spread and total titles from logged straight-bet metadata", async () => {
    expect(
      buildTrackedBetCardTitle(
        makeBet({
          event: "Over",
          sport: "MLB",
          market: "Total",
          source_market_key: "totals",
          selection_side: "over",
          line_value: 8,
          clv_team: "Over",
        })
      )
    ).toBe("Over 8 runs");

    expect(
      buildTrackedBetCardTitle(
        makeBet({
          event: "Over",
          sport: "NBA",
          market: "Total",
          source_market_key: "totals",
          selection_side: "over",
          line_value: 210,
          clv_team: "Over",
        })
      )
    ).toBe("Over 210 points");

    expect(
      buildTrackedBetCardTitle(
        makeBet({
          event: "Cleveland Guardians",
          sport: "MLB",
          market: "Spread",
          source_market_key: "spreads",
          selection_side: "away",
          line_value: 1.5,
          clv_team: "Cleveland Guardians",
        })
      )
    ).toBe("Cleveland Guardians +1.5");
  });

  test("tracker search matches rebuilt spread and total labels", async () => {
    const totalBet = makeBet({
      event: "Over",
      sport: "NBA",
      market: "Total",
      source_market_key: "totals",
      selection_side: "over",
      line_value: 210,
      clv_team: "Over",
    });
    const spreadBet = makeBet({
      event: "Cleveland Guardians",
      sport: "MLB",
      market: "Spread",
      source_market_key: "spreads",
      selection_side: "away",
      line_value: 1.5,
      clv_team: "Cleveland Guardians",
    });

    expect(matchesTrackerFilters(totalBet, { source: "all", sportsbook: "all", search: "210" })).toBe(true);
    expect(matchesTrackerFilters(totalBet, { source: "all", sportsbook: "all", search: "over 210 points" })).toBe(true);
    expect(matchesTrackerFilters(spreadBet, { source: "all", sportsbook: "all", search: "guardians +1.5" })).toBe(true);
  });
});

test.describe("tracker view query helpers", () => {
  test("parses tab and source safely", async () => {
    expect(parseTrackerTab("history")).toBe("history");
    expect(parseTrackerTab("anything-else")).toBe("pending");
    expect(parseTrackerSourceFilter("core")).toBe("core");
    expect(parseTrackerSourceFilter("promos")).toBe("promos");
    expect(parseTrackerSourceFilter("cash")).toBe("all");
  });

  test("builds compact tracker query strings", async () => {
    expect(buildTrackerViewQuery({ tab: "pending", source: "all", sportsbook: "all", search: "" })).toBe("");
    expect(buildTrackerViewQuery({ tab: "history", source: "core", sportsbook: "all", search: "" })).toBe("tab=history&source=core");
    expect(buildTrackerViewQuery({ tab: "history", source: "promos", sportsbook: "FanDuel", search: "Lakers ML" }))
      .toBe("tab=history&source=promos&sportsbook=FanDuel&search=Lakers+ML");
  });
});
