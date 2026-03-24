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
  referenceOddsAmerican: 108,
  referenceSource: "pinnacle",
  display: "Lakers ML",
  event: "Lakers @ Warriors",
  sport: "basketball_nba",
  commenceTime: "2026-03-21T01:00:00Z",
  correlationTags: ["evt-1", "lakers"],
  team: "Lakers",
  participantName: null,
  participantId: null,
  selectionSide: "Lakers",
  lineValue: null,
  marketDisplay: "Moneyline",
  sourceEventId: "evt-1",
  sourceMarketKey: "h2h",
  sourceSelectionKey: "evt-1:lakers",
  selectionMeta: null,
};

const PROP_LEG: ParlayCartLeg = {
  id: "props:1",
  surface: "player_props",
  eventId: "evt-2",
  marketKey: "player_points",
  selectionKey: "evt-2|player_points|jokic|over|24.5",
  sportsbook: "DraftKings",
  oddsAmerican: 105,
  referenceOddsAmerican: -110,
  referenceSource: "market_median",
  display: "Nikola Jokic Over 24.5",
  event: "Nuggets @ Suns",
  sport: "basketball_nba",
  commenceTime: "2026-03-21T03:00:00Z",
  correlationTags: ["evt-2", "Nikola Jokic", "player_points"],
  team: "Nuggets",
  participantName: "Nikola Jokic",
  participantId: null,
  selectionSide: "over",
  lineValue: 24.5,
  marketDisplay: "Player Points",
  sourceEventId: "evt-2",
  sourceMarketKey: "player_points",
  sourceSelectionKey: "evt-2|player_points|jokic|over|24.5",
  selectionMeta: null,
};

test.describe("parlay utils", () => {
  test("builds combined pricing and independence estimate for clean slips", async () => {
    const preview = buildParlayPreview([STRAIGHT_LEG, PROP_LEG], 10);

    expect(preview).not.toBeNull();
    expect(preview?.legCount).toBe(2);
    expect(preview?.combinedAmericanOdds).toBeGreaterThan(300);
    expect(preview?.totalPayout).toBeGreaterThan(30);
    expect(preview?.profit).toBeCloseTo((preview?.totalPayout ?? 0) - 10, 5);
    expect(preview?.estimateAvailable).toBe(true);
    expect(preview?.estimatedFairAmericanOdds).not.toBeNull();
    expect(preview?.estimatedEvPercent).not.toBeNull();
    expect(preview?.warnings).toHaveLength(0);
  });

  test("returns null when the cart is empty", async () => {
    expect(buildParlayPreview([], 10)).toBeNull();
  });

  test("suppresses estimate when same-event correlation is present", async () => {
    const correlatedLeg: ParlayCartLeg = {
      ...PROP_LEG,
      id: "props:correlated",
      eventId: "evt-1",
      event: "Lakers @ Warriors",
      correlationTags: ["evt-1", "Nikola Jokic", "player_points"],
    };

    const preview = buildParlayPreview([STRAIGHT_LEG, correlatedLeg], 10);

    expect(preview?.estimateAvailable).toBe(false);
    expect(preview?.estimateUnavailableReason).toBe("Correlation warning");
    expect(preview?.warnings.some((warning) => warning.code === "same_event_correlation")).toBe(true);
  });

  test("does not raise a shared-tag warning for generic market keys across events", async () => {
    const propA: ParlayCartLeg = {
      ...PROP_LEG,
      id: "props:a",
      eventId: "evt-a",
      event: "Nuggets @ Suns",
      correlationTags: ["evt-a", "Nikola Jokic", "player_points"],
    };
    const propB: ParlayCartLeg = {
      ...PROP_LEG,
      id: "props:b",
      eventId: "evt-b",
      event: "Lakers @ Warriors",
      participantName: "LeBron James",
      display: "LeBron James Over 24.5",
      selectionKey: "evt-b|player_points|lebron|over|24.5",
      sourceSelectionKey: "evt-b|player_points|lebron|over|24.5",
      correlationTags: ["evt-b", "LeBron James", "player_points"],
    };

    const preview = buildParlayPreview([propA, propB], 10);

    expect(preview?.warnings.some((warning) => warning.code === "shared_correlation_tag")).toBe(false);
    expect(preview?.estimateAvailable).toBe(true);
  });

  test("suppresses estimate when a leg is missing a reference price", async () => {
    const preview = buildParlayPreview(
      [{ ...STRAIGHT_LEG, referenceOddsAmerican: null, referenceSource: null }, PROP_LEG],
      10
    );

    expect(preview?.estimateAvailable).toBe(false);
    expect(preview?.estimateUnavailableReason).toBe("Missing reference price");
    expect(preview?.estimatedFairAmericanOdds).toBeNull();
  });
});
