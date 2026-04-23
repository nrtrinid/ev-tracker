import { expect, test } from "@playwright/test";

import { buildBetLiveChipState } from "@/lib/bet-live-state";
import type { BetLiveSnapshot } from "@/lib/types";

function snapshot(overrides: Partial<BetLiveSnapshot> = {}): BetLiveSnapshot {
  return {
    bet_id: "bet-1",
    sport_key: "basketball_nba",
    status: "live",
    event: {
      provider: "espn",
      provider_event_id: "401",
      sport_key: "basketball_nba",
      status: "live",
      status_detail: "Q3 04:22",
      period_label: "Q3",
      clock: "4:22",
      start_time: "2026-04-22T02:00:00Z",
      last_updated: "2026-04-22T03:15:00Z",
      away: { name: "Los Angeles Lakers", short_name: "LAL", score: 68, home_away: "away" },
      home: { name: "Golden State Warriors", short_name: "GSW", score: 72, home_away: "home" },
    },
    player_stat: null,
    provider: {
      primary_provider: "espn",
      source: "live_tracking",
      cache_hit: true,
      stale: false,
      last_updated: "2026-04-22T03:15:00Z",
      unavailable_reason: null,
      confidence: "matchup_plus_time",
    },
    ...overrides,
  };
}

function mlbSnapshot(overrides: Partial<BetLiveSnapshot> = {}): BetLiveSnapshot {
  return {
    bet_id: "bet-mlb-1",
    sport_key: "baseball_mlb",
    status: "live",
    event: {
      provider: "mlb_statsapi",
      provider_event_id: "401101",
      sport_key: "baseball_mlb",
      status: "live",
      status_detail: "Bottom 7th",
      period_label: "B7",
      clock: null,
      start_time: "2026-04-22T23:10:00Z",
      last_updated: "2026-04-23T01:15:00Z",
      away: { name: "New York Yankees", short_name: "NYY", score: 3, home_away: "away" },
      home: { name: "Boston Red Sox", short_name: "BOS", score: 2, home_away: "home" },
    },
    player_stat: null,
    provider: {
      primary_provider: "mlb_statsapi",
      source: "live_tracking",
      cache_hit: true,
      stale: false,
      last_updated: "2026-04-23T01:15:00Z",
      unavailable_reason: null,
      confidence: "matchup_plus_time",
    },
    ...overrides,
  };
}

test.describe("bet live chip state", () => {
  test("formats compact live game score without extra card rows", async () => {
    const state = buildBetLiveChipState(snapshot());

    expect(state?.label).toBe("Q3 4:22 • LAL 68-72 GSW");
    expect(state?.tone).toBe("live");
    expect(state?.progressRatio).toBeNull();
  });

  test("prefers supported player stat progress when present", async () => {
    const state = buildBetLiveChipState(
      snapshot({
        player_stat: {
          participant_name: "LeBron James",
          stat_key: "AST",
          stat_label: "AST",
          value: 2,
          line_value: 4,
          selection_side: "over",
          progress_ratio: 0.5,
          match_kind: "exact",
        },
      }),
    );

    expect(state?.label).toBe("2 / 4 AST");
    expect(state?.title).toBe("LeBron James: 2 / 4 AST");
    expect(state?.progressRatio).toBe(0.5);
  });

  test("hides unavailable snapshots by default", async () => {
    const state = buildBetLiveChipState(
      snapshot({
        status: "unavailable",
        event: null,
        provider: {
          primary_provider: null,
          source: "live_tracking",
          cache_hit: false,
          stale: false,
          last_updated: null,
          unavailable_reason: "unsupported_sport_or_provider",
          confidence: null,
        },
      }),
    );

    expect(state).toBeNull();
  });

  test("formats compact MLB inning labels with the live score", async () => {
    const state = buildBetLiveChipState(mlbSnapshot());

    expect(state?.label).toContain("B7");
    expect(state?.label).toContain("NYY 3-2 BOS");
    expect(state?.title).toBe("Bottom 7th");
    expect(state?.tone).toBe("live");
    expect(state?.progressRatio).toBeNull();
  });

  test("uses compact status labels for non-live MLB game states", async () => {
    const state = buildBetLiveChipState(
      mlbSnapshot({
        status: "delayed",
        event: {
          provider: "mlb_statsapi",
          provider_event_id: "401101",
          sport_key: "baseball_mlb",
          status: "delayed",
          status_detail: "Rain Delay",
          period_label: null,
          clock: null,
          start_time: "2026-04-22T23:10:00Z",
          last_updated: "2026-04-23T01:15:00Z",
          away: { name: "New York Yankees", short_name: "NYY", score: 3, home_away: "away" },
          home: { name: "Boston Red Sox", short_name: "BOS", score: 2, home_away: "home" },
        },
      }),
    );

    expect(state?.label).toBe("Delayed");
    expect(state?.title).toBe("Rain Delay");
    expect(state?.tone).toBe("warning");
  });

  for (const [statKey, statLabel, value, lineValue, expectedLabel] of [
    ["P_SO", "P_SO", 4, 5, "4 / 5 Ks"],
    ["B_TB", "B_TB", 3, 4, "3 / 4 TB"],
    ["B_H", "B_H", 2, 2.5, "2 / 2.5 H"],
    ["B_H_R_RBI", "B_H_R_RBI", 4, 5, "4 / 5 H+R+RBI"],
  ] as const) {
    test(`formats compact MLB prop counters for ${statKey}`, async () => {
      const state = buildBetLiveChipState(
        mlbSnapshot({
          player_stat: {
            participant_name: "Aaron Judge",
            stat_key: statKey,
            stat_label: statLabel,
            value,
            line_value: lineValue,
            selection_side: "over",
            progress_ratio: value / lineValue,
            match_kind: "exact",
          },
        }),
      );

      expect(state?.label).toBe(expectedLabel);
      expect(state?.title).toBe(`Aaron Judge: ${expectedLabel}`);
      expect(state?.progressRatio).toBe(value / lineValue);
      expect(state?.tone).toBe("live");
    });
  }
});
