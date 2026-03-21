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

test.describe("scanner filters", () => {
  test("default scanner filters are baseline", async () => {
    const defaults = defaultScannerResultFilters();
    expect(defaults.timePreset).toBe("all");
    expect(defaults.edgeMinStandard).toBe(1);
    expect(defaults.hideLongshots).toBeTruthy();
    expect(defaults.hideAlreadyLogged).toBeFalsy();
    expect(defaults.riskPreset).toBe("any");

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
      },
      longshotMaxAmerican: 500,
    });

    expect(labels).toContain("Edge: All +EV");
  });
});
