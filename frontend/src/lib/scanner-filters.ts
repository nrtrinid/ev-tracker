import type { MarketSide } from "@/lib/types";

export type ScannerTimePreset = "all" | "starting_soon" | "today" | "tomorrow";
export type ScannerRiskPreset = "any" | "safer" | "balanced";
export const DEFAULT_STANDARD_EDGE_MIN = 1;

export interface ScannerResultFilters {
  searchQuery: string;
  timePreset: ScannerTimePreset;
  edgeMinStandard: number;
  hideLongshots: boolean;
  hideAlreadyLogged: boolean;
  riskPreset: ScannerRiskPreset;
}

export function defaultScannerResultFilters(): ScannerResultFilters {
  return {
    searchQuery: "",
    timePreset: "all",
    edgeMinStandard: DEFAULT_STANDARD_EDGE_MIN,
    hideLongshots: true,
    hideAlreadyLogged: false,
    riskPreset: "any",
  };
}

export function normalizeSearchQuery(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function matchesSearch(side: MarketSide, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  const haystack = normalizeSearchQuery(
    `${side.team} ${side.event} ${side.sportsbook} ${side.sport}`
  );
  return haystack.includes(normalizedQuery);
}

function isToday(date: Date, now: Date): boolean {
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  );
}

function isTomorrow(date: Date, now: Date): boolean {
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  return (
    date.getFullYear() === tomorrow.getFullYear() &&
    date.getMonth() === tomorrow.getMonth() &&
    date.getDate() === tomorrow.getDate()
  );
}

function matchesTimePreset(
  commenceTime: string,
  preset: ScannerTimePreset,
  now: Date
): boolean {
  const start = new Date(commenceTime);
  if (Number.isNaN(start.getTime())) return false;

  const deltaMs = start.getTime() - now.getTime();
  // Past-started events are excluded from all filtered views.
  if (deltaMs < 0) return false;

  if (preset === "all") return true;

  const maxStartingSoonMs = 2 * 60 * 60 * 1000;

  if (preset === "starting_soon") {
    return deltaMs < maxStartingSoonMs;
  }

  if (preset === "today") {
    return isToday(start, now);
  }

  return isTomorrow(start, now);
}

function matchesRiskPreset(side: MarketSide, preset: ScannerRiskPreset): boolean {
  if (preset === "any") return true;
  if (preset === "safer") return side.book_odds <= 150;
  return side.book_odds <= 300;
}

export function applyScannerResultFilters(params: {
  sides: MarketSide[];
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  filters: ScannerResultFilters;
  now?: Date;
  longshotMaxAmerican: number;
}): MarketSide[] {
  const { sides, activeLens, filters, longshotMaxAmerican } = params;
  const now = params.now ?? new Date();
  const normalizedQuery = normalizeSearchQuery(filters.searchQuery);

  return sides.filter((side) => {
    if (!matchesSearch(side, normalizedQuery)) return false;
    if (!matchesTimePreset(side.commence_time, filters.timePreset, now)) return false;
    if (filters.hideLongshots && side.book_odds > longshotMaxAmerican) return false;
    if (filters.hideAlreadyLogged && (side.scanner_duplicate_state ?? "new") !== "new") {
      return false;
    }
    if (!matchesRiskPreset(side, filters.riskPreset)) return false;

    if (activeLens === "standard" && filters.edgeMinStandard > 0) {
      return side.ev_percentage >= filters.edgeMinStandard;
    }

    return true;
  });
}

export function describeScannerResultFilters(params: {
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  filters: ScannerResultFilters;
  longshotMaxAmerican: number;
}): string[] {
  const { activeLens, filters, longshotMaxAmerican } = params;
  const chips: string[] = [];

  const normalizedQuery = normalizeSearchQuery(filters.searchQuery);
  if (normalizedQuery) chips.push(`Search: ${filters.searchQuery.trim()}`);

  if (filters.timePreset === "starting_soon") chips.push("Time: Starting Soon");
  if (filters.timePreset === "today") chips.push("Time: Today");
  if (filters.timePreset === "tomorrow") chips.push("Time: Tomorrow");

  if (activeLens === "standard" && filters.edgeMinStandard !== DEFAULT_STANDARD_EDGE_MIN) {
    if (filters.edgeMinStandard === 0) {
      chips.push("Edge: All +EV");
    } else if (filters.edgeMinStandard !== DEFAULT_STANDARD_EDGE_MIN) {
      chips.push(`Edge: ${filters.edgeMinStandard.toFixed(1)}%+`);
    }
  }

  if (filters.hideLongshots) chips.push(`Odds: <= +${longshotMaxAmerican}`);
  if (filters.hideAlreadyLogged) chips.push("Hide Already Logged");
  if (filters.riskPreset === "safer") chips.push("Risk: Safer");
  if (filters.riskPreset === "balanced") chips.push("Risk: Balanced");

  return chips;
}

export function hasActiveScannerResultFilters(params: {
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  filters: ScannerResultFilters;
}): boolean {
  const { activeLens, filters } = params;
  return (
    normalizeSearchQuery(filters.searchQuery).length > 0 ||
    filters.timePreset !== "all" ||
    (activeLens === "standard" && filters.edgeMinStandard !== DEFAULT_STANDARD_EDGE_MIN) ||
    filters.hideLongshots ||
    filters.hideAlreadyLogged ||
    filters.riskPreset !== "any"
  );
}
