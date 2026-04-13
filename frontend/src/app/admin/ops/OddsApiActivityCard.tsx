"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type {
  BoardDropResultSummary,
  BoardDropRunStatus,
  OddsApiActivityCall,
  OddsApiActivityScanDetail,
  OddsApiActivityScanSession,
  OddsApiActivitySummary,
  OperatorStatusResponse,
} from "@/lib/types";

type HealthState = "healthy" | "warning" | "degraded" | "unknown";
type SourceFilter = "all" | "board_drop" | "jit" | "settlement" | "manual" | "other";
type UsageCategory = "board_drop" | "jit" | "settlement" | "manual" | "legacy" | "other";
type WarningTone = "danger" | "warning" | "info";

type UsageRow = {
  key: string;
  label: string;
  exactCredits: number;
  exactCallCount: number;
  inferredCredits: number;
  totalCredits: number;
  callCount: number;
  errorCount: number;
  hasExactData: boolean;
};

type GapWarning = {
  afterTimestamp: string | null;
  beforeTimestamp: string | null;
  gapMinutes: number;
  unaccountedCredits: number;
};

type BoardRunDescriptor = {
  key: "scheduled" | "manual";
  label: string;
  run: BoardDropRunStatus;
  result: BoardDropResultSummary | null;
  timestamp: string | null;
  errorCount: number;
};

type BoardWarning = {
  key: string;
  tone: WarningTone;
  title: string;
  body: string;
};

const BOARD_DROP_SOURCES = new Set(["scheduled_board_drop", "ops_trigger_board_drop", "cron_board_drop"]);
const JIT_SOURCES = new Set(["jit_clv", "jit_clv_props"]);
const SETTLEMENT_SOURCES = new Set([
  "auto_settle_scheduler",
  "auto_settle_cron",
  "auto_settle_ops_trigger",
  "auto_settle",
  "manual_cli",
  "clv_daily",
]);
const MANUAL_SOURCES = new Set([
  "manual_scan",
  "manual_refresh",
  "manual_refresh_props_events",
  "manual_scan_props_events",
  "ops_trigger_scan",
  "cron_scan",
  "ops_trigger",
  "cron",
]);

