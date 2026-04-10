// Quarantined until the frontend utility specs move to a dedicated unit-test runner.
import { expect, test } from "vitest";

import { normalizeParlayLegFromRaw, parseParlayLegsFromBet } from "@/lib/parlay-bet-meta";
import type { Bet } from "@/lib/types";

const baseBet: Bet = {
  id: "b1",
  created_at: "2026-01-01T00:00:00Z",
  event_date: "2026-01-01",
  settled_at: null,
  sport: "NBA",
  event: "Lakers ML + More",
  market: "Parlay",
  surface: "parlay",
  sportsbook: "DraftKings",
  promo_type: "standard",
  odds_american: 500,
  odds_decimal: 6,
  stake: 10,
  boost_percent: null,
  winnings_cap: null,
  notes: null,
  opposing_odds: null,
  result: "pending",
  win_payout: 60,
  ev_per_dollar: 0.1,
  ev_total: 1,
  real_profit: null,
  pinnacle_odds_at_entry: null,
  latest_pinnacle_odds: null,
  latest_pinnacle_updated_at: null,
  pinnacle_odds_at_close: null,
  clv_updated_at: null,
  commence_time: null,
  clv_team: null,
  clv_sport_key: null,
  clv_event_id: null,
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
};

test("parseParlayLegsFromBet returns legs from camelCase selection_meta", () => {
  const bet: Bet = {
    ...baseBet,
    selection_meta: {
      type: "parlay",
      legs: [
        {
          id: "l1",
          surface: "straight_bets",
          marketKey: "h2h",
          selectionKey: "evt|lal",
          sportsbook: "DraftKings",
          oddsAmerican: -150,
          referenceOddsAmerican: -140,
          referenceSource: "pinnacle",
          display: "Lakers ML",
          event: "Lakers @ Celtics",
          sport: "basketball_nba",
          commenceTime: "2026-03-21T02:00:00Z",
          correlationTags: ["evt-1", "lakers"],
          team: "Lakers",
        },
      ],
    },
  };
  const legs = parseParlayLegsFromBet(bet);
  expect(legs).not.toBeNull();
  expect(legs).toHaveLength(1);
  expect(legs![0].display).toBe("Lakers ML");
  expect(legs![0].oddsAmerican).toBe(-150);
  expect(legs![0].commenceTime).toBe("2026-03-21T02:00:00Z");
});

test("parseParlayLegsFromBet accepts snake_case leg fields", () => {
  const bet: Bet = {
    ...baseBet,
    selection_meta: {
      type: "parlay",
      legs: [
        {
          id: "l1",
          market_key: "player_points",
          selection_key: "sk",
          sportsbook: "FanDuel",
          odds_american: 105,
          reference_odds_american: -108,
          reference_source: "consensus",
          display: "Jokic Over 24.5 PTS",
          event: "Nuggets @ Suns",
          sport: "basketball_nba",
          commence_time: "2026-03-22T03:00:00Z",
          correlation_tags: ["e1"],
          participant_name: "Nikola Jokic",
          selection_side: "over",
          line_value: 24.5,
          source_market_key: "player_points",
        },
      ],
    },
  };
  const legs = parseParlayLegsFromBet(bet);
  expect(legs).not.toBeNull();
  expect(legs![0].marketKey).toBe("player_points");
  expect(legs![0].participantName).toBe("Nikola Jokic");
  expect(legs![0].lineValue).toBe(24.5);
});

test("parseParlayLegsFromBet returns null for non-parlay or missing meta", () => {
  expect(parseParlayLegsFromBet({ ...baseBet, surface: "straight_bets" })).toBeNull();
  expect(parseParlayLegsFromBet({ ...baseBet, selection_meta: {} })).toBeNull();
  expect(parseParlayLegsFromBet({ ...baseBet, selection_meta: { type: "parlay", legs: [] } })).toBeNull();
});

test("normalizeParlayLegFromRaw reads per-leg CLV fields", () => {
  const leg = normalizeParlayLegFromRaw(
    {
      id: "x",
      sportsbook: "DK",
      display: "Test",
      oddsAmerican: 100,
      pinnacle_odds_at_close: -110,
      clv_ev_percent: 2.5,
      beat_close: true,
    },
    0,
  );
  expect(leg).not.toBeNull();
  expect(leg!.pinnacle_odds_at_close).toBe(-110);
  expect(leg!.clv_ev_percent).toBe(2.5);
  expect(leg!.beat_close).toBe(true);
});
