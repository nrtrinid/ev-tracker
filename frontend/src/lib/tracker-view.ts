import type { Bet } from "@/lib/types";

import { buildTrackedBetCardTitle } from "@/lib/straight-bet-labels";
import { matchesTeamAliasSearch } from "@/lib/team-search-aliases";
import { matchesTrackerSourceFilter, type TrackerSourceFilter } from "@/lib/tracker-source";

export type TrackerTab = "pending" | "history";

export type TrackerViewState = {
  tab: TrackerTab;
  source: TrackerSourceFilter;
  sportsbook: string;
  search: string;
};

export const DEFAULT_TRACKER_VIEW_STATE: TrackerViewState = {
  tab: "pending",
  source: "all",
  sportsbook: "all",
  search: "",
};

export function parseTrackerTab(value: string | null): TrackerTab {
  return value === "history" ? "history" : "pending";
}

export function parseTrackerSourceFilter(value: string | null): TrackerSourceFilter {
  if (value === "core" || value === "promos") {
    return value;
  }

  return "all";
}

export function normalizeTrackerSearch(search: string): string {
  return search.trim();
}

export function buildTrackerViewQuery(state: TrackerViewState): string {
  const params = new URLSearchParams();
  const search = normalizeTrackerSearch(state.search);

  if (state.tab !== DEFAULT_TRACKER_VIEW_STATE.tab) {
    params.set("tab", state.tab);
  }

  if (state.source !== DEFAULT_TRACKER_VIEW_STATE.source) {
    params.set("source", state.source);
  }

  if (state.sportsbook !== DEFAULT_TRACKER_VIEW_STATE.sportsbook) {
    params.set("sportsbook", state.sportsbook);
  }

  if (search) {
    params.set("search", search);
  }

  return params.toString();
}

export function matchesTrackerSearch(bet: Bet, rawSearch: string): boolean {
  const search = normalizeTrackerSearch(rawSearch);

  if (!search) {
    return true;
  }

  const haystacks = [
    bet.event,
    buildTrackedBetCardTitle(bet),
    bet.market,
    bet.sport,
    bet.sportsbook,
    bet.clv_team,
    bet.participant_name,
    bet.selection_side,
    bet.line_value == null ? null : String(bet.line_value),
  ];

  return matchesTeamAliasSearch(search, haystacks);
}

export function matchesTrackerFilters(bet: Bet, filters: Pick<TrackerViewState, "source" | "sportsbook" | "search">): boolean {
  const matchesSportsbook = filters.sportsbook === "all" || bet.sportsbook === filters.sportsbook;
  return matchesSportsbook && matchesTrackerSourceFilter(bet, filters.source) && matchesTrackerSearch(bet, filters.search);
}