function parseOpsTimestamp(value?: string | null): Date | null {
  if (!value) return null;
  const raw = value.trim();
  if (!raw) return null;
  const normalized = /[+-]\d{2}:\d{2}Z$/i.test(raw) ? raw.slice(0, -1) : raw;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function formatTime(value?: string | null): string {
  const parsed = parseOpsTimestamp(value);
  if (!parsed) return "Unknown";
  return parsed.toLocaleString();
}

function ageMinutes(value?: string | null): number | null {
  const parsed = parseOpsTimestamp(value);
  if (!parsed) return null;
  return Math.max(0, Math.round((Date.now() - parsed.getTime()) / 60000));
}

function formatRelativeTime(value?: string | null): string {
  const age = ageMinutes(value);
  if (age === null) return "Unknown";
  if (age < 1) return "just now";
  if (age < 60) return `${age}m ago`;
  if (age < 1440) return `${Math.floor(age / 60)}h ago`;
  return `${Math.floor(age / 1440)}d ago`;
}

function formatTimeWithRelative(value?: string | null, fallback: string = "Unknown"): string {
  if (!value) return fallback;
  const full = formatTime(value);
  if (full === "Unknown") return fallback;
  return `${full} (${formatRelativeTime(value)})`;
}

function formatCompactTime(value?: string | null): string {
  const parsed = parseOpsTimestamp(value);
  if (!parsed) return "Unknown";
  return parsed.toLocaleString([], {
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDuration(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}s`;
}

function scalarOrUnknown(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "Unknown";
  return String(value);
}

function formatQuotaLabel(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "quota n/a";
  return `${value} left`;
}

function parseRemainingValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === "number" ? value : Number(String(value).trim());
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

function isFailedActivity(call: { error_type?: string | null; status_code?: number | null }): boolean {
  return Boolean(call.error_type) || (typeof call.status_code === "number" && call.status_code >= 400);
}

function formatModeLabel(cacheHit?: boolean, outboundCallMade?: boolean): string {
  if (cacheHit) return "cache";
  if (outboundCallMade) return "live";
  return "local";
}

function formatSportLabel(sport?: string | null): string {
  if (!sport) return "Unknown";
  if (sport === "all") return "All sports";
  return sport
    .split("_")
    .filter(Boolean)
    .map((part, index, parts) => (index === parts.length - 1 ? part.toUpperCase() : part))
    .join(" ");
}

function formatSportsList(sports?: string[] | null): string {
  if (!sports?.length) return "Unknown";
  return sports.map((sport) => formatSportLabel(sport)).join(", ");
}

function formatOddsSourceLabel(source?: string | null): string {
  const normalized = (source || "").trim().toLowerCase();
  if (normalized === "scheduled_board_drop") return "Scheduled board drop";
  if (normalized === "ops_trigger_board_drop") return "Ops manual refresh";
  if (normalized === "cron_board_drop") return "Cron board drop";
  if (normalized === "jit_clv") return "JIT CLV";
  if (normalized === "jit_clv_props") return "JIT CLV props";
  if (normalized === "auto_settle_scheduler") return "Auto-settle (scheduler)";
  if (normalized === "auto_settle_cron") return "Auto-settle (cron)";
  if (normalized === "auto_settle_ops_trigger") return "Auto-settle (ops)";
  if (normalized === "manual_refresh") return "Manual refresh";
  if (normalized === "manual_refresh_props_events") return "Manual refresh props events";
  if (normalized === "manual_scan") return "Manual scan";
  if (normalized === "manual_scan_props_events") return "Manual scan props events";
  if (normalized === "scheduled_scan") return "Scheduled straight scan";
  if (normalized === "manual_cli") return "Manual CLI";
  return source || "Unknown source";
}

function formatOddsEndpointLabel(endpoint?: string | null): string {
  const value = (endpoint || "").trim();
  if (!value) return "Unknown endpoint";
  if (value.includes("odds?markets=h2h,spreads,totals")) return "Game lines slate";
  if (value.includes("odds?markets=totals")) return "Totals slate";
  if (/\/sports\/[^/]+\/events\/[^/]+\/odds/i.test(value)) return "Event odds bundle";
  if (value.endsWith("/scores")) return "Scores";
  if (value.endsWith("/events")) return "Events list";
  if (/\/sports\/[^/]+\/odds/i.test(value)) return "Sport odds";
  return value;
}

function getSourceCategory(source?: string | null): UsageCategory {
  const normalized = (source || "").trim().toLowerCase();
  if (BOARD_DROP_SOURCES.has(normalized)) return "board_drop";
  if (JIT_SOURCES.has(normalized)) return "jit";
  if (SETTLEMENT_SOURCES.has(normalized)) return "settlement";
  if (MANUAL_SOURCES.has(normalized)) return "manual";
  if (normalized === "scheduled_scan") return "legacy";
  return "other";
}

function mapToSourceFilter(category: UsageCategory): SourceFilter {
  if (category === "board_drop") return "board_drop";
  if (category === "jit") return "jit";
  if (category === "settlement") return "settlement";
  if (category === "manual" || category === "legacy") return "manual";
  return "other";
}

const CATEGORY_LABELS: Record<UsageCategory, string> = {
  board_drop: "Board drop",
  jit: "JIT CLV",
  settlement: "Settlement",
  manual: "Manual",
  legacy: "Legacy scan",
  other: "Other",
};

function buildUsageRows(
  calls: OddsApiActivityCall[],
  keySelector: (call: OddsApiActivityCall) => string,
  labelSelector: (call: OddsApiActivityCall) => string,
): UsageRow[] {
  const ordered = [...calls].sort((a, b) => {
    const at = parseOpsTimestamp(a.timestamp || null)?.getTime() ?? 0;
    const bt = parseOpsTimestamp(b.timestamp || null)?.getTime() ?? 0;
    return at - bt;
  });
  const map = new Map<string, UsageRow>();
  let previousRemaining: number | null = null;

  for (const call of ordered) {
    const key = keySelector(call);
    const existing = map.get(key) ?? {
      key,
      label: labelSelector(call),
      exactCredits: 0,
      exactCallCount: 0,
      inferredCredits: 0,
      totalCredits: 0,
      callCount: 0,
      errorCount: 0,
      hasExactData: false,
    };
    existing.callCount += 1;
    if (isFailedActivity(call)) existing.errorCount += 1;

    if (typeof call.credits_used_last === "number" && call.credits_used_last >= 0) {
      existing.exactCredits += call.credits_used_last;
      existing.exactCallCount += 1;
      existing.hasExactData = true;
    } else {
      const currentRemaining = parseRemainingValue(call.api_requests_remaining);
      if (previousRemaining !== null && currentRemaining !== null && currentRemaining < previousRemaining) {
        existing.inferredCredits += previousRemaining - currentRemaining;
      }
      if (currentRemaining !== null) previousRemaining = currentRemaining;
    }

    existing.totalCredits = existing.exactCredits + existing.inferredCredits;
    map.set(key, existing);
  }

  return Array.from(map.values()).sort((a, b) => {
    if (b.totalCredits !== a.totalCredits) return b.totalCredits - a.totalCredits;
    return b.callCount - a.callCount;
  });
}

function detectGaps(calls: OddsApiActivityCall[]): GapWarning[] {
  const liveOutbound = calls
    .filter((call) => call.outbound_call_made && !call.cache_hit)
    .sort((a, b) => {
      const at = parseOpsTimestamp(a.timestamp || null)?.getTime() ?? 0;
      const bt = parseOpsTimestamp(b.timestamp || null)?.getTime() ?? 0;
      return at - bt;
    });

  const gaps: GapWarning[] = [];
  for (let index = 1; index < liveOutbound.length; index += 1) {
    const previous = liveOutbound[index - 1];
    const current = liveOutbound[index];
    const previousRemaining = parseRemainingValue(previous.api_requests_remaining);
    const currentRemaining = parseRemainingValue(current.api_requests_remaining);
    if (previousRemaining === null || currentRemaining === null) continue;
    const drop = previousRemaining - currentRemaining;
    if (drop <= 0) continue;

    const currentCost = typeof current.credits_used_last === "number" ? current.credits_used_last : null;
    const unaccountedCredits = currentCost !== null ? drop - currentCost : drop;
    if (unaccountedCredits < 5) continue;

    const previousTimestamp = parseOpsTimestamp(previous.timestamp || null)?.getTime() ?? 0;
    const currentTimestamp = parseOpsTimestamp(current.timestamp || null)?.getTime() ?? 0;
    gaps.push({
      afterTimestamp: previous.timestamp || null,
      beforeTimestamp: current.timestamp || null,
      gapMinutes: Math.round((currentTimestamp - previousTimestamp) / 60000),
      unaccountedCredits,
    });
  }

  return gaps;
}

function deriveOddsApiState(data: OperatorStatusResponse | undefined): HealthState {
  if (!data) return "unknown";
  const keyConfigured = data.runtime?.odds_api_key_configured;
  const summary = data.ops?.odds_api_activity?.summary;
  const errorsLastHour = Number(summary?.errors_last_hour || 0);
  if (keyConfigured === false) return "degraded";
  if (!summary) return "unknown";
  if (errorsLastHour >= 3) return "degraded";
  if (errorsLastHour > 0) return "warning";
  return "healthy";
}

function getStateStyle(state: HealthState): { label: string; className: string } {
  if (state === "healthy") {
    return { label: "Healthy", className: "border-color-profit/30 bg-color-profit-subtle text-color-profit-fg" };
  }
  if (state === "warning") {
    return { label: "Warning", className: "border-primary/35 bg-primary/10 text-primary" };
  }
  if (state === "degraded") {
    return { label: "Degraded", className: "border-color-loss/30 bg-color-loss-subtle text-color-loss-fg" };
  }
  return { label: "Unknown", className: "border-border bg-muted text-muted-foreground" };
}

function normalizeBoardResult(run?: BoardDropRunStatus | null): BoardDropResultSummary | null {
  if (!run) return null;
  const result = run.result ? { ...run.result } : {};
  if (result.straight_sides === undefined && run.straight_sides !== undefined) result.straight_sides = run.straight_sides;
  if (result.props_sides === undefined && run.props_sides !== undefined) result.props_sides = run.props_sides;
  if (result.total_sides === undefined && run.total_sides !== undefined) result.total_sides = run.total_sides;
  if (result.featured_games_count === undefined && run.featured_games_count !== undefined) {
    result.featured_games_count = run.featured_games_count;
  }
  if (result.props_events_scanned === undefined && run.props_events_scanned !== undefined) {
    result.props_events_scanned = run.props_events_scanned;
  }
  if (result.game_line_sports_scanned === undefined && run.game_line_sports_scanned !== undefined) {
    result.game_line_sports_scanned = run.game_line_sports_scanned;
  }
  if (result.duration_ms === undefined && run.duration_ms !== undefined) result.duration_ms = run.duration_ms;
  return Object.keys(result).length > 0 ? result : null;
}

function getBoardRunTimestamp(run?: BoardDropRunStatus | null): string | null {
  if (!run) return null;
  return run.finished_at || run.captured_at || run.started_at || null;
}

function getBoardRunErrorCount(run?: BoardDropRunStatus | null): number {
  if (!run) return 0;
  const explicit = "error_count" in run ? Number((run as { error_count?: number }).error_count || 0) : 0;
  const hard = "hard_errors" in run ? Number((run as { hard_errors?: number }).hard_errors || 0) : 0;
  return explicit || hard;
}

function getPlayerPropsSummary(result?: BoardDropResultSummary | null) {
  return {
    eventsScanned: result?.player_props?.events_scanned ?? result?.props_events_scanned ?? null,
    eventsFetched: result?.player_props?.events_fetched ?? result?.props_events_fetched ?? null,
    eventsWithBothBooks: result?.player_props?.events_with_both_books ?? result?.props_events_with_both_books ?? null,
    apiRequestsRemaining: result?.player_props?.api_requests_remaining ?? result?.props_api_requests_remaining ?? null,
    eventsSkippedPregame: result?.player_props?.events_skipped_pregame ?? result?.props_events_skipped_pregame ?? null,
    eventsWithProviderMarkets:
      result?.player_props?.events_with_provider_markets ?? result?.props_events_with_provider_markets ?? null,
    eventsWithSupportedBookMarkets:
      result?.player_props?.events_with_supported_book_markets ?? result?.props_events_with_supported_book_markets ?? null,
    eventsProviderOnly: result?.player_props?.events_provider_only ?? result?.props_events_provider_only ?? null,
    eventsWithResults: result?.player_props?.events_with_results ?? result?.props_events_with_results ?? null,
    candidateSides: result?.player_props?.candidate_sides ?? result?.props_candidate_sides ?? null,
    qualityGateFiltered: result?.player_props?.quality_gate_filtered ?? result?.props_quality_gate_filtered ?? null,
    qualityGateMinReferenceBookmakers:
      result?.player_props?.quality_gate_min_reference_bookmakers ??
      result?.props_quality_gate_min_reference_bookmakers ??
      null,
    pickemQualityGateMinReferenceBookmakers:
      result?.player_props?.pickem_quality_gate_min_reference_bookmakers ??
      result?.props_pickem_quality_gate_min_reference_bookmakers ??
      null,
    pickemCardsCount: result?.player_props?.pickem_cards_count ?? result?.props_pickem_cards_count ?? null,
    surfacedSides: result?.player_props?.surfaced_sides ?? result?.props_sides ?? null,
    marketsRequested: result?.player_props?.markets_requested ?? [],
    providerMarketEventCounts:
      result?.player_props?.provider_market_event_counts ?? result?.props_provider_market_event_counts ?? null,
    supportedBookMarketEventCounts:
      result?.player_props?.supported_book_market_event_counts ?? result?.props_supported_book_market_event_counts ?? null,
    boardItems: result?.player_props?.board_items ?? result?.player_props_board_artifacts ?? null,
  };
}

function formatMarketCoverageSummary(counts?: Record<string, number> | null): string {
  if (!counts) return "Unknown";
  const entries = Object.entries(counts)
    .filter(([, count]) => typeof count === "number" && count > 0)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
  if (!entries.length) return "None";
  return entries.map(([market, count]) => `${market}: ${count}`).join(" | ");
}

function getGameLinesSummary(result?: BoardDropResultSummary | null) {
  return {
    sportsScanned: result?.game_lines?.sports_scanned ?? result?.game_line_sports_scanned ?? [],
    eventsFetched: result?.game_lines?.events_fetched ?? result?.game_lines_events_fetched ?? null,
    eventsWithBothBooks: result?.game_lines?.events_with_both_books ?? result?.game_lines_events_with_both_books ?? null,
    apiRequestsRemaining: result?.game_lines?.api_requests_remaining ?? result?.game_lines_api_requests_remaining ?? null,
    surfacedSides: result?.game_lines?.surfaced_sides ?? result?.straight_sides ?? null,
    freshSidesCount: result?.game_lines?.fresh_sides_count ?? null,
  };
}

function Row({ label, value, dim }: { label: string; value: string; dim?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-mono text-xs text-right ${dim ? "text-muted-foreground" : ""}`}>{value}</span>
    </div>
  );
}

function MetricTile({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string | null;
  tone?: "default" | "warning" | "danger";
}) {
  const valueClass =
    tone === "danger"
      ? "text-color-loss-fg"
      : tone === "warning"
        ? "text-primary"
        : "text-foreground";
  return (
    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-0.5 text-sm font-semibold ${valueClass}`}>{value}</p>
      {hint ? <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function WarningCallout({ warning }: { warning: BoardWarning }) {
  const className =
    warning.tone === "danger"
      ? "border-color-loss/30 bg-color-loss-subtle text-color-loss-fg"
      : warning.tone === "warning"
        ? "border-primary/35 bg-primary/10 text-primary"
        : "border-border bg-muted/25 text-foreground";
  const mutedClass =
    warning.tone === "info" ? "text-muted-foreground" : warning.tone === "warning" ? "text-primary/80" : "text-color-loss-fg/80";

  return (
    <div className={`rounded border px-2.5 py-2 ${className}`}>
      <p className="text-xs font-semibold">{warning.title}</p>
      <p className={`mt-1 text-[11px] ${mutedClass}`}>{warning.body}</p>
    </div>
  );
}

function formatLiveCacheMix(session: OddsApiActivityScanSession): string {
  const parts: string[] = [];
  const live = Number(session.live_call_count || 0);
  const cache = Number(session.cache_hit_count || 0);
  const other = Number(session.other_count || 0);
  if (live > 0) parts.push(`${live} live`);
  if (cache > 0) parts.push(`${cache} cache`);
  if (other > 0) parts.push(`${other} local`);
  return parts.join(" / ") || "No grouped calls";
}

type Props = {
  data?: OperatorStatusResponse;
};

export function OddsApiActivityCard({ data }: Props) {
  const [showAllCalls, setShowAllCalls] = useState(false);
  const [showBoardDropCalls, setShowBoardDropCalls] = useState(false);
  const [showScanSessions, setShowScanSessions] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");

  const oddsState = useMemo(() => deriveOddsApiState(data), [data]);
  const style = getStateStyle(oddsState);
  const oddsApiActivity = data?.ops?.odds_api_activity;
  const oddsSummary: OddsApiActivitySummary | undefined = oddsApiActivity?.summary;
  const oddsRecentCalls = useMemo(
    () => (Array.isArray(oddsApiActivity?.recent_calls) ? oddsApiActivity?.recent_calls ?? [] : []),
    [oddsApiActivity?.recent_calls],
  );
  const oddsRecentScans = useMemo(
    () => (Array.isArray(oddsApiActivity?.recent_scans) ? oddsApiActivity?.recent_scans ?? [] : []),
    [oddsApiActivity?.recent_scans],
  );

  const schedulerRun = data?.ops?.last_scheduler_scan ?? null;
  const manualRun = data?.ops?.last_ops_trigger_scan ?? null;
  const boardRuns = useMemo<BoardRunDescriptor[]>(
    () =>
      [
        schedulerRun
          ? {
              key: "scheduled" as const,
              label: "Scheduled board drop",
              run: schedulerRun,
              result: normalizeBoardResult(schedulerRun),
              timestamp: getBoardRunTimestamp(schedulerRun),
              errorCount: getBoardRunErrorCount(schedulerRun),
            }
          : null,
        manualRun
          ? {
              key: "manual" as const,
              label: "Ops manual refresh",
              run: manualRun,
              result: normalizeBoardResult(manualRun),
              timestamp: getBoardRunTimestamp(manualRun),
              errorCount: getBoardRunErrorCount(manualRun),
            }
          : null,
      ]
        .filter((run): run is BoardRunDescriptor => Boolean(run))
        .sort((a, b) => {
          const at = parseOpsTimestamp(a.timestamp)?.getTime() ?? 0;
          const bt = parseOpsTimestamp(b.timestamp)?.getTime() ?? 0;
          return bt - at;
        }),
    [manualRun, schedulerRun],
  );
  const latestBoardRun = boardRuns[0] ?? null;

  const remainingSnapshot = useMemo(() => {
    for (const call of oddsRecentCalls) {
      if (call.api_requests_remaining !== null && call.api_requests_remaining !== undefined) {
        return parseRemainingValue(call.api_requests_remaining);
      }
    }
    return null;
  }, [oddsRecentCalls]);

  const boardDropCalls = useMemo(
    () => oddsRecentCalls.filter((call) => BOARD_DROP_SOURCES.has((call.source || "").trim().toLowerCase())),
    [oddsRecentCalls],
  );
  const boardDropErrors =
    oddsApiActivity?.board_drop?.errors ?? boardDropCalls.filter((call) => isFailedActivity(call)).length;
  const boardDropExactCost = useMemo(
    () =>
      boardDropCalls.every((call) => typeof call.credits_used_last === "number")
        ? boardDropCalls.reduce((sum, call) => sum + (call.credits_used_last ?? 0), 0)
        : null,
    [boardDropCalls],
  );

  const usageByCategory = useMemo(
    () =>
      buildUsageRows(
        oddsRecentCalls,
        (call) => getSourceCategory(call.source),
        (call) => CATEGORY_LABELS[getSourceCategory(call.source)],
      ),
    [oddsRecentCalls],
  );
  const usageByEndpoint = useMemo(
    () =>
      buildUsageRows(
        oddsRecentCalls,
        (call) => formatOddsEndpointLabel(call.endpoint),
        (call) => formatOddsEndpointLabel(call.endpoint),
      ),
    [oddsRecentCalls],
  );
  const exactTotalCredits = useMemo(() => usageByCategory.reduce((sum, row) => sum + row.exactCredits, 0), [usageByCategory]);
  const inferredTotalCredits = useMemo(
    () => usageByCategory.reduce((sum, row) => sum + row.inferredCredits, 0),
    [usageByCategory],
  );
  const hasAnyExactData = useMemo(() => usageByCategory.some((row) => row.hasExactData), [usageByCategory]);
  const gaps = useMemo(() => detectGaps(oddsRecentCalls), [oddsRecentCalls]);

  const filteredCalls = useMemo(() => {
    if (sourceFilter === "all") return oddsRecentCalls;
    return oddsRecentCalls.filter((call) => mapToSourceFilter(getSourceCategory(call.source)) === sourceFilter);
  }, [oddsRecentCalls, sourceFilter]);

  const latestResult = latestBoardRun?.result ?? null;
  const latestProps = getPlayerPropsSummary(latestResult);
  const latestGameLines = getGameLinesSummary(latestResult);

  const boardWarnings = useMemo(() => {
    const warnings: BoardWarning[] = [];
    if (!latestBoardRun) {
      warnings.push({
        key: "no-board-run",
        tone: "info",
        title: "No board-drop runs recorded yet",
        body: "The ops dashboard has not captured a scheduled or manual board run yet.",
      });
      return warnings;
    }

    if (
      Number(latestResult?.props_sides || 0) === 0 &&
      Number(latestProps.candidateSides || 0) > 0 &&
      Number(latestProps.qualityGateFiltered || 0) >= Number(latestProps.candidateSides || 0)
    ) {
      warnings.push({
        key: "props-filtered",
        tone: "warning",
        title: "All prop candidates were filtered before publish",
        body: `${latestProps.candidateSides} candidate prop side${Number(latestProps.candidateSides) === 1 ? "" : "s"} were found, but ${latestProps.qualityGateFiltered} were removed by the ${latestProps.qualityGateMinReferenceBookmakers ?? "?"}-book quality gate.`,
      });
    }

    if (Number(latestProps.eventsSkippedPregame || 0) > 0) {
      warnings.push({
        key: "pregame-skips",
        tone: "info",
        title: "Pregame events reduced the usable prop slate",
        body: `${latestProps.eventsSkippedPregame} event${Number(latestProps.eventsSkippedPregame) === 1 ? "" : "s"} were skipped before parsing props. ${scalarOrUnknown(latestProps.eventsWithResults)} event${Number(latestProps.eventsWithResults || 0) === 1 ? "" : "s"} still produced usable results.`,
      });
    }

    if (
      Number(latestProps.eventsWithProviderMarkets || 0) > 0 &&
      Number(latestProps.eventsWithSupportedBookMarkets || 0) < Number(latestProps.eventsWithProviderMarkets || 0)
    ) {
      warnings.push({
        key: "provider-supported-gap",
        tone: "warning",
        title: "Provider coverage is wider than the current supported prop books",
        body: `${scalarOrUnknown(latestProps.eventsWithProviderMarkets)} prop event${Number(latestProps.eventsWithProviderMarkets || 0) === 1 ? "" : "s"} had provider-posted markets, but only ${scalarOrUnknown(latestProps.eventsWithSupportedBookMarkets)} reached the current supported-book set.`,
      });
    }

    if (latestBoardRun.errorCount > 0) {
      warnings.push({
        key: "board-errors",
        tone: "danger",
        title: "The latest board run completed with recorded errors",
        body: `${latestBoardRun.errorCount} board-run error${latestBoardRun.errorCount === 1 ? "" : "s"} were recorded. Check the raw call log below for the failing endpoint.`,
      });
    }

    const deliveryStatus = latestBoardRun.run.board_alert_delivery_status;
    if (deliveryStatus && !["delivered", "not_attempted"].includes(deliveryStatus)) {
      warnings.push({
        key: "board-alert",
        tone: "warning",
        title: "Discord board alert did not deliver cleanly",
        body: `Alert status: ${deliveryStatus}${latestBoardRun.run.board_alert_error ? ` (${latestBoardRun.run.board_alert_error})` : ""}.`,
      });
    }

    if (Number(oddsSummary?.errors_last_hour || 0) > 0 && boardDropErrors > 0) {
      warnings.push({
        key: "recent-api-errors",
        tone: "warning",
        title: "Recent Odds API errors were recorded",
        body: `${scalarOrUnknown(oddsSummary?.errors_last_hour)} raw call error${Number(oddsSummary?.errors_last_hour || 0) === 1 ? "" : "s"} were seen in the last hour, including ${boardDropErrors} tied to board-drop activity.`,
      });
    }

    return warnings.slice(0, 4);
  }, [boardDropErrors, latestBoardRun, latestProps, latestResult, oddsSummary?.errors_last_hour]);

  const boardDropDefaultVisibleCalls = 4;
  const boardDropCallsVisible = showBoardDropCalls
    ? boardDropCalls
    : boardDropCalls.slice(0, boardDropDefaultVisibleCalls);
  const callsDefaultVisible = 6;
  const visibleCalls = showAllCalls ? filteredCalls : filteredCalls.slice(0, callsDefaultVisible);

  return (
    <Card className="md:col-span-2">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">Daily Board Pipeline</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Board-drop workflow diagnostics first, raw Odds API activity second.
            </p>
          </div>
          <span
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${style.className}`}
          >
            {style.label}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 md:grid-cols-4">
          <MetricTile
            label="Remaining quota"
            value={remainingSnapshot === null ? "Unknown" : String(remainingSnapshot)}
            hint={oddsApiActivity?.board_drop?.min_api_requests_remaining !== undefined
              ? `Board run low-water mark: ${formatQuotaLabel(oddsApiActivity.board_drop?.min_api_requests_remaining)}`
              : null}
            tone={remainingSnapshot !== null && remainingSnapshot <= 10 ? "danger" : "default"}
          />
          <MetricTile
            label="Calls last hour"
            value={scalarOrUnknown(oddsSummary?.calls_last_hour)}
            hint={formatTimeWithRelative(oddsSummary?.last_success_at, "No successful live call yet")}
          />
          <MetricTile
            label="Errors last hour"
            value={scalarOrUnknown(oddsSummary?.errors_last_hour)}
            hint={formatTimeWithRelative(oddsSummary?.last_error_at, "No recent errors")}
            tone={Number(oddsSummary?.errors_last_hour || 0) > 0 ? "warning" : "default"}
          />
          <MetricTile
            label="Board-drop call cost"
            value={
              boardDropExactCost !== null
                ? `${boardDropExactCost} exact`
                : boardDropCalls.length > 0
                  ? "Waiting on exact headers"
                  : "No recent calls"
            }
            hint={`${boardDropCalls.length} board-drop call${boardDropCalls.length === 1 ? "" : "s"} logged`}
            tone={boardDropErrors > 0 ? "warning" : "default"}
          />
        </div>

        <div className="grid gap-2 md:grid-cols-2">
          {boardRuns.length === 0 ? (
            <div className="rounded border border-border/70 bg-muted/20 px-3 py-3 text-sm text-muted-foreground">
              No scheduled or manual board-drop run has been recorded yet.
            </div>
          ) : (
            boardRuns.map((boardRun) => {
              const propsSummary = getPlayerPropsSummary(boardRun.result);
              const gameLinesSummary = getGameLinesSummary(boardRun.result);
              const boardItems = propsSummary.boardItems;
              const alertStatus =
                boardRun.run.board_alert_delivery_status ||
                (boardRun.run.board_alert_attempted ? "attempted" : "not_attempted");
              const statusTone =
                boardRun.errorCount > 0
                  ? "border-color-loss/30 bg-color-loss-subtle"
                  : boardRun.key === "scheduled"
                    ? "border-border/70 bg-muted/20"
                    : "border-primary/25 bg-primary/5";

              return (
                <div key={boardRun.key} className={`rounded border px-3 py-3 ${statusTone}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {boardRun.label}
                      </p>
                      <p className="mt-1 text-sm font-medium">
                        {formatTimeWithRelative(boardRun.timestamp, "Not recorded")}
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {boardRun.result?.scan_label || (boardRun.key === "scheduled" ? "Daily scheduled board window" : "Manual ops-triggered refresh")}
                      </p>
                    </div>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                        boardRun.errorCount > 0
                          ? "bg-color-loss-subtle text-color-loss-fg"
                          : "bg-color-profit-subtle text-color-profit-fg"
                      }`}
                    >
                      {boardRun.errorCount > 0 ? `${boardRun.errorCount} issue${boardRun.errorCount === 1 ? "" : "s"}` : "clean"}
                    </span>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <MetricTile label="Straight sides" value={scalarOrUnknown(boardRun.result?.straight_sides)} />
                    <MetricTile label="Props surfaced" value={scalarOrUnknown(boardRun.result?.props_sides)} />
                    <MetricTile label="Prop browse" value={scalarOrUnknown(boardItems?.browse_total)} />
                    <MetricTile label="Prop opportunities" value={scalarOrUnknown(boardItems?.opportunities_total)} />
                    <MetricTile label="Pick'em cards" value={scalarOrUnknown(boardItems?.pickem_total ?? propsSummary.pickemCardsCount)} />
                    <MetricTile label="Featured games" value={scalarOrUnknown(boardRun.result?.featured_games_count)} />
                  </div>

                  <div className="mt-3 space-y-1.5">
                    <Row label="Props events scanned" value={scalarOrUnknown(propsSummary.eventsScanned)} />
                    <Row label="Game-line sports" value={formatSportsList(gameLinesSummary.sportsScanned)} />
                    <Row label="Duration" value={formatDuration(boardRun.result?.duration_ms ?? boardRun.run.duration_ms)} />
                    <Row label="Discord alert" value={alertStatus || "Unknown"} />
                  </div>
                </div>
              );
            })
          )}
        </div>

        {boardWarnings.length > 0 ? (
          <div className="space-y-2">
            {boardWarnings.map((warning) => (
              <WarningCallout key={warning.key} warning={warning} />
            ))}
          </div>
        ) : null}

        <div className="rounded border border-border/70 bg-muted/15 px-3 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Latest Pipeline Snapshot
              </p>
              <p className="mt-1 text-sm font-medium">
                {latestBoardRun
                  ? `${latestBoardRun.label} · ${formatTimeWithRelative(latestBoardRun.timestamp, "Unknown")}`
                  : "No board snapshot yet"}
              </p>
            </div>
            {latestBoardRun?.result?.anchor_time_mst ? (
              <span className="rounded bg-background/70 px-2 py-1 text-[11px] font-mono text-muted-foreground">
                {latestBoardRun.result.anchor_time_mst} MST
              </span>
            ) : null}
          </div>

          {latestBoardRun ? (
            <div className="mt-3 space-y-3">
              <div className="grid gap-2 md:grid-cols-6">
                <MetricTile label="Straight" value={scalarOrUnknown(latestResult?.straight_sides)} />
                <MetricTile label="Props" value={scalarOrUnknown(latestResult?.props_sides)} />
                <MetricTile label="Browse" value={scalarOrUnknown(latestProps.boardItems?.browse_total)} />
                <MetricTile label="Opportunities" value={scalarOrUnknown(latestProps.boardItems?.opportunities_total)} />
                <MetricTile label="Pick'em" value={scalarOrUnknown(latestProps.boardItems?.pickem_total ?? latestProps.pickemCardsCount)} />
                <MetricTile label="Featured" value={scalarOrUnknown(latestResult?.featured_games_count)} />
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded border border-border/70 bg-background/70 px-3 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Player Props Funnel
                  </p>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <MetricTile label="Events scanned" value={scalarOrUnknown(latestProps.eventsScanned)} />
                    <MetricTile label="Fetched" value={scalarOrUnknown(latestProps.eventsFetched)} />
                    <MetricTile
                      label="Pregame skipped"
                      value={scalarOrUnknown(latestProps.eventsSkippedPregame)}
                      tone={Number(latestProps.eventsSkippedPregame || 0) > 0 ? "warning" : "default"}
                    />
                    <MetricTile label="Provider posted" value={scalarOrUnknown(latestProps.eventsWithProviderMarkets)} />
                    <MetricTile
                      label="Supported books"
                      value={scalarOrUnknown(latestProps.eventsWithSupportedBookMarkets)}
                    />
                    <MetricTile
                      label="Provider only"
                      value={scalarOrUnknown(latestProps.eventsProviderOnly)}
                      tone={Number(latestProps.eventsProviderOnly || 0) > 0 ? "warning" : "default"}
                    />
                    <MetricTile label="With results" value={scalarOrUnknown(latestProps.eventsWithResults)} />
                    <MetricTile label="Candidates" value={scalarOrUnknown(latestProps.candidateSides)} />
                    <MetricTile
                      label="Filtered"
                      value={scalarOrUnknown(latestProps.qualityGateFiltered)}
                      tone={Number(latestProps.qualityGateFiltered || 0) > 0 ? "warning" : "default"}
                    />
                    <MetricTile label="Surfaced" value={scalarOrUnknown(latestProps.surfacedSides)} />
                    <MetricTile label="Quota left" value={scalarOrUnknown(latestProps.apiRequestsRemaining)} />
                  </div>
                  <div className="mt-3 space-y-1.5">
                    <Row
                      label="Reference gate"
                      value={
                        latestProps.qualityGateMinReferenceBookmakers === null ||
                        latestProps.qualityGateMinReferenceBookmakers === undefined
                          ? "Unknown"
                          : `${latestProps.qualityGateMinReferenceBookmakers} books`
                      }
                    />
                    <Row
                      label="Pick'em gate"
                      value={
                        latestProps.pickemQualityGateMinReferenceBookmakers === null ||
                        latestProps.pickemQualityGateMinReferenceBookmakers === undefined
                          ? "Unknown"
                          : `${latestProps.pickemQualityGateMinReferenceBookmakers} books`
                      }
                    />
                    <Row
                      label="Markets requested"
                      value={latestProps.marketsRequested.length > 0 ? latestProps.marketsRequested.join(", ") : "Unknown"}
                      dim
                    />
                    <Row
                      label="Provider coverage"
                      value={formatMarketCoverageSummary(latestProps.providerMarketEventCounts)}
                      dim
                    />
                    <Row
                      label="Supported coverage"
                      value={formatMarketCoverageSummary(latestProps.supportedBookMarketEventCounts)}
                      dim
                    />
                  </div>
                </div>

                <div className="rounded border border-border/70 bg-background/70 px-3 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Game Lines And Publish State
                  </p>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <MetricTile label="Sports scanned" value={String(latestGameLines.sportsScanned.length || 0)} hint={formatSportsList(latestGameLines.sportsScanned)} />
                    <MetricTile label="Events fetched" value={scalarOrUnknown(latestGameLines.eventsFetched)} />
                    <MetricTile label="Matched events" value={scalarOrUnknown(latestGameLines.eventsWithBothBooks)} />
                    <MetricTile label="Straight surfaced" value={scalarOrUnknown(latestGameLines.surfacedSides)} />
                    <MetricTile label="Fresh sides" value={scalarOrUnknown(latestGameLines.freshSidesCount)} />
                    <MetricTile label="Quota left" value={scalarOrUnknown(latestGameLines.apiRequestsRemaining)} />
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <MetricTile label="Browse items" value={scalarOrUnknown(latestProps.boardItems?.browse_total)} />
                    <MetricTile label="Opportunity items" value={scalarOrUnknown(latestProps.boardItems?.opportunities_total)} />
                    <MetricTile label="Pick'em items" value={scalarOrUnknown(latestProps.boardItems?.pickem_total)} />
                    <MetricTile label="Legacy props cache" value={scalarOrUnknown(latestProps.boardItems?.legacy_total)} />
                  </div>
                  <div className="mt-3 space-y-1.5">
                    <Row label="Selected games" value={scalarOrUnknown(latestResult?.selected_games_count ?? latestResult?.selected_games?.length)} />
                    <Row label="Props scan event ids" value={scalarOrUnknown(latestResult?.props_scan_event_count ?? latestResult?.props_scan_event_ids?.length)} />
                    <Row label="Total board sides" value={scalarOrUnknown(latestResult?.total_sides)} />
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">No board diagnostics available yet.</p>
          )}
        </div>

        <div className="grid gap-3 md:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded border border-border/70 bg-muted/15 px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Board-Drop Call Log
              </p>
              <span className="text-[11px] text-muted-foreground">
                {boardDropCalls.length} call{boardDropCalls.length === 1 ? "" : "s"}
              </span>
            </div>
            {boardDropCalls.length === 0 ? (
              <p className="mt-3 text-xs text-muted-foreground">No recent board-drop calls captured yet.</p>
            ) : (
              <div className="mt-3 space-y-1.5">
                {boardDropCallsVisible.map((call, index) => {
                  const failed = isFailedActivity(call);
                  return (
                    <div
                      key={`board-call-${call.timestamp || "unknown"}-${index}`}
                      className={`rounded border px-2 py-1.5 text-xs ${
                        failed ? "border-color-loss/25 bg-color-loss-subtle" : "border-border/70 bg-background/70"
                      }`}
                    >
                      <p className="leading-relaxed">
                        {formatCompactTime(call.timestamp)} · {formatOddsEndpointLabel(call.endpoint)} ·{" "}
                        <span className="font-semibold">
                          {typeof call.credits_used_last === "number" ? `${call.credits_used_last} cr` : "cr n/a"}
                        </span>{" "}
                        · {formatQuotaLabel(call.api_requests_remaining)}
                        {typeof call.duration_ms === "number" ? ` · ${Math.round(call.duration_ms)}ms` : ""}
                        {failed ? ` · ${call.status_code ?? "ERR"} ${call.error_type ?? ""}` : ""}
                      </p>
                      {call.endpoint && formatOddsEndpointLabel(call.endpoint) !== call.endpoint ? (
                        <p className="mt-0.5 break-all text-[10px] text-muted-foreground">{call.endpoint}</p>
                      ) : null}
                      {failed && call.error_message ? (
                        <p className="mt-0.5 text-[10px] text-muted-foreground">{call.error_message}</p>
                      ) : null}
                    </div>
                  );
                })}
                {boardDropCalls.length > boardDropDefaultVisibleCalls ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-auto px-0 text-xs"
                    onClick={() => setShowBoardDropCalls((value) => !value)}
                  >
                    {showBoardDropCalls
                      ? "Hide board-drop calls"
                      : `Show ${boardDropCalls.length - boardDropDefaultVisibleCalls} more calls`}
                  </Button>
                ) : null}
              </div>
            )}
          </div>

          <div className="rounded border border-border/70 bg-muted/15 px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Credit Attribution
              </p>
              <span className="text-[11px] font-semibold">
                {hasAnyExactData ? `${exactTotalCredits} exact` : `${inferredTotalCredits} inferred`}
              </span>
            </div>
            {!hasAnyExactData ? (
              <p className="mt-2 text-[11px] text-muted-foreground">
                Exact cost is missing on some calls, so attribution falls back to balance drops between requests.
              </p>
            ) : null}
            <div className="mt-3 space-y-1.5">
              {usageByCategory.length === 0 ? (
                <p className="text-xs text-muted-foreground">No recent call data available.</p>
              ) : (
                usageByCategory.map((row) => (
                  <div key={row.key} className="flex items-center justify-between gap-3 text-xs">
                    <span>{row.label}</span>
                    <span className="font-mono text-right">
                      {row.exactCredits > 0 ? `${row.exactCredits} exact` : row.inferredCredits > 0 ? `${row.inferredCredits} inferred` : "0"}
                      <span className="ml-1.5 text-muted-foreground">
                        {row.callCount} call{row.callCount === 1 ? "" : "s"}
                        {row.errorCount > 0 ? ` · ${row.errorCount} err` : ""}
                      </span>
                    </span>
                  </div>
                ))
              )}
            </div>
            {usageByEndpoint.length > 0 ? (
              <details className="mt-3">
                <summary className="cursor-pointer text-[11px] text-muted-foreground">By endpoint</summary>
                <div className="mt-1.5 space-y-1">
                  {usageByEndpoint.map((row) => (
                    <div key={`endpoint-${row.key}`} className="flex items-center justify-between gap-3 text-xs">
                      <span className="break-all pr-2">{row.label}</span>
                      <span className="shrink-0 font-mono">
                        {row.exactCredits > 0 ? `${row.exactCredits} exact` : `${row.inferredCredits} inferred`}
                        <span className="ml-1 text-muted-foreground">· {row.callCount}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            ) : null}
          </div>
        </div>

        {gaps.length > 0 ? (
          <div className="rounded border border-primary/35 bg-primary/10 px-3 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
              Unaccounted Credit Gaps
            </p>
            <div className="mt-2 space-y-1.5">
              {gaps.map((gap, index) => (
                <p key={`${gap.afterTimestamp}-${gap.beforeTimestamp}-${index}`} className="text-xs text-primary/80">
                  {formatCompactTime(gap.afterTimestamp)} to {formatCompactTime(gap.beforeTimestamp)}:{" "}
                  <span className="font-semibold">{gap.unaccountedCredits} credits</span> drained across a{" "}
                  {gap.gapMinutes}m gap with no logged calls.
                </p>
              ))}
            </div>
          </div>
        ) : null}

        {oddsRecentScans.length > 0 ? (
          <details open={showScanSessions} onToggle={(event) => setShowScanSessions((event.target as HTMLDetailsElement).open)}>
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Call bundles ({oddsRecentScans.length})
            </summary>
            <div className="mt-2 space-y-1.5">
              {oddsRecentScans.slice(0, 6).map((scan, index) => {
                const hasErrors = Boolean(scan.has_errors);
                return (
                  <details
                    key={`${scan.scan_session_id || scan.timestamp || "scan"}-${index}`}
                    className={`rounded border px-2 py-1.5 text-xs ${
                      hasErrors ? "border-color-loss/25 bg-color-loss-subtle" : "border-border/70 bg-background/70"
                    } [&_summary::-webkit-details-marker]:hidden`}
                  >
                    <summary className="cursor-pointer list-none">
                      <p className="leading-relaxed">
                        {formatCompactTime(scan.timestamp)} | {formatOddsSourceLabel(scan.source)} | {formatLiveCacheMix(scan)} |{" "}
                        {scalarOrUnknown(scan.total_events_fetched)} events | {scalarOrUnknown(scan.total_sides)} sides
                      </p>
                    </summary>
                    <div className="mt-2 space-y-1 border-t border-border/50 pt-2">
                      {(scan.details ?? []).map((detail: OddsApiActivityScanDetail, detailIndex) => (
                        <p key={`${detailIndex}-${detail.sport || "sport"}`} className="text-xs leading-relaxed">
                          {formatSportLabel(detail.sport)} · {formatModeLabel(detail.cache_hit, detail.outbound_call_made)} ·{" "}
                          {scalarOrUnknown(detail.events_fetched)} events · {scalarOrUnknown(detail.sides_count)} sides ·{" "}
                          {typeof detail.credits_used_last === "number"
                            ? `${detail.credits_used_last} cr`
                            : formatQuotaLabel(detail.api_requests_remaining)}
                        </p>
                      ))}
                    </div>
                  </details>
                );
              })}
            </div>
          </details>
        ) : null}

        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">All API calls</p>
            <div className="flex flex-wrap gap-1">
              {([
                ["all", "All"],
                ["board_drop", "Board"],
                ["jit", "JIT"],
                ["settlement", "Settle"],
                ["manual", "Manual"],
                ["other", "Other"],
              ] as Array<[SourceFilter, string]>).map(([filter, label]) => (
                <button
                  type="button"
                  key={filter}
                  onClick={() => setSourceFilter(filter)}
                  className={`rounded px-1.5 py-0.5 text-[10px] ${
                    sourceFilter === filter ? "bg-foreground text-background" : "bg-muted text-muted-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {visibleCalls.length === 0 ? (
            <p className="text-xs text-muted-foreground">No calls in this filter.</p>
          ) : (
            <div className="space-y-1">
              {visibleCalls.map((call, index) => {
                const failed = isFailedActivity(call);
                const status = failed
                  ? `${call.status_code ?? "ERR"}${call.error_type ? ` ${call.error_type}` : ""}`
                  : typeof call.status_code === "number"
                    ? String(call.status_code)
                    : "status n/a";
                return (
                  <div
                    key={`${call.timestamp || "unknown"}-${call.source || "source"}-${index}`}
                    className={`rounded border px-2 py-1.5 text-xs ${
                      failed ? "border-color-loss/25 bg-color-loss-subtle" : "border-border/70 bg-muted/20"
                    }`}
                  >
                    <p className="leading-relaxed">
                      {formatCompactTime(call.timestamp)} · {formatOddsSourceLabel(call.source)} · {formatOddsEndpointLabel(call.endpoint)} ·{" "}
                      {status} ·{" "}
                      <span className={typeof call.credits_used_last === "number" ? "font-semibold" : "text-muted-foreground"}>
                        {typeof call.credits_used_last === "number" ? `${call.credits_used_last} cr` : "cr n/a"}
                      </span>{" "}
                      · {formatQuotaLabel(call.api_requests_remaining)}
                      {typeof call.duration_ms === "number" ? ` · ${Math.round(call.duration_ms)}ms` : ""}
                    </p>
                    {call.endpoint && formatOddsEndpointLabel(call.endpoint) !== call.endpoint ? (
                      <p className="mt-0.5 break-all text-[10px] text-muted-foreground">{call.endpoint}</p>
                    ) : null}
                    {failed && call.error_message ? (
                      <p className="mt-0.5 text-[10px] text-muted-foreground">{call.error_message}</p>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}

          {filteredCalls.length > callsDefaultVisible ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-auto px-0 text-xs"
              onClick={() => setShowAllCalls((previous) => !previous)}
            >
              {showAllCalls ? "Show fewer calls" : `Show ${filteredCalls.length - callsDefaultVisible} more calls`}
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
