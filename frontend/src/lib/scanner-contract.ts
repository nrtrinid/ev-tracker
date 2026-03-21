import type { ScanResult } from "@/lib/types";

export type ScannerNullState = "has_results" | "backend_empty" | "filter_empty";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isScanResultContractShape(value: unknown): value is ScanResult {
  if (!isObject(value)) return false;
  if (typeof value.sport !== "string") return false;
  if (!Array.isArray(value.sides)) return false;
  if (typeof value.events_fetched !== "number") return false;
  if (typeof value.events_with_both_books !== "number") return false;

  if (value.api_requests_remaining !== null && value.api_requests_remaining !== undefined) {
    if (typeof value.api_requests_remaining !== "string") return false;
  }

  return value.sides.every((side) => {
    if (!isObject(side)) return false;
    return (
      typeof side.sportsbook === "string" &&
      typeof side.sport === "string" &&
      typeof side.event === "string" &&
      typeof side.commence_time === "string" &&
      typeof side.team === "string" &&
      typeof side.pinnacle_odds === "number" &&
      typeof side.book_odds === "number" &&
      typeof side.true_prob === "number" &&
      typeof side.base_kelly_fraction === "number" &&
      typeof side.book_decimal === "number" &&
      typeof side.ev_percentage === "number"
    );
  });
}

export function classifyScannerNullState(params: {
  sourceCount: number;
  filteredCount: number;
}): ScannerNullState {
  const { sourceCount, filteredCount } = params;
  if (sourceCount <= 0) return "backend_empty";
  if (filteredCount <= 0) return "filter_empty";
  return "has_results";
}

export function describeActiveResultFilters(activeFilters: string[]): string {
  const normalized = activeFilters.map((f) => f.trim()).filter(Boolean);
  if (!normalized.length) return "No result filters applied";
  return `Active filters: ${normalized.join(", ")}`;
}
