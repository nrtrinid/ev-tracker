import type { Bet } from "@/lib/types";

export type TrackerSource = "core" | "promos";
export type TrackerSourceFilter = "all" | TrackerSource;

export function getTrackerSource(bet: Bet): TrackerSource {
  return bet.promo_type === "standard" ? "core" : "promos";
}

export function matchesTrackerSourceFilter(bet: Bet, filter: TrackerSourceFilter): boolean {
  return filter === "all" || getTrackerSource(bet) === filter;
}

export function getTrackerSourceLabel(filter: TrackerSourceFilter): string {
  if (filter === "core") {
    return "Core Bets";
  }

  if (filter === "promos") {
    return "Promos";
  }

  return "All Bets";
}
