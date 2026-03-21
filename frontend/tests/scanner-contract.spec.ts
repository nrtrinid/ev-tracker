import { expect, test } from "@playwright/test";

import {
  classifyScannerNullState,
  describeActiveResultFilters,
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
});
