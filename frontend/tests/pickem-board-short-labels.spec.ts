import { expect, test } from "@playwright/test";

import { buildPickEmBoardCards } from "@/app/scanner/pickem-board";
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
});
