import { expect, test } from "@playwright/test";

import {
  classifyScannerNullState,
  describeActiveResultFilters,
  isPlayerPropScanDiagnostics,
  isScanResultContractShape,
} from "@/lib/scanner-contract";

test.describe("scanner contract helpers", () => {
  test("accepts valid scan payload shape", async () => {
    const payload = {
      sport: "all",
      sides: [
        {
          sportsbook: "DraftKings",
          sport: "basketball_nba",
          event: "Lakers @ Warriors",
          commence_time: "2026-03-20T18:00:00Z",
          team: "Lakers",
          pinnacle_odds: 110,
          book_odds: 120,
          true_prob: 0.51,
          base_kelly_fraction: 0.03,
          book_decimal: 2.2,
          ev_percentage: 3.2,
        },
      ],
      events_fetched: 12,
      events_with_both_books: 10,
      api_requests_remaining: "498",
      scanned_at: "2026-03-20T17:55:00Z",
    };

    expect(isScanResultContractShape(payload)).toBeTruthy();
  });

  test("rejects invalid scan payload shape", async () => {
    const payload = {
      sport: "all",
      sides: [{ event: "missing required fields" }],
      events_fetched: "12",
      events_with_both_books: 10,
    };

    expect(isScanResultContractShape(payload)).toBeFalsy();
  });

  test("classifies backend-empty and filter-empty states distinctly", async () => {
    expect(classifyScannerNullState({ sourceCount: 0, filteredCount: 0 })).toBe("backend_empty");
    expect(classifyScannerNullState({ sourceCount: 20, filteredCount: 0 })).toBe("filter_empty");
    expect(classifyScannerNullState({ sourceCount: 20, filteredCount: 5 })).toBe("has_results");
  });

  test("describes active filters for null-state messaging", async () => {
    expect(describeActiveResultFilters(["Time: Starting Soon", "Edge: 1.0%+"])).toContain(
      "Active filters:"
    );
    expect(describeActiveResultFilters(["   "])).toBe("No result filters applied");
  });

  test("accepts valid player prop diagnostics payload shape", async () => {
    const diagnostics = {
      scan_mode: "curated_sniper",
      scoreboard_event_count: 25,
      odds_event_count: 5,
      curated_games: [
        {
          event_id: "401810887",
          away_team: "Portland Trail Blazers",
          home_team: "Denver Nuggets",
          selection_reason: "nba_tv",
          broadcasts: ["Altitude Sports", "NBA TV"],
          odds_event_id: "evt-1",
          commence_time: "2026-03-22T21:10:00Z",
          matched: true,
        },
      ],
      matched_event_count: 1,
      unmatched_game_count: 0,
      events_fetched: 1,
      events_skipped_pregame: 0,
      events_with_results: 1,
      candidate_sides_count: 120,
      quality_gate_filtered_count: 8,
      quality_gate_min_reference_bookmakers: 2,
      sides_count: 112,
      markets_requested: ["player_points", "player_rebounds"],
    };

    expect(isPlayerPropScanDiagnostics(diagnostics)).toBeTruthy();
  });
});
