import { expect, test } from "@playwright/test";

import {
  markParlaySlipLoggedInCache,
  removeParlaySlipFromCache,
  shouldRetryParlaySaveAsNewDraft,
  upsertParlaySlipCache,
} from "@/lib/parlay-slip-cache";
import type { ParlaySlip } from "@/lib/types";

const BASE_SLIP: ParlaySlip = {
  id: "slip-1",
  created_at: "2026-03-23T00:00:00Z",
  updated_at: "2026-03-23T00:00:00Z",
  sportsbook: "DraftKings",
  stake: 25,
  legs: [],
  warnings: [],
  pricingPreview: null,
  logged_bet_id: null,
};

test.describe("parlay slip cache helpers", () => {
  test("upserts and sorts saved slips by updated_at descending", async () => {
    const current: ParlaySlip[] = [
      BASE_SLIP,
      {
        ...BASE_SLIP,
        id: "slip-2",
        updated_at: "2026-03-23T02:00:00Z",
      },
    ];

    const result = upsertParlaySlipCache(current, {
      ...BASE_SLIP,
      id: "slip-3",
      updated_at: "2026-03-23T03:00:00Z",
    });

    expect(result.map((slip) => slip.id)).toEqual(["slip-3", "slip-2", "slip-1"]);
  });

  test("marks a slip as logged without waiting for a refetch", async () => {
    const result = markParlaySlipLoggedInCache([BASE_SLIP], {
      slipId: "slip-1",
      loggedBetId: "bet-123",
      updatedAt: "2026-03-23T04:00:00Z",
    });

    expect(result[0]?.logged_bet_id).toBe("bet-123");
    expect(result[0]?.updated_at).toBe("2026-03-23T04:00:00Z");
  });

  test("removes deleted slips from cache", async () => {
    const result = removeParlaySlipFromCache([
      BASE_SLIP,
      { ...BASE_SLIP, id: "slip-2" },
    ], "slip-1");

    expect(result.map((slip) => slip.id)).toEqual(["slip-2"]);
  });

  test("retries stale logged-slip edit conflicts as new drafts", async () => {
    expect(shouldRetryParlaySaveAsNewDraft(new Error("Logged parlay slips cannot be edited"))).toBeTruthy();
    expect(shouldRetryParlaySaveAsNewDraft(new Error("Parlay slip has already been logged"))).toBeTruthy();
    expect(shouldRetryParlaySaveAsNewDraft(new Error("Failed to create parlay slip"))).toBeFalsy();
  });
});
