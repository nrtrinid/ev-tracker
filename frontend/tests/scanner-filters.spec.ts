import { expect, test } from "@playwright/test";

import {
  applyScannerResultFilters,
  defaultScannerResultFilters,
  describeScannerResultFilters,
  hasActiveScannerResultFilters,
  normalizeSearchQuery,
} from "@/lib/scanner-filters";
import type { MarketSide } from "@/lib/types";

const BASE_SIDE: MarketSide = {
  surface: "straight_bets",
  market_key: "h2h",
  selection_key: "evt-1:lakers",
  sportsbook: "DraftKings",
  sport: "basketball_nba",
  event: "Lakers @ Warriors",
  commence_time: "2026-03-21T01:00:00Z",
  team: "Los Angeles Lakers",
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

const BASE_PROP_SIDE: MarketSide = {
  surface: "player_props",
  event_id: "evt-prop-1",
  market_key: "player_points",
  selection_key: "evt-prop-1|player_points|jokic|over|24.5",
  sportsbook: "FanDuel",
  sport: "basketball_nba",
  event: "Nuggets @ Suns",
  commence_time: "2026-03-21T03:00:00Z",
  market: "player_points",
  player_name: "Nikola Jokic",
  participant_id: null,
  team: "Nuggets",
  opponent: "Suns",
  selection_side: "over",
  line_value: 24.5,
  display_name: "Nikola Jokic Over 24.5",
  reference_odds: -110,
  reference_source: "market_median",
  reference_bookmakers: ["bovada", "betmgm"],
  book_odds: 105,
  true_prob: 0.52,
  base_kelly_fraction: 0.022,
  book_decimal: 2.05,
  ev_percentage: 6.6,
  scanner_duplicate_state: "new",
  best_logged_odds_american: null,
  current_odds_american: 105,
  matched_pending_bet_id: null,
};

test.describe("scanner filters", () => {
  test("default scanner filters are baseline", async () => {
    const defaults = defaultScannerResultFilters();
    expect(defaults.timePreset).toBe("all");
    expect(defaults.edgeMinStandard).toBe(1);
    expect(defaults.hideLongshots).toBeTruthy();
    expect(defaults.hideAlreadyLogged).toBeFalsy();
    expect(defaults.riskPreset).toBe("any");
    expect(defaults.propMarket).toBe("all");
    expect(defaults.propSide).toBe("all");

    expect(
      hasActiveScannerResultFilters({
        activeLens: "standard",
        filters: defaults,
      })
    ).toBeTruthy();
  });

  test("normalizes whitespace and casing for search", async () => {
    expect(normalizeSearchQuery("  Lakers    Warriors  ")).toBe("lakers warriors");
  });

  test("applies standard edge filter only in standard lens", async () => {
    const sides = [
      BASE_SIDE,
      {
        ...BASE_SIDE,
        team: "Boston Celtics",
        event: "Celtics @ Knicks",
        ev_percentage: 0.8,
      },
    ];

    const standardFiltered = applyScannerResultFilters({
      sides,
      activeLens: "standard",
      longshotMaxAmerican: 500,
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 1,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      now: new Date("2026-03-20T12:00:00Z"),
    });

    const boostFiltered = applyScannerResultFilters({
      sides,
      activeLens: "profit_boost",
      longshotMaxAmerican: 500,
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 1,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      now: new Date("2026-03-20T12:00:00Z"),
    });

    expect(standardFiltered).toHaveLength(1);
    expect(boostFiltered).toHaveLength(2);
  });

  test("distinguishes time presets", async () => {
    const sides = [
      { ...BASE_SIDE, team: "Soon", commence_time: "2026-03-20T13:30:00Z" },
      { ...BASE_SIDE, team: "Today", commence_time: "2026-03-20T23:00:00Z" },
      { ...BASE_SIDE, team: "Tomorrow", commence_time: "2026-03-21T20:00:00Z" },
      { ...BASE_SIDE, team: "Past", commence_time: "2026-03-20T10:00:00Z" },
    ];

    const now = new Date("2026-03-20T12:00:00Z");

    const startingSoon = applyScannerResultFilters({
      sides,
      activeLens: "standard",
      longshotMaxAmerican: 500,
      filters: {
        searchQuery: "",
        timePreset: "starting_soon",
        edgeMinStandard: 0,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      now,
    });

    const tomorrow = applyScannerResultFilters({
      sides,
      activeLens: "standard",
      longshotMaxAmerican: 500,
      filters: {
        searchQuery: "",
        timePreset: "tomorrow",
        edgeMinStandard: 0,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      now,
    });

    const all = applyScannerResultFilters({
      sides,
      activeLens: "standard",
      longshotMaxAmerican: 500,
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 0,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      now,
    });

    expect(startingSoon.map((s) => s.team)).toEqual(["Soon"]);
    expect(tomorrow.map((s) => s.team)).toEqual(["Tomorrow"]);
    expect(all.map((s) => s.team)).toEqual(["Soon", "Today", "Tomorrow"]);
  });

  test("reports active filter chips and active-state flag", async () => {
    const filters = {
      searchQuery: "lakers",
      timePreset: "starting_soon" as const,
      edgeMinStandard: 1.5,
      hideLongshots: true,
      hideAlreadyLogged: true,
      riskPreset: "safer" as const,
      propMarket: "all",
      propSide: "all" as const,
    };

    expect(
      hasActiveScannerResultFilters({
        activeLens: "standard",
        filters,
      })
    ).toBeTruthy();

    const labels = describeScannerResultFilters({
      activeLens: "standard",
      filters,
      longshotMaxAmerican: 500,
    });

    expect(labels).toContain("Search: lakers");
    expect(labels).toContain("Time: Starting Soon");
    expect(labels).toContain("Edge: 1.5%+");
    expect(labels).toContain("Hide Already Logged");
  });

  test("treats 1.0% edge as default (not active) in standard lens", async () => {
    expect(
      hasActiveScannerResultFilters({
        activeLens: "standard",
        filters: {
          searchQuery: "",
          timePreset: "all",
          edgeMinStandard: 1,
          hideLongshots: false,
          hideAlreadyLogged: false,
          riskPreset: "any",
          propMarket: "all",
          propSide: "all",
        },
      })
    ).toBeFalsy();
  });

  test("reports tomorrow filter chip label", async () => {
    const labels = describeScannerResultFilters({
      activeLens: "standard",
      filters: {
        searchQuery: "",
        timePreset: "tomorrow",
        edgeMinStandard: 0,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      longshotMaxAmerican: 500,
    });

    expect(labels).toContain("Time: Tomorrow");
  });

  test("supports 1.5% edge threshold in standard lens", async () => {
    const sides = [
      { ...BASE_SIDE, team: "One", ev_percentage: 1.4 },
      { ...BASE_SIDE, team: "Two", ev_percentage: 1.5 },
    ];

    const filtered = applyScannerResultFilters({
      sides,
      activeLens: "standard",
      longshotMaxAmerican: 500,
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 1.5,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      now: new Date("2026-03-20T12:00:00Z"),
    });

    expect(filtered.map((s) => s.team)).toEqual(["Two"]);
  });

  test("labels All +EV when edge is set to 0", async () => {
    const labels = describeScannerResultFilters({
      activeLens: "standard",
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 0,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      longshotMaxAmerican: 500,
    });

    expect(labels).toContain("Edge: All +EV");
  });

  test("can expose the default 1.0% edge chip for player props", async () => {
    const labels = describeScannerResultFilters({
      activeLens: "standard",
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 1,
        hideLongshots: true,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "all",
        propSide: "all",
      },
      longshotMaxAmerican: 500,
      showDefaultStandardEdge: true,
    });

    expect(labels).toContain("Edge: 1.0%+");
    expect(labels).toContain("Odds: <= +500");
  });

  test("filters player props by market and side", async () => {
    const filtered = applyScannerResultFilters({
      sides: [
        BASE_PROP_SIDE,
        { ...BASE_PROP_SIDE, selection_side: "under", selection_key: "under", display_name: "Nikola Jokic Under 24.5" },
        { ...BASE_PROP_SIDE, market_key: "player_assists", market: "player_assists", selection_key: "assists", line_value: 8.5 },
      ],
      activeLens: "standard",
      longshotMaxAmerican: 500,
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 0,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "player_points",
        propSide: "over",
      },
      now: new Date("2026-03-20T12:00:00Z"),
    });

    expect(filtered).toHaveLength(1);
    expect(filtered[0]).toEqual(BASE_PROP_SIDE);
  });

  test("reports active props chips", async () => {
    const labels = describeScannerResultFilters({
      activeLens: "standard",
      filters: {
        searchQuery: "",
        timePreset: "all",
        edgeMinStandard: 0,
        hideLongshots: false,
        hideAlreadyLogged: false,
        riskPreset: "any",
        propMarket: "player_points",
        propSide: "under",
      },
      longshotMaxAmerican: 500,
    });

    expect(labels).toContain("Market: player points");
    expect(labels).toContain("Side: under");
  });
});
