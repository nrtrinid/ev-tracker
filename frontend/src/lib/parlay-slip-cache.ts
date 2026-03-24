import type { ParlaySlip } from "@/lib/types";

function sortParlaySlips(slips: ParlaySlip[]): ParlaySlip[] {
  return [...slips].sort((left, right) => {
    const rightTime = Date.parse(right.updated_at);
    const leftTime = Date.parse(left.updated_at);
    if (Number.isNaN(rightTime) || Number.isNaN(leftTime)) {
      return right.updated_at.localeCompare(left.updated_at);
    }
    return rightTime - leftTime;
  });
}

export function upsertParlaySlipCache(
  current: ParlaySlip[] | undefined,
  nextSlip: ParlaySlip,
): ParlaySlip[] {
  const slips = Array.isArray(current) ? [...current] : [];
  const existingIndex = slips.findIndex((slip) => slip.id === nextSlip.id);
  if (existingIndex >= 0) {
    slips[existingIndex] = nextSlip;
  } else {
    slips.unshift(nextSlip);
  }
  return sortParlaySlips(slips);
}

export function markParlaySlipLoggedInCache(
  current: ParlaySlip[] | undefined,
  params: { slipId: string; loggedBetId: string; updatedAt?: string },
): ParlaySlip[] {
  const { slipId, loggedBetId, updatedAt = new Date().toISOString() } = params;
  const slips = Array.isArray(current) ? [...current] : [];
  const updated = slips.map((slip) => (
    slip.id === slipId
      ? {
          ...slip,
          logged_bet_id: loggedBetId,
          updated_at: updatedAt,
        }
      : slip
  ));
  return sortParlaySlips(updated);
}

export function removeParlaySlipFromCache(
  current: ParlaySlip[] | undefined,
  slipId: string,
): ParlaySlip[] {
  const slips = Array.isArray(current) ? current : [];
  return slips.filter((slip) => slip.id !== slipId);
}

export function shouldRetryParlaySaveAsNewDraft(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  return error.message === "Logged parlay slips cannot be edited" ||
    error.message === "Parlay slip has already been logged";
}
