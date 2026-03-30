import { expect, test } from "@playwright/test";

import {
  buildParlayEventSummary,
  buildParlayPreview,
  getParlayRecommendedStake,
  isPickEmParlayLeg,
} from "@/lib/parlay-utils";
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
  referenceTrueProbability: 0.48,
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
  referenceTrueProbability: 0.52,
  referenceSource: "market_median",
  display: "Nikola Jokic Over 24.5 PTS",
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
  test("builds a readable parlay summary from the selected leg labels", async () => {
    expect(buildParlayEventSummary([STRAIGHT_LEG, PROP_LEG], "DraftKings")).toBe(
      "Lakers ML + Nikola Jokic Over 24.5 PTS"
    );
  });

  test("compacts longer slips after the first two leg labels", async () => {
    const extraProp: ParlayCartLeg = {
      ...PROP_LEG,
      id: "props:2",
      eventId: "evt-3",
      selectionKey: "evt-3|player_points|lebron|over|27.5",
      sourceSelectionKey: "evt-3|player_points|lebron|over|27.5",
      display: "LeBron James Over 27.5 PTS",
      event: "Lakers @ Celtics",
      participantName: "LeBron James",
      lineValue: 27.5,
      correlationTags: ["evt-3", "LeBron James", "player_points"],
    };
    const extraStraight: ParlayCartLeg = {
      ...STRAIGHT_LEG,
      id: "straight:2",
      eventId: "evt-4",
      selectionKey: "evt-4|celtics",
      sourceSelectionKey: "evt-4|celtics",
      display: "Celtics ML",
      event: "Celtics @ Heat",
      team: "Celtics",
      selectionSide: "Celtics",
      correlationTags: ["evt-4", "celtics"],
    };

    expect(buildParlayEventSummary([STRAIGHT_LEG, PROP_LEG, extraProp, extraStraight], "DraftKings")).toBe(
      "Lakers ML + Nikola Jokic Over 24.... + 2 more"
    );
  });

  test("falls back to the sportsbook name for an empty cart", async () => {
    expect(buildParlayEventSummary([], "FanDuel")).toBe("FanDuel parlay");
  });

  test("builds combined pricing and independence estimate for clean slips", async () => {
    const preview = buildParlayPreview([STRAIGHT_LEG, PROP_LEG], 10, {
      bankroll: 1000,
      kellyMultiplier: 0.25,
    });

    expect(preview).not.toBeNull();
    expect(preview?.slipMode).toBe("standard");
    expect(preview?.legCount).toBe(2);
    expect(preview?.combinedAmericanOdds).toBeGreaterThan(300);
    expect(preview?.totalPayout).toBeGreaterThan(30);
    expect(preview?.profit).toBeCloseTo((preview?.totalPayout ?? 0) - 10, 5);
    expect(preview?.estimateAvailable).toBe(true);
    expect(preview?.estimatedFairAmericanOdds).not.toBeNull();
    expect(preview?.estimatedEvPercent).not.toBeNull();
    expect(preview?.baseKellyFraction).not.toBeNull();
    expect(preview?.rawKellyStake).toBeGreaterThan(0);
    expect(preview?.stealthKellyStake).toBeGreaterThan(0);
    expect(preview?.bankrollUsed).toBe(1000);
    expect(preview?.kellyMultiplierUsed).toBe(0.25);
    expect(preview?.warnings).toHaveLength(0);
  });

  test("prefers stored de-vigged probability over rounded reference odds", async () => {
    const preview = buildParlayPreview(
      [
        {
          ...STRAIGHT_LEG,
          oddsAmerican: 250,
          referenceOddsAmerican: 227,
          referenceTrueProbability: 100 / 340,
        },
      ],
      10
    );

    expect(preview?.estimateAvailable).toBe(true);
    expect(preview?.estimatedFairAmericanOdds).toBe(240);
    expect(preview?.estimatedTrueProbability).toBeCloseTo(100 / 340, 8);
  });

  test("returns null when the cart is empty", async () => {
    expect(buildParlayPreview([], 10)).toBeNull();
  });

  test("returns a zero-dollar recommendation for non-positive Kelly slips with a fair estimate", async () => {
    const preview = buildParlayPreview(
      [
        {
          ...STRAIGHT_LEG,
          id: "straight:no-edge",
          oddsAmerican: -110,
          referenceOddsAmerican: -150,
          referenceTrueProbability: 0.5,
        },
      ],
      10,
      { bankroll: 1000, kellyMultiplier: 0.25 }
    );

    expect(getParlayRecommendedStake(preview)).toBe(0);
  });

  test("returns null recommendation when the fair estimate is unavailable", async () => {
    const preview = buildParlayPreview(
      [{ ...STRAIGHT_LEG, referenceOddsAmerican: null, referenceTrueProbability: null, referenceSource: null }],
      10
    );

    expect(getParlayRecommendedStake(preview)).toBeNull();
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
    expect(preview?.stealthKellyStake).toBeNull();
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
      display: "LeBron James Over 24.5 PTS",
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
      [{ ...STRAIGHT_LEG, referenceOddsAmerican: null, referenceTrueProbability: null, referenceSource: null }, PROP_LEG],
      10
    );

    expect(preview?.estimateAvailable).toBe(false);
    expect(preview?.estimateUnavailableReason).toBe("Missing reference price");
    expect(preview?.estimatedFairAmericanOdds).toBeNull();
    expect(preview?.stealthKellyStake).toBeNull();
  });

  test("does not suggest Kelly for non-positive EV slips", async () => {
    const negativeEdgeLeg: ParlayCartLeg = {
      ...STRAIGHT_LEG,
      id: "straight:negative",
      oddsAmerican: -110,
      referenceOddsAmerican: -150,
    };

    const preview = buildParlayPreview([negativeEdgeLeg], 10, {
      bankroll: 1000,
      kellyMultiplier: 0.25,
    });

    expect(preview?.estimateAvailable).toBe(true);
    expect(preview?.estimatedEvPercent).not.toBeNull();
    expect((preview?.estimatedEvPercent ?? 0) <= 0).toBe(true);
    expect(preview?.baseKellyFraction).toBe(0);
    expect(preview?.rawKellyStake).toBeNull();
    expect(preview?.stealthKellyStake).toBeNull();
  });

  test("pick'em-only cart uses pickem_notes preview without combined odds or warnings", async () => {
    const pickLeg: ParlayCartLeg = {
      ...PROP_LEG,
      id: "pick:1",
      selectionMeta: { pickEmComparisonKey: "k1" },
    };
    const pickLeg2: ParlayCartLeg = {
      ...PROP_LEG,
      id: "pick:2",
      selectionKey: "evt-9|player_points|x|over|20",
      sourceSelectionKey: "evt-9|player_points|x|over|20",
      selectionMeta: { pickEmComparisonKey: "k2" },
      sportsbook: "FanDuel",
    };

    expect(isPickEmParlayLeg(pickLeg)).toBe(true);
    expect(isPickEmParlayLeg(PROP_LEG)).toBe(false);

    const preview = buildParlayPreview([pickLeg, pickLeg2], 10);
    expect(preview?.slipMode).toBe("pickem_notes");
    expect(preview?.combinedAmericanOdds).toBeNull();
    expect(preview?.totalPayout).toBeNull();
    expect(preview?.estimateAvailable).toBe(false);
    expect(preview?.warnings).toHaveLength(0);
    expect(getParlayRecommendedStake(preview)).toBeNull();
  });
});
