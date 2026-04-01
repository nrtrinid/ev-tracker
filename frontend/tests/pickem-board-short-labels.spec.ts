import { expect, test } from "@playwright/test";

import { buildPickEmBoardCards } from "@/app/scanner/pickem-board";
import { sortPickEmBoardCards } from "@/app/scanner/ScannerSurfacePage";
import type { PlayerPropMarketSide } from "@/lib/types";


function makeSide(partial: Partial<PlayerPropMarketSide>): PlayerPropMarketSide {
  return {
    surface: "player_props",
    event_id: "evt-1",
    market_key: "player_points",
    selection_key: "evt-1|player_points|nikola jokic|over|24.5",
    sportsbook: "DraftKings",
    sport: "basketball_nba",
    event: "Denver Nuggets @ Phoenix Suns",
    event_short: "DEN @ PHX",
    commence_time: "2026-03-21T03:00:00Z",
    market: "player_points",
    player_name: "Nikola Jokic",
    participant_id: null,
    team: "Denver Nuggets",
    team_short: "DEN",
    opponent: "Phoenix Suns",
    opponent_short: "PHX",
    selection_side: "over",
    line_value: 24.5,
    display_name: "Nikola Jokic Over 24.5 PTS",
    reference_odds: -110,
    reference_source: "market_weighted_consensus",
    reference_bookmakers: ["bovada", "betmgm"],
    reference_bookmaker_count: 2,
    confidence_label: "solid",
    confidence_score: 0.52,
    prob_std: 0.01,
    book_odds: 105,
    true_prob: 0.51,
    base_kelly_fraction: 0.02,
    book_decimal: 2.05,
    ev_percentage: 4.55,
    ...partial,
  };
}


test.describe("pick'em board short labels", () => {
  test("keeps event_short and team_short on grouped cards", async () => {
    const sides: PlayerPropMarketSide[] = [
      makeSide({
        sportsbook: "DraftKings",
        selection_side: "over",
        selection_key: "evt-1|player_points|nikola jokic|over|24.5",
      }),
      makeSide({
        sportsbook: "DraftKings",
        selection_side: "under",
        selection_key: "evt-1|player_points|nikola jokic|under|24.5",
        book_odds: -125,
      }),
      makeSide({
        sportsbook: "FanDuel",
        selection_side: "over",
        selection_key: "evt-1|player_points|nikola jokic|over|24.5|fd",
        book_odds: 100,
      }),
      makeSide({
        sportsbook: "FanDuel",
        selection_side: "under",
        selection_key: "evt-1|player_points|nikola jokic|under|24.5|fd",
        book_odds: -120,
      }),
    ];

    const cards = buildPickEmBoardCards(sides);
    expect(cards).toHaveLength(1);
    expect(cards[0].event_short).toBe("DEN @ PHX");
    expect(cards[0].team_short).toBe("DEN");
    expect(cards[0].opponent_short).toBe("PHX");
  });

  test("sorts by strongest consensus above fifty percent", async () => {
    const sorted = sortPickEmBoardCards([
      {
        comparison_key: "balanced",
        event_id: "evt-1",
        sport: "basketball_nba",
        event: "A @ B",
        event_short: "A @ B",
        commence_time: "2026-03-21T03:00:00Z",
        player_name: "Balanced",
        participant_id: null,
        team: "A",
        team_short: "A",
        opponent: "B",
        opponent_short: "B",
        market_key: "player_points",
        market: "player_points",
        line_value: 20.5,
        exact_line_bookmakers: ["DraftKings", "FanDuel"],
        exact_line_bookmaker_count: 2,
        consensus_over_prob: 0.5,
        consensus_under_prob: 0.5,
        consensus_side: "over",
        confidence_label: "solid",
        best_over_sportsbook: "DraftKings",
        best_over_odds: 100,
        best_over_deeplink_url: null,
        best_under_sportsbook: "FanDuel",
        best_under_odds: -120,
        best_under_deeplink_url: null,
      },
      {
        comparison_key: "mid",
        event_id: "evt-2",
        sport: "basketball_nba",
        event: "C @ D",
        event_short: "C @ D",
        commence_time: "2026-03-21T04:00:00Z",
        player_name: "Mid",
        participant_id: null,
        team: "C",
        team_short: "C",
        opponent: "D",
        opponent_short: "D",
        market_key: "player_rebounds",
        market: "player_rebounds",
        line_value: 8.5,
        exact_line_bookmakers: ["DraftKings", "FanDuel", "BetMGM"],
        exact_line_bookmaker_count: 3,
        consensus_over_prob: 0.58,
        consensus_under_prob: 0.42,
        consensus_side: "over",
        confidence_label: "high",
        best_over_sportsbook: "DraftKings",
        best_over_odds: 102,
        best_over_deeplink_url: null,
        best_under_sportsbook: "FanDuel",
        best_under_odds: -118,
        best_under_deeplink_url: null,
      },
      {
        comparison_key: "top",
        event_id: "evt-3",
        sport: "basketball_nba",
        event: "E @ F",
        event_short: "E @ F",
        commence_time: "2026-03-21T05:00:00Z",
        player_name: "Top",
        participant_id: null,
        team: "E",
        team_short: "E",
        opponent: "F",
        opponent_short: "F",
        market_key: "player_assists",
        market: "player_assists",
        line_value: 7.5,
        exact_line_bookmakers: ["DraftKings", "FanDuel"],
        exact_line_bookmaker_count: 2,
        consensus_over_prob: 0.37,
        consensus_under_prob: 0.63,
        consensus_side: "under",
        confidence_label: "solid",
        best_over_sportsbook: "DraftKings",
        best_over_odds: 110,
        best_over_deeplink_url: null,
        best_under_sportsbook: "FanDuel",
        best_under_odds: -130,
        best_under_deeplink_url: null,
      },
    ]);

    expect(sorted.map((card) => card.comparison_key)).toEqual(["top", "mid"]);
  });
});
