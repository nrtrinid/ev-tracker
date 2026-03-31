"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCcw, XCircle } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useModelCalibrationSummary, useOperatorStatus, useResearchOpportunitySummary } from "@/lib/hooks";
import type {
  ModelCalibrationBreakdownItem,
  ModelCalibrationRecentComparisonRow,
  OddsApiActivityCall,
  OddsApiActivityScanDetail,
  OddsApiActivityScanSession,
  OddsApiActivitySummary,
  OperatorStatusResponse,
  ResearchOpportunityBreakdownItem,
  ResearchOpportunityRecentRow,
} from "@/lib/types";

type HealthState = "healthy" | "warning" | "degraded" | "unknown";

function parseOpsTimestamp(value?: string | null): Date | null {
  if (!value) return null;
  const raw = value.trim();
  if (!raw) return null;

  // Backend may emit legacy values like 2026-...+00:00Z.
  // Remove trailing Z if an explicit numeric offset already exists.
  const normalized = /[+-]\d{2}:\d{2}Z$/i.test(raw) ? raw.slice(0, -1) : raw;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function formatTime(value?: string | null): string {
  const date = parseOpsTimestamp(value);
  if (!date) return "Unknown";
  return date.toLocaleString();
}

function ageMinutes(value?: string | null): number | null {
  const parsed = parseOpsTimestamp(value);
  if (!parsed) return null;
  const ts = parsed.getTime();
  return Math.max(0, Math.round((Date.now() - ts) / 60000));
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
  const relative = formatRelativeTime(value);
  if (full === "Unknown") return fallback;
  return `${full} (${relative})`;
}

function formatCompactTime(value?: string | null): string {
  const parsed = parseOpsTimestamp(value);
  if (!parsed) return "Unknown";
  return parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function getStateStyle(state: HealthState): { label: string; className: string; icon: typeof CheckCircle2 } {
  if (state === "healthy") {
    return {
      label: "Healthy",
      className: "border-[#4A7C59]/30 bg-[#4A7C59]/10 text-[#2C5235]",
      icon: CheckCircle2,
    };
  }
  if (state === "warning") {
    return {
      label: "Warning",
      className: "border-[#C4A35A]/35 bg-[#C4A35A]/15 text-[#5C4D2E]",
      icon: AlertTriangle,
    };
  }
  if (state === "degraded") {
    return {
      label: "Degraded",
      className: "border-[#B85C38]/30 bg-[#B85C38]/10 text-[#8B3D20]",
      icon: XCircle,
    };
  }
  return {
    label: "Unknown",
    className: "border-border bg-muted text-muted-foreground",
    icon: HelpCircle,
  };
}

function StatusBadge({ state }: { state: HealthState }) {
  const style = getStateStyle(state);
  const Icon = style.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${style.className}`}>
      <Icon className="h-3.5 w-3.5" />
      {style.label}
    </span>
  );
}

function scalarOrUnknown(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "Unknown";
  return String(value);
}

function formatPercentValue(value: number | null | undefined, digits: number = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unknown";
  return `${value.toFixed(digits)}%`;
}

function formatDecimalValue(value: number | null | undefined, digits: number = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unknown";
  return value.toFixed(digits);
}

function yesNoUnknown(value: boolean | undefined): string {
  if (value === undefined) return "Unknown";
  return value ? "Yes" : "No";
}

function normalizeSettleSource(source: string | undefined): "Scheduler" | "Cron" | "Manual" | "Unknown" {
  if (!source) return "Unknown";
  const normalized = source.trim().toLowerCase();
  if (normalized === "scheduler") return "Scheduler";
  if (normalized === "cron" || normalized === "ops_trigger") return "Manual";
  if (normalized === "manual") return "Manual";
  return "Unknown";
}

function schedulerFreshnessLabel(data: OperatorStatusResponse | undefined): string {
  if (!data?.checks) return "Unknown";
  return data.checks.scheduler_freshness ? "Fresh" : "Stale";
}

function deriveScannerState(data: OperatorStatusResponse | undefined): HealthState {
  if (!data) return "unknown";
  const scheduler = data.ops?.last_scheduler_scan;
  const cron = data.ops?.last_ops_trigger_scan;
  const manual = data.ops?.last_manual_scan;
  const schedulerAge = ageMinutes(scheduler?.finished_at || scheduler?.captured_at);
  const cronAge = ageMinutes(cron?.finished_at || cron?.captured_at);
  const manualAge = ageMinutes(manual?.captured_at);
  const checks = data.checks;

  if (checks && checks.scheduler_freshness === false) return "degraded";
  if (schedulerAge === null && cronAge === null && manualAge === null) return "unknown";
  if ((schedulerAge !== null && schedulerAge > 180) || (cronAge !== null && cronAge > 180)) return "warning";
  if (manualAge !== null && manualAge > 180) return "warning";
  return "healthy";
}

function deriveSettlementState(data: OperatorStatusResponse | undefined): HealthState {
  if (!data) return "unknown";
  const settle = data.ops?.last_auto_settle;
  const summary = data.ops?.last_auto_settle_summary;
  const skipTotals = summary?.skipped_totals;
  const skipCount = Object.values(skipTotals || {}).reduce((acc, item) => {
    const parsed = typeof item === "number" ? item : 0;
    return acc + parsed;
  }, 0);

  const actionableSkips = [
    Number(skipTotals?.ambiguous_match || 0),
    Number(skipTotals?.missing_scores || 0),
    Number(skipTotals?.db_update_failed || 0),
    Number(skipTotals?.missing_clv_team || 0),
    Number(skipTotals?.missing_commence_time || 0),
  ].reduce((acc, value) => acc + value, 0);

  if (!settle) return "unknown";
  const settleAge = ageMinutes(settle.finished_at || settle.captured_at);
  if (settleAge !== null && settleAge > 1440) return "degraded";
  // A no_match-only run is common when no pending bets map to completed events yet.
  if (actionableSkips > 0) return "warning";
  if (skipCount > 0 && Number(skipTotals?.no_match || 0) !== skipCount) return "warning";
  return "healthy";
}

function deriveReadinessState(data: OperatorStatusResponse | undefined): HealthState {
  if (!data) return "unknown";
  const checks = data.checks;
  if (!checks) return "unknown";
  if (checks.db_connectivity === false || checks.scheduler_freshness === false) return "degraded";
  if (data.ops?.last_readiness_failure) return "warning";
  return "healthy";
}

function deriveOddsApiState(data: OperatorStatusResponse | undefined): HealthState {
  if (!data) return "unknown";
  const keyConfigured = data.runtime?.odds_api_key_configured;
  const backendSummary = data.ops?.odds_api_activity?.summary;
  const fallback = buildFallbackOddsActivity(data);
  const summary = backendSummary ?? fallback.summary;
  const errorsLastHour = Number(summary?.errors_last_hour || 0);

  if (keyConfigured === false) return "degraded";
  if (!backendSummary && fallback.recentCalls.length === 0 && fallback.recentScans.length === 0) return "unknown";
  if (errorsLastHour >= 3) return "degraded";
  if (errorsLastHour > 0) return "warning";
  return "healthy";
}

function formatSourceLabel(source?: string | null): string {
  const normalized = source?.trim().toLowerCase();
  if (normalized === "manual_scan") return "Manual";
  if (normalized === "scheduled_scan") return "Scheduler";
  if (normalized === "ops_trigger_scan" || normalized === "cron_scan") return "Ops trigger";
  return source || "Unknown";
}

function formatSurfaceLabel(surface?: string | null): string {
  if (surface === "player_props") return "Player props";
  if (surface === "straight_bets") return "Straight bets";
  return "Unknown surface";
}

function formatSportLabel(sport?: string | null): string {
  if (!sport) return "Unknown sport";
  if (sport === "all") return "All sports";
  const parts = sport.split("_").filter(Boolean);
  if (parts.length > 1) return parts[parts.length - 1].toUpperCase();
  return sport.replace(/_/g, " ").toUpperCase();
}

function formatScanScopeLabel(scanScope?: string | null, requestedSport?: string | null): string {
  if (scanScope === "all") return "All sports";
  if (requestedSport) return formatSportLabel(requestedSport);
  return "Single sport";
}

function formatModeLabel(cacheHit?: boolean, outboundCallMade?: boolean): string {
  if (cacheHit) return "cache";
  if (outboundCallMade) return "live";
  return "local";
}

function formatQuotaLabel(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "quota n/a";
  return `${value} left`;
}

function formatLiveCacheMix(session: OddsApiActivityScanSession): string {
  const parts: string[] = [];
  const live = Number(session.live_call_count || 0);
  const cache = Number(session.cache_hit_count || 0);
  const other = Number(session.other_count || 0);
  if (live > 0) parts.push(`${live} live`);
  if (cache > 0) parts.push(`${cache} cache`);
  if (other > 0) parts.push(`${other} local`);
  return parts.join(" / ") || "No scan calls";
}

function isFailedActivity(call: { error_type?: string | null; status_code?: number | null }): boolean {
  return Boolean(call.error_type) || (typeof call.status_code === "number" && call.status_code >= 400);
}

function buildFallbackScanSession({
  timestamp,
  source,
  surface,
  scanScope,
  requestedSport,
  actorLabel,
  runId,
  eventsFetched,
  eventsWithBothBooks,
  totalSides,
  apiRequestsRemaining,
  errorCount,
  errorMessage,
}: {
  timestamp: string | null | undefined;
  source: string;
  surface: "straight_bets" | "player_props";
  scanScope: "all" | "single_sport";
  requestedSport: string | null;
  actorLabel: string | null;
  runId: string | null;
  eventsFetched: number | null | undefined;
  eventsWithBothBooks: number | null | undefined;
  totalSides: number | null | undefined;
  apiRequestsRemaining: string | number | null | undefined;
  errorCount: number;
  errorMessage: string | null;
}): OddsApiActivityScanSession | null {
  if (!timestamp) return null;
  const detail: OddsApiActivityScanDetail = {
    activity_kind: "scan_detail",
    timestamp,
    source,
    surface,
    scan_scope: scanScope,
    requested_sport: requestedSport,
    sport: requestedSport ?? (scanScope === "all" ? "all" : null),
    actor_label: actorLabel,
    run_id: runId,
    cache_hit: false,
    outbound_call_made: true,
    duration_ms: null,
    events_fetched: eventsFetched ?? null,
    events_with_both_books: eventsWithBothBooks ?? null,
    sides_count: totalSides ?? null,
    api_requests_remaining: apiRequestsRemaining ?? null,
    status_code: errorCount > 0 ? 500 : 200,
    error_type: errorCount > 0 ? "ScanError" : null,
    error_message: errorMessage,
  };

  return {
    activity_kind: "scan_session",
    scan_session_id: runId || `${source}-${timestamp}`,
    timestamp,
    source,
    surface,
    scan_scope: scanScope,
    requested_sport: requestedSport,
    actor_label: actorLabel,
    run_id: runId,
    detail_count: 1,
    live_call_count: 1,
    cache_hit_count: 0,
    other_count: 0,
    total_events_fetched: eventsFetched ?? 0,
    total_events_with_both_books: eventsWithBothBooks ?? 0,
    total_sides: totalSides ?? 0,
    min_api_requests_remaining: apiRequestsRemaining ?? null,
    error_count: errorCount,
    has_errors: errorCount > 0,
    details: [detail],
  };
}

function buildFallbackOddsActivity(data: OperatorStatusResponse | undefined): {
  summary: OddsApiActivitySummary;
  recentScans: OddsApiActivityScanSession[];
  recentCalls: OddsApiActivityCall[];
} {
  const scheduler = data?.ops?.last_scheduler_scan;
  const cron = data?.ops?.last_ops_trigger_scan;
  const manual = data?.ops?.last_manual_scan;

  const candidates: OddsApiActivityCall[] = [
    {
      activity_kind: "raw_call" as const,
      timestamp: manual?.captured_at,
      source: "manual_scan",
      endpoint: "/sports/{sport}/odds",
      sport: manual?.sport || null,
      cache_hit: undefined,
      outbound_call_made: true,
      status_code: 200,
      duration_ms: null,
      api_requests_remaining: manual?.api_requests_remaining ?? null,
      error_type: null,
      error_message: null,
    },
    {
      activity_kind: "raw_call" as const,
      timestamp: scheduler?.finished_at || scheduler?.captured_at,
      source: "scheduled_scan",
      endpoint: "/sports/{sport}/odds",
      sport: null,
      cache_hit: undefined,
      outbound_call_made: true,
      status_code: Number(scheduler?.hard_errors || 0) > 0 ? 500 : 200,
      duration_ms: scheduler?.duration_ms ?? null,
      api_requests_remaining: null,
      error_type: Number(scheduler?.hard_errors || 0) > 0 ? "ScanError" : null,
      error_message: Number(scheduler?.hard_errors || 0) > 0 ? `${scheduler?.hard_errors} sport scan error(s)` : null,
    },
    {
      activity_kind: "raw_call" as const,
      timestamp: cron?.finished_at || cron?.captured_at,
      source: "ops_trigger_scan",
      endpoint: "/sports/{sport}/odds",
      sport: null,
      cache_hit: undefined,
      outbound_call_made: true,
      status_code: Number(cron?.error_count || 0) > 0 ? 500 : 200,
      duration_ms: cron?.duration_ms ?? null,
      api_requests_remaining: null,
      error_type: Number(cron?.error_count || 0) > 0 ? "ScanError" : null,
      error_message: Number(cron?.error_count || 0) > 0 ? `${cron?.error_count} sport scan error(s)` : null,
    },
  ].filter((entry) => Boolean(entry.timestamp));

  const sorted = [...candidates].sort((a, b) => {
    const at = parseOpsTimestamp(a.timestamp || null)?.getTime() || 0;
    const bt = parseOpsTimestamp(b.timestamp || null)?.getTime() || 0;
    return bt - at;
  });

  const nowMs = Date.now();
  const callsLastHour = sorted.filter((entry) => {
    const ts = parseOpsTimestamp(entry.timestamp || null)?.getTime();
    return typeof ts === "number" && nowMs - ts <= 3600 * 1000;
  }).length;

  const errorsLastHour = sorted.filter((entry) => {
    const ts = parseOpsTimestamp(entry.timestamp || null)?.getTime();
    if (typeof ts !== "number" || nowMs - ts > 3600 * 1000) return false;
    return Boolean(entry.error_type) || (typeof entry.status_code === "number" && entry.status_code >= 400);
  }).length;

  const lastSuccessAt = sorted.find((entry) => !entry.error_type && (entry.status_code || 0) < 400)?.timestamp || null;
  const lastErrorAt = sorted.find((entry) => Boolean(entry.error_type) || (typeof entry.status_code === "number" && entry.status_code >= 400))?.timestamp || null;
  const fallbackScans = [
    buildFallbackScanSession({
      timestamp: manual?.captured_at,
      source: "manual_scan",
      surface: "straight_bets",
      scanScope: manual?.sport && manual.sport !== "all" ? "single_sport" : "all",
      requestedSport: manual?.sport && manual.sport !== "all" ? manual.sport : null,
      actorLabel: null,
      runId: null,
      eventsFetched: manual?.events_fetched ?? null,
      eventsWithBothBooks: manual?.events_with_both_books ?? null,
      totalSides: manual?.total_sides ?? null,
      apiRequestsRemaining: manual?.api_requests_remaining ?? null,
      errorCount: 0,
      errorMessage: null,
    }),
    buildFallbackScanSession({
      timestamp: scheduler?.finished_at || scheduler?.captured_at,
      source: "scheduled_scan",
      surface: "straight_bets",
      scanScope: "all",
      requestedSport: null,
      actorLabel: null,
      runId: scheduler?.run_id ?? null,
      eventsFetched: null,
      eventsWithBothBooks: null,
      totalSides: scheduler?.total_sides ?? null,
      apiRequestsRemaining: null,
      errorCount: Number(scheduler?.hard_errors || 0),
      errorMessage: Number(scheduler?.hard_errors || 0) > 0 ? `${scheduler?.hard_errors} sport scan error(s)` : null,
    }),
    buildFallbackScanSession({
      timestamp: cron?.finished_at || cron?.captured_at,
      source: "ops_trigger_scan",
      surface: "straight_bets",
      scanScope: "all",
      requestedSport: null,
      actorLabel: null,
      runId: cron?.run_id ?? null,
      eventsFetched: null,
      eventsWithBothBooks: null,
      totalSides: cron?.total_sides ?? null,
      apiRequestsRemaining: null,
      errorCount: Number(cron?.error_count || 0),
      errorMessage: Number(cron?.error_count || 0) > 0 ? `${cron?.error_count} sport scan error(s)` : null,
    }),
  ].filter((entry): entry is OddsApiActivityScanSession => Boolean(entry));

  return {
    summary: {
      calls_last_hour: callsLastHour,
      errors_last_hour: errorsLastHour,
      last_success_at: lastSuccessAt,
      last_error_at: lastErrorAt,
    },
    recentScans: fallbackScans,
    recentCalls: sorted,
  };
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-xs text-right">{value}</span>
    </div>
  );
}

function BreakdownChips({
  title,
  rows,
}: {
  title: string;
  rows: ResearchOpportunityBreakdownItem[];
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground">{title}</p>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No data yet.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {rows.map((row) => (
            <span key={`${title}-${row.key}`} className="rounded bg-muted px-2 py-1 text-[11px] font-mono">
              {row.key}: {row.captured_count} captured | {formatPercentValue(row.beat_close_pct)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function CalibrationBreakdownChips({
  title,
  rows,
}: {
  title: string;
  rows: ModelCalibrationBreakdownItem[];
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground">{title}</p>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No data yet.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {rows.map((row) => (
            <span key={`${title}-${row.key}`} className="rounded bg-muted px-2 py-1 text-[11px] font-mono">
              {row.key}: {row.valid_close_count} valid | Brier {formatDecimalValue(row.avg_brier_score)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function formatAmericanOdds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unknown";
  return value > 0 ? `+${value}` : String(value);
}

function formatMarketLabel(value?: string | null): string {
  if (!value) return "Unknown market";
  return value.replace(/_/g, " ");
}

function formatPropLine(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return Number.isInteger(value) ? String(value) : String(value);
}

function formatResearchPrimaryLabel(row: ResearchOpportunityRecentRow): string {
  if (row.surface === "player_props") {
    const player = row.player_name || row.team || "Unknown player";
    const side = row.selection_side ? row.selection_side.toLowerCase() : "line";
    const line = formatPropLine(row.line_value);
    const market = formatMarketLabel(row.market || row.source_market_key);
    return `${player} ${side}${line ? ` ${line}` : ""} ${market} @ ${row.sportsbook}`;
  }
  return `${row.team} @ ${row.sportsbook}`;
}

function formatResearchCloseLabel(row: ResearchOpportunityRecentRow): string {
  if (row.reference_odds_at_close === null || row.reference_odds_at_close === undefined) {
    return "pending";
  }
  return formatAmericanOdds(row.reference_odds_at_close);
}

function formatCloseQuality(value?: string | null): string {
  if (value === "paired") return "paired";
  if (value === "single") return "fallback";
  return "pending";
}

function deriveCalibrationGateState(passes: boolean | undefined, eligible: boolean | undefined): HealthState {
  if (passes) return "healthy";
  if (eligible) return "warning";
  if (eligible === false) return "unknown";
  return "unknown";
}

function CalibrationRecentList({
  rows,
}: {
  rows: ModelCalibrationRecentComparisonRow[];
}) {
  if (rows.length === 0) return <p className="text-xs text-muted-foreground">No side-by-side comparisons yet.</p>;

  return (
    <div className="space-y-1.5">
      {rows.map((row) => (
        <div key={row.opportunity_key} className="rounded border border-border/70 bg-muted/20 px-2 py-1.5 text-xs">
          <p className="leading-relaxed">
            {formatCompactTime(row.first_seen_at)} | {row.sport} | {row.player_name || row.event} | {row.selection_side || "side"}
            {row.line_value !== null && row.line_value !== undefined ? ` ${row.line_value}` : ""}
            {" | "}
            {row.baseline_model_key || "baseline"} {formatPercentValue(row.baseline_ev_percentage)}
            {" vs "}
            {row.candidate_model_key || "candidate"} {formatPercentValue(row.candidate_ev_percentage)}
            {" | Close "}
            {formatCloseQuality(row.close_quality)}
            {" | CLV "}
            {formatPercentValue(row.baseline_clv_ev_percent)}
            {" / "}
            {formatPercentValue(row.candidate_clv_ev_percent)}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">{row.event} @ {row.sportsbook}</p>
        </div>
      ))}
    </div>
  );
}

function ResearchRecentList({
  title,
  rows,
}: {
  title: string;
  rows: ResearchOpportunityRecentRow[];
}) {
  if (rows.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground">{title}</p>
      <div className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.opportunity_key} className="rounded border border-border/70 bg-muted/20 px-2 py-1.5 text-xs">
            <p className="leading-relaxed">
              {formatCompactTime(row.first_seen_at)} • {row.first_source} • {row.sport} • {formatResearchPrimaryLabel(row)}
              {" • "}
              EV {formatPercentValue(row.first_ev_percentage)}
              {" • "}
              Odds {formatAmericanOdds(row.first_book_odds)}
              {" • "}
              Close {formatResearchCloseLabel(row)}
              {" • "}
              CLV {formatPercentValue(row.clv_ev_percent)}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">{row.event}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function OpsDashboard() {
  const query = useOperatorStatus();
  const researchQuery = useResearchOpportunitySummary();
  const calibrationQuery = useModelCalibrationSummary();
  const [showAllOddsScans, setShowAllOddsScans] = useState(false);
  const [showAllOddsCalls, setShowAllOddsCalls] = useState(false);
  const queryErrorMessage = query.error instanceof Error ? query.error.message : null;
  const researchErrorMessage = researchQuery.error instanceof Error ? researchQuery.error.message : null;
  const calibrationErrorMessage = calibrationQuery.error instanceof Error ? calibrationQuery.error.message : null;

  const automationState = useMemo(() => deriveScannerState(query.data), [query.data]);
  const settlementState = useMemo(() => deriveSettlementState(query.data), [query.data]);
  const readinessState = useMemo(() => deriveReadinessState(query.data), [query.data]);
  const oddsApiState = useMemo(() => deriveOddsApiState(query.data), [query.data]);

  const schedulerScan = query.data?.ops?.last_scheduler_scan;
  const cronScan = query.data?.ops?.last_ops_trigger_scan;
  const manualScan = query.data?.ops?.last_manual_scan;
  const autoSettle = query.data?.ops?.last_auto_settle;
  const readinessFailure = query.data?.ops?.last_readiness_failure;
  const settleSummary = query.data?.ops?.last_auto_settle_summary;
  const oddsApiActivity = query.data?.ops?.odds_api_activity;
  const oddsFallback = useMemo(() => buildFallbackOddsActivity(query.data), [query.data]);
  const oddsSummary = oddsApiActivity?.summary ?? oddsFallback.summary;
  const oddsRecentScans = Array.isArray(oddsApiActivity?.recent_scans) && oddsApiActivity.recent_scans.length > 0
    ? oddsApiActivity.recent_scans
    : oddsFallback.recentScans;
  const oddsRecentCalls = Array.isArray(oddsApiActivity?.recent_calls) && oddsApiActivity.recent_calls.length > 0
    ? oddsApiActivity.recent_calls
    : oddsFallback.recentCalls;
  const oddsScansDefaultVisible = 6;
  const oddsCallsDefaultVisible = 4;
  const oddsVisibleScans = showAllOddsScans ? oddsRecentScans : oddsRecentScans.slice(0, oddsScansDefaultVisible);
  const oddsVisibleCalls = showAllOddsCalls ? oddsRecentCalls : oddsRecentCalls.slice(0, oddsCallsDefaultVisible);
  const schedulerExpected = query.data?.runtime?.scheduler_expected;
  const noScanRunsYet = !schedulerScan && !cronScan && !manualScan;
  const noSettlementRunsYet = !autoSettle && !settleSummary;

  const skippedTotals = settleSummary?.skipped_totals || {};
  const skippedEntries = Object.entries(skippedTotals);
  const settleSource = normalizeSettleSource(autoSettle?.source);
  const fallbackAvailable = yesNoUnknown(query.data?.runtime?.cron_token_configured);
  const research = researchQuery.data;
  const calibration = calibrationQuery.data;
  const recentResearch = research?.recent_opportunities ?? [];
  const recentStraightResearch = recentResearch.filter((row) => row.surface !== "player_props");
  const recentPropResearch = recentResearch.filter((row) => row.surface === "player_props");
  const gateState = deriveCalibrationGateState(calibration?.release_gate?.passes, calibration?.release_gate?.eligible);

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-4xl px-4 py-6 space-y-4 pb-20">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Operator Status</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Internal runtime and automation visibility for scanner and settlement health.
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Last snapshot: {formatTime(query.data?.timestamp)}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              query.refetch();
              researchQuery.refetch();
              calibrationQuery.refetch();
            }}
            disabled={query.isFetching || researchQuery.isFetching || calibrationQuery.isFetching}
          >
            <RefreshCcw className={`h-4 w-4 mr-1.5 ${(query.isFetching || researchQuery.isFetching || calibrationQuery.isFetching) ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {query.isError && (
          <Card className="border-[#B85C38]/30 bg-[#B85C38]/10">
            <CardContent className="pt-6 text-sm text-[#8B3D20]">
              <p>Operator status is temporarily unavailable. Customer-facing pages continue to run normally.</p>
              {queryErrorMessage && (
                <p className="mt-2 text-xs font-mono">Details: {queryErrorMessage}</p>
              )}
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Automation Health</h2>
                <StatusBadge state={automationState} />
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <Row label="Primary mode" value="Scheduler" />
              <Row label="Last scheduler scan" value={formatTime(schedulerScan?.finished_at || schedulerScan?.captured_at)} />
              <Row label="Scheduler freshness" value={schedulerFreshnessLabel(query.data)} />
              <Row label="Last settle run" value={formatTime(autoSettle?.finished_at || autoSettle?.captured_at)} />
              <Row label="Last settle source" value={settleSource} />

              <div className="mt-3 rounded-md border border-border/60 bg-muted/30 p-2.5 space-y-1.5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Fallback Trigger Path</p>
                <Row label="Available" value={fallbackAvailable} />
                <Row label="Last ops-triggered run" value={formatTime(cronScan?.finished_at || cronScan?.captured_at)} />
                <p className="text-[11px] text-muted-foreground">Note: backup/manual use only</p>
              </div>

              {noScanRunsYet && (
                <p className="text-xs text-muted-foreground pt-1">
                  No scheduler or cron scans recorded yet. This is expected in local development until a run is triggered.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Settlement Health</h2>
                <StatusBadge state={settlementState} />
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <Row label="Last auto-settle run" value={formatTime(autoSettle?.finished_at || autoSettle?.captured_at)} />
              <Row label="Settled count" value={scalarOrUnknown(autoSettle?.settled ?? settleSummary?.total_settled)} />
              <Row label="Summary captured" value={formatTime(settleSummary?.captured_at)} />
              {skippedEntries.length ? (
                <div className="pt-1">
                  <p className="text-xs text-muted-foreground mb-1">Skipped totals</p>
                  <div className="flex flex-wrap gap-1.5">
                    {skippedEntries.map(([key, value]) => (
                      <span key={key} className="rounded bg-muted px-2 py-1 text-[11px] font-mono">
                        {key}: {scalarOrUnknown(value as number)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No skip totals recorded yet.</p>
              )}
              {noSettlementRunsYet && (
                <p className="text-xs text-muted-foreground">
                  No auto-settlement runs recorded yet. In local mode this is normal before first run.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Readiness / Runtime Health</h2>
                <StatusBadge state={readinessState} />
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <Row
                label="DB connectivity"
                value={query.data?.checks?.db_connectivity === undefined
                  ? "Unknown"
                  : query.data.checks.db_connectivity
                    ? "OK"
                    : "Failing"}
              />
              <Row
                label="Scheduler freshness"
                value={query.data?.checks?.scheduler_freshness === undefined
                  ? "Unknown"
                  : query.data.checks.scheduler_freshness
                    ? "Fresh"
                    : "Stale"}
              />
              <Row label="Environment" value={query.data?.runtime?.environment || "Unknown"} />
              <Row label="Redis configured" value={yesNoUnknown(query.data?.runtime?.redis_configured)} />
              {schedulerExpected === false && (
                <p className="text-xs text-muted-foreground pt-1">
                  Scheduler is disabled in this environment. Scan and settlement snapshots update when cron endpoints are called.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Odds API Activity</h2>
                <StatusBadge state={oddsApiState} />
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Calls (last hour)</p>
                  <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(oddsSummary?.calls_last_hour)}</p>
                </div>
                <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Errors (last hour)</p>
                  <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(oddsSummary?.errors_last_hour)}</p>
                </div>
                <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Last success</p>
                  <p className="text-xs mt-0.5">{formatTimeWithRelative(oddsSummary?.last_success_at, "Unknown")}</p>
                </div>
                <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Last error</p>
                  <p className="text-xs mt-0.5">{formatTimeWithRelative(oddsSummary?.last_error_at, "No recent errors")}</p>
                </div>
              </div>

              <div className="space-y-1.5">
                <p className="text-xs text-muted-foreground">Recent scans</p>
                {oddsVisibleScans.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No grouped scan activity recorded yet.</p>
                ) : (
                  <div className="space-y-1.5">
                    {oddsVisibleScans.map((scan, index) => {
                      const hasErrors = Boolean(scan.has_errors);
                      const styleClass = hasErrors
                        ? "border-[#B85C38]/25 bg-[#B85C38]/10"
                        : Number(scan.cache_hit_count || 0) > 0 && Number(scan.live_call_count || 0) === 0
                          ? "border-[#4A7C59]/25 bg-[#4A7C59]/10"
                          : "border-border/70 bg-muted/20";
                      const statusLabel = hasErrors
                        ? `${scan.error_count || 1} issue${Number(scan.error_count || 0) === 1 ? "" : "s"}`
                        : "OK";

                      return (
                        <details
                          key={`${scan.scan_session_id || scan.timestamp || "scan"}-${index}`}
                          className={`rounded border px-2 py-1.5 text-xs ${styleClass} [&_summary::-webkit-details-marker]:hidden`}
                        >
                          <summary className="cursor-pointer list-none">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="leading-relaxed">
                                  {formatCompactTime(scan.timestamp)} | {formatSourceLabel(scan.source)} | {formatSurfaceLabel(scan.surface)} | {formatScanScopeLabel(scan.scan_scope, scan.requested_sport)}
                                  {scan.actor_label ? ` | ${scan.actor_label}` : ""}
                                </p>
                                <p className="mt-1 text-[11px] text-muted-foreground">
                                  {formatLiveCacheMix(scan)} | {scalarOrUnknown(scan.total_events_fetched)} events | {scalarOrUnknown(scan.total_sides)} sides | {formatQuotaLabel(scan.min_api_requests_remaining)}
                                </p>
                              </div>
                              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ${hasErrors ? "bg-[#B85C38]/15 text-[#8B3D20]" : "bg-[#4A7C59]/15 text-[#2C5235]"}`}>
                                {statusLabel}
                              </span>
                            </div>
                          </summary>

                          <div className="mt-2 space-y-1.5 border-t border-border/50 pt-2">
                            {(scan.details ?? []).map((detail, detailIndex) => {
                              const detailFailed = isFailedActivity(detail);
                              const detailStyle = detailFailed
                                ? "border-[#B85C38]/25 bg-[#B85C38]/5"
                                : detail.cache_hit
                                  ? "border-[#4A7C59]/25 bg-[#4A7C59]/5"
                                  : "border-border/60 bg-background/60";
                              const detailStatus = detailFailed
                                ? `${detail.status_code ?? "ERR"}${detail.error_type ? ` ${detail.error_type}` : ""}`
                                : formatModeLabel(detail.cache_hit, detail.outbound_call_made);
                              const latency = typeof detail.duration_ms === "number" ? `${Math.round(detail.duration_ms)}ms` : "time n/a";

                              return (
                                <div key={`${detail.sport || "sport"}-${detailIndex}`} className={`rounded border px-2 py-1.5 ${detailStyle}`}>
                                  <p className="leading-relaxed">
                                    {formatSportLabel(detail.sport)} | {detailStatus} | {latency} | {scalarOrUnknown(detail.events_fetched)} events | matched {scalarOrUnknown(detail.events_with_both_books)} | {scalarOrUnknown(detail.sides_count)} sides | {formatQuotaLabel(detail.api_requests_remaining)}
                                  </p>
                                  {detail.error_message && (
                                    <p className="text-[11px] text-muted-foreground mt-1">{detail.error_message}</p>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </details>
                      );
                    })}
                  </div>
                )}
              </div>

              {oddsRecentScans.length > oddsScansDefaultVisible && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="px-0 h-auto text-xs"
                  onClick={() => setShowAllOddsScans((prev) => !prev)}
                >
                  {showAllOddsScans ? "Show fewer scans" : `Show more scans (${oddsRecentScans.length - oddsScansDefaultVisible} more)`}
                </Button>
              )}

              <div className="space-y-1.5">
                <p className="text-xs text-muted-foreground">Other calls</p>
                {oddsVisibleCalls.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No non-scan Odds API calls recorded yet.</p>
                ) : (
                  <div className="space-y-1.5">
                    {oddsVisibleCalls.map((call, index) => {
                      const isFailed = Boolean(call.error_type) || (typeof call.status_code === "number" && call.status_code >= 400);
                      const styleClass = isFailed
                        ? "border-[#B85C38]/25 bg-[#B85C38]/10"
                        : call.cache_hit
                          ? "border-[#4A7C59]/25 bg-[#4A7C59]/10"
                          : "border-border/70 bg-muted/20";
                      const source = call.source || "unknown_source";
                      const endpoint = call.endpoint || "endpoint";
                      const sport = call.sport || "-";
                      const status = isFailed
                        ? `${call.status_code ?? "ERR"}${call.error_type ? ` ${call.error_type}` : ""}`
                        : typeof call.status_code === "number"
                          ? String(call.status_code)
                          : call.cache_hit
                            ? "cache hit"
                            : "status n/a";
                      const latency = typeof call.duration_ms === "number" ? `${Math.round(call.duration_ms)}ms` : null;
                      const mode = call.cache_hit ? "cache" : call.outbound_call_made ? "live" : "local";
                      const quota = call.api_requests_remaining === null || call.api_requests_remaining === undefined
                        ? "Quota remaining unavailable"
                        : `${call.api_requests_remaining} remaining`;

                      return (
                        <div key={`${call.timestamp || "unknown"}-${source}-${index}`} className={`rounded border px-2 py-1.5 text-xs ${styleClass}`}>
                          <p className="leading-relaxed">
                            {formatCompactTime(call.timestamp)} • {source} • {endpoint} {sport !== "-" ? sport : ""} • {status}
                            {latency ? ` • ${latency}` : ""} • {mode} • {quota}
                          </p>
                          {isFailed && call.error_message && (
                            <p className="text-[11px] text-muted-foreground mt-1">{call.error_message}</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {oddsRecentCalls.length > oddsCallsDefaultVisible && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="px-0 h-auto text-xs"
                  onClick={() => setShowAllOddsCalls((prev) => !prev)}
                >
                  {showAllOddsCalls ? "Show fewer calls" : `Show more calls (${oddsRecentCalls.length - oddsCallsDefaultVisible} more)`}
                </Button>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <h2 className="font-semibold">Recent Failures / Warnings</h2>
            </CardHeader>
            <CardContent className="space-y-2">
              <Row label="Last readiness failure" value={formatTime(readinessFailure?.captured_at)} />
              <Row label="Last readiness DB error" value={readinessFailure?.db_error || "None"} />
              <Row label="Auto-settle source" value={autoSettle?.source || "Unknown"} />
              <Row label="Auto-settle run id" value={autoSettle?.run_id || "Unknown"} />
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Research Tracker</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Fresh scanner opportunities captured into the internal research ledger.
                  </p>
                </div>
                {research && (
                  <span className="rounded-md border border-border bg-muted px-2 py-1 text-xs font-medium">
                    {research.captured_count} captured
                  </span>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {researchQuery.isError ? (
                <p className="text-sm text-muted-foreground">
                  Research summary unavailable{researchErrorMessage ? `: ${researchErrorMessage}` : "."}
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Captured</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.captured_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Open</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.open_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Close Captured</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.close_captured_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">CLV Ready</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.clv_ready_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Beat Close</p>
                      <p className="text-sm font-semibold mt-0.5">{formatPercentValue(research?.beat_close_pct)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Avg CLV</p>
                      <p className="text-sm font-semibold mt-0.5">{formatPercentValue(research?.avg_clv_percent)}</p>
                    </div>
                  </div>

                  <BreakdownChips title="By Surface" rows={research?.by_surface ?? []} />
                  <BreakdownChips title="By Source" rows={research?.by_source ?? []} />
                  <BreakdownChips title="By Sportsbook" rows={research?.by_sportsbook ?? []} />
                  <BreakdownChips title="By Edge Bucket" rows={research?.by_edge_bucket ?? []} />
                  <BreakdownChips title="By Odds Bucket" rows={research?.by_odds_bucket ?? []} />

                  <div className="space-y-1.5">
                    <p className="text-xs text-muted-foreground">Recent opportunities</p>
                    <p className="text-[11px] text-muted-foreground">
                      Close pending means the final reference is still waiting for the last 20-minute pregame window.
                    </p>
                    {recentResearch.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No captured opportunities yet.</p>
                    ) : (
                      <div className="space-y-3">
                        <ResearchRecentList title="Straight Bets" rows={recentStraightResearch} />
                        <ResearchRecentList title="Player Props" rows={recentPropResearch} />
                      </div>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Model Calibration</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Live vs shadow props-model tracking, paired-close coverage, and promotion gates.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge state={gateState} />
                  {calibration && (
                    <span className="rounded-md border border-border bg-muted px-2 py-1 text-xs font-medium">
                      {calibration.valid_close_count} valid closes
                    </span>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {calibrationQuery.isError ? (
                <p className="text-sm text-muted-foreground">
                  Model calibration summary unavailable{calibrationErrorMessage ? `: ${calibrationErrorMessage}` : "."}
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Captured Evals</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(calibration?.captured_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Valid Closes</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(calibration?.valid_close_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Paired Close %</p>
                      <p className="text-sm font-semibold mt-0.5">{formatPercentValue(calibration?.paired_close_pct)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Promotion Gate</p>
                      <p className="text-sm font-semibold mt-0.5">
                        {calibration?.release_gate?.passes ? "Pass" : calibration?.release_gate?.eligible ? "Hold" : "Not ready"}
                      </p>
                    </div>
                  </div>

                  <div className="rounded border border-border/70 bg-muted/20 p-3 space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium">Shadow Release Gate</p>
                      <span className="rounded bg-background px-2 py-1 text-[11px] font-mono">
                        {calibration?.release_gate?.baseline_model_key || "baseline"} to {calibration?.release_gate?.candidate_model_key || "candidate"}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      <div className="rounded border border-border/60 bg-background/70 px-2 py-2">
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Baseline Brier</p>
                        <p className="text-sm font-semibold mt-0.5">{formatDecimalValue(calibration?.release_gate?.baseline_avg_brier_score)}</p>
                      </div>
                      <div className="rounded border border-border/60 bg-background/70 px-2 py-2">
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Shadow Brier</p>
                        <p className="text-sm font-semibold mt-0.5">{formatDecimalValue(calibration?.release_gate?.candidate_avg_brier_score)}</p>
                      </div>
                      <div className="rounded border border-border/60 bg-background/70 px-2 py-2">
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Baseline Log Loss</p>
                        <p className="text-sm font-semibold mt-0.5">{formatDecimalValue(calibration?.release_gate?.baseline_avg_log_loss)}</p>
                      </div>
                      <div className="rounded border border-border/60 bg-background/70 px-2 py-2">
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Shadow Log Loss</p>
                        <p className="text-sm font-semibold mt-0.5">{formatDecimalValue(calibration?.release_gate?.candidate_avg_log_loss)}</p>
                      </div>
                    </div>
                    <div className="space-y-1">
                      {(calibration?.release_gate?.reasons ?? []).map((reason, index) => (
                        <p key={`${reason}-${index}`} className="text-[11px] text-muted-foreground">
                          {index + 1}. {reason}
                        </p>
                      ))}
                    </div>
                  </div>

                  <CalibrationBreakdownChips title="By Model" rows={calibration?.by_model ?? []} />
                  <CalibrationBreakdownChips title="By Interpolation Mode" rows={calibration?.by_interpolation_mode ?? []} />
                  <CalibrationBreakdownChips title="By Market" rows={(calibration?.by_market ?? []).slice(0, 8)} />
                  <CalibrationBreakdownChips title="By Sportsbook" rows={(calibration?.by_sportsbook ?? []).slice(0, 8)} />

                  <div className="space-y-1.5">
                    <p className="text-xs text-muted-foreground">Recent live vs shadow comparisons</p>
                    <p className="text-[11px] text-muted-foreground">
                      Paired closes use both sides of the final reference market. Fallback closes use single-side CLV math.
                    </p>
                    <CalibrationRecentList rows={calibration?.recent_comparisons ?? []} />
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
