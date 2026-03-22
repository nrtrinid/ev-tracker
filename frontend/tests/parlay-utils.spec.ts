import { expect, test } from "@playwright/test";

import { buildParlayPreview } from "@/lib/parlay-utils";
import type { ParlayCartLeg } from "@/lib/types";

const STRAIGHT_LEG: ParlayCartLeg = {
  id: "straight:1",
  surface: "straight_bets",
  eventId: "evt-1",
  marketKey: "h2h",
  selectionKey: "evt-1:lakers",
  sportsbook: "DraftKings",
  oddsAmerican: 130,
  display: "Lakers ML",
  event: "Lakers @ Warriors",
  sport: "basketball_nba",
  commenceTime: "2026-03-21T01:00:00Z",
  correlationTags: ["evt-1", "lakers"],
};

const PROP_LEG: ParlayCartLeg = {
  id: "props:1",
  surface: "player_props",
  eventId: "evt-2",
  marketKey: "player_points",
  selectionKey: "evt-2|player_points|jokic|over|24.5",
  sportsbook: "FanDuel",
  oddsAmerican: 105,
  display: "Nikola Jokic Over 24.5",
  event: "Nuggets @ Suns",
  sport: "basketball_nba",
  commenceTime: "2026-03-21T03:00:00Z",
  correlationTags: ["evt-2", "Nikola Jokic", "player_points"],
};

test.describe("parlay utils", () => {
  test("builds combined payout preview from cart legs", async () => {
    const preview = buildParlayPreview([STRAIGHT_LEG, PROP_LEG], 10);

    expect(preview).not.toBeNull();
    expect(preview?.legCount).toBe(2);
    expect(preview?.combinedAmericanOdds).toBeGreaterThan(300);
    expect(preview?.totalPayout).toBeGreaterThan(30);
    expect(preview?.profit).toBeCloseTo((preview?.totalPayout ?? 0) - 10, 5);
  });

  test("returns null when preview stake is invalid", async () => {
    expect(buildParlayPreview([STRAIGHT_LEG], 0)).toBeNull();
    expect(buildParlayPreview([], 10)).toBeNull();
  });
});
