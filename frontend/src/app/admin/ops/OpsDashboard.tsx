"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCcw, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { adminRefreshMarkets, adminTriggerAutoSettle } from "@/lib/api";
import { useAnalyticsSummary, useAnalyticsUserDrilldown, useOperatorStatus } from "@/lib/hooks";
import { OddsApiActivityCard } from "./OddsApiActivityCard";
import type {
  AutoSettleRunStatus,
  AutoSettleSummary,
  BoardDropResultSummary,
  BoardDropRunStatus,
  OddsApiActivityCall,
  OddsApiActivityScanDetail,
  OddsApiActivityScanSession,
  OddsApiActivitySummary,
  OperatorStatusResponse,
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

function formatIsoWithRelative(value?: string | null): string {
  if (!value) return "-";
  const parsed = parseOpsTimestamp(value);
  if (!parsed) return "-";
  return `${parsed.toLocaleString()} (${formatRelativeTime(value)})`;
}

function formatTutorialStatusLabel(value: string | null | undefined): string {
  if (value === "completed") return "Completed";
  if (value === "started") return "Started";
  if (value === "skipped") return "Skipped";
  return "Not started";
}

function followUpTagClass(tag: string): string {
  if (tag === "recent_failure") return "border-[#B85C38]/35 bg-[#B85C38]/12 text-[#8B3D20]";
  if (tag === "stuck_pre_bet") return "border-[#C4A35A]/35 bg-[#C4A35A]/15 text-[#5C4D2E]";
  if (tag === "inactive") return "border-border bg-muted/40 text-muted-foreground";
  if (tag === "high_signal_tester") return "border-[#4A7C59]/35 bg-[#4A7C59]/12 text-[#2C5235]";
  return "border-border bg-muted/20 text-muted-foreground";
}

function formatFollowUpTagLabel(tag: string): string {
  if (tag === "recent_failure") return "Recent failure";
  if (tag === "stuck_pre_bet") return "Stuck pre-bet";
  if (tag === "inactive") return "Inactive";
  if (tag === "high_signal_tester") return "High signal";
  return "Active";
}

function formatAnalyticsEventLabel(eventName: string): string {
  return eventName.replaceAll("_", " ");
}

function deriveBoardAutomationHealth(data: OperatorStatusResponse | undefined): {
  state: HealthState;
  reason: string | null;
} {
  if (!data) return { state: "unknown", reason: null };
  const scheduler = data.ops?.last_scheduler_scan;
  const cron = data.ops?.last_ops_trigger_scan;
  const schedulerExpected = data.runtime?.scheduler_expected !== false;
  const scheduledScanFresh = data.scheduler_freshness?.jobs?.scheduled_scan?.fresh;
  const schedulerFreshnessReason = data.scheduler_freshness?.reason;
  const scheduledScanStaleAfterSeconds = Number(
    data.scheduler_freshness?.jobs?.scheduled_scan?.stale_after_seconds || 20 * 60 * 60,
  );
  const schedulerAge = ageMinutes(scheduler?.finished_at || scheduler?.captured_at);
  const cronAge = ageMinutes(cron?.finished_at || cron?.captured_at);
  const schedulerErrors = Number(scheduler?.hard_errors || 0);
  const cronErrors = Number(cron?.error_count || 0);
  const recencyWarningMinutes = 12 * 60;
  const scheduledErrorWindowMinutes = Math.ceil(scheduledScanStaleAfterSeconds / 60);
  const hasRecentSchedulerErrors =
    schedulerErrors > 0 && schedulerAge !== null && schedulerAge <= scheduledErrorWindowMinutes;
  const hasRecentCronErrors = cronErrors > 0 && cronAge !== null && cronAge <= recencyWarningMinutes;
  const hasRecentSuccessfulScheduledRun =
    schedulerAge !== null && schedulerAge <= scheduledErrorWindowMinutes && schedulerErrors === 0;

  if (schedulerAge === null && cronAge === null) {
    return { state: "unknown", reason: "No daily board runs recorded yet." };
  }

  if (schedulerExpected) {
    // Daily-drop schedules are sparse by design; trust backend freshness windows.
    if (hasRecentSchedulerErrors || hasRecentCronErrors) {
      return {
        state: "warning",
        reason: hasRecentSchedulerErrors
          ? `Recent scheduled board drop reported ${schedulerErrors} error${schedulerErrors === 1 ? "" : "s"}.`
          : `Recent ops-trigger board refresh reported ${cronErrors} error${cronErrors === 1 ? "" : "s"}.`,
      };
    }
    if (scheduledScanFresh === false) {
      return {
        state: "warning",
        reason: `Scheduled board-drop freshness check is stale (>${Math.round(scheduledErrorWindowMinutes / 60)}h window).`,
      };
    }
    if (scheduledScanFresh === true) {
      return { state: "healthy", reason: null };
    }

    // External-scheduler split: API process may have no in-process heartbeats.
    if (schedulerFreshnessReason === "scheduler heartbeats unavailable") {
      if (hasRecentSuccessfulScheduledRun) {
        return { state: "healthy", reason: null };
      }
      return {
        state: "warning",
        reason: "No in-process scheduler heartbeat and no recent successful scheduled board drop found.",
      };
    }

    if (data.checks?.scheduler_freshness === false) {
      return { state: "warning", reason: "Board scheduler freshness check is failing." };
    }
    return { state: "healthy", reason: null };
  }

  // In external/ops-trigger mode, keep a softer recency warning threshold.
  if (hasRecentSchedulerErrors || hasRecentCronErrors) {
    return {
      state: "warning",
      reason: hasRecentCronErrors
        ? `Recent ops-trigger board refresh reported ${cronErrors} error${cronErrors === 1 ? "" : "s"}.`
        : `Recent scheduled board drop reported ${schedulerErrors} error${schedulerErrors === 1 ? "" : "s"}.`,
    };
  }
  if (cronAge === null || cronAge > recencyWarningMinutes) {
    return {
      state: "warning",
      reason: `No recent ops-trigger board refresh in the last ${Math.round(recencyWarningMinutes / 60)}h.`,
    };
  }
  return { state: "healthy", reason: null };
}

function deriveSettlementState(data: OperatorStatusResponse | undefined): HealthState {
  if (!data) return "unknown";
  const recentRuns = getRecentAutoSettleRuns(data);
  const settle = recentRuns[0] ?? data.ops?.last_auto_settle ?? null;
  const summary = data.ops?.last_auto_settle_summary;
  const skipTotals = summary?.skipped_totals ?? settle?.skipped_totals;
  const skipCount = countSkippedTotals(skipTotals);
  const actionableSkips = countActionableSkips(skipTotals);
  const manualPending = summary?.manual_settlement_pending ?? settle?.manual_settlement_pending ?? null;
  const manualPendingTotal = Number(manualPending?.total || 0);
  const manualPendingOldestAge = ageMinutes(manualPending?.oldest_commence_time);

  if (!settle) return "unknown";
  const settleAge = ageMinutes(settle.finished_at || settle.captured_at);
  if (settleAge !== null && settleAge > 1440) return "degraded";
  if (manualPendingTotal > 0 && manualPendingOldestAge !== null && manualPendingOldestAge > 1440) {
    return "warning";
  }
  // A no_match-only run is common when no pending bets map to completed events yet.
  if (actionableSkips > 0) return "warning";
  if (skipCount > 0 && Number(skipTotals?.no_match || 0) !== skipCount) return "warning";
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

function countSkippedTotals(skippedTotals?: Record<string, number> | null): number {
  return Object.values(skippedTotals || {}).reduce((acc, value) => acc + (typeof value === "number" ? value : 0), 0);
}

function countActionableSkips(skippedTotals?: Record<string, number> | null): number {
  return [
    Number(skippedTotals?.ambiguous_match || 0),
    Number(skippedTotals?.missing_scores || 0),
    Number(skippedTotals?.db_update_failed || 0),
    Number(skippedTotals?.missing_clv_team || 0),
    Number(skippedTotals?.missing_commence_time || 0),
  ].reduce((acc, value) => acc + value, 0);
}

function getBoardRunTimestamp(run?: Pick<BoardDropRunStatus, "finished_at" | "captured_at"> | null): string | null {
  return run?.finished_at || run?.captured_at || null;
}

function getLatestBoardRun(
  scheduler?: BoardDropRunStatus | null,
  cron?: BoardDropRunStatus | null,
): BoardDropRunStatus | null {
  const candidates = [scheduler, cron].filter(Boolean) as BoardDropRunStatus[];
  if (!candidates.length) return null;
  return [...candidates].sort((left, right) => {
    const leftTs = parseOpsTimestamp(getBoardRunTimestamp(left))?.getTime() || 0;
    const rightTs = parseOpsTimestamp(getBoardRunTimestamp(right))?.getTime() || 0;
    return rightTs - leftTs;
  })[0] ?? null;
}

function formatBoardWindowLabel(run?: BoardDropRunStatus | null): string {
  if (!run) return "Unknown";
  const scanWindow = (run as { scan_window?: { label?: string } | null }).scan_window?.label ?? null;
  return run.result?.scan_label || scanWindow || "Unknown";
}

function formatBoardMixLabel(result?: BoardDropResultSummary | null, fallbackTotalSides?: number | null): string {
  if (!result && fallbackTotalSides === null) return "Unknown";
  const parts: string[] = [];
  if (typeof result?.straight_sides === "number") parts.push(`${result.straight_sides} lines`);
  if (typeof result?.props_sides === "number") parts.push(`${result.props_sides} props`);
  if (typeof result?.featured_games_count === "number") parts.push(`${result.featured_games_count} featured`);
  if (!parts.length && typeof fallbackTotalSides === "number") {
    parts.push(`${fallbackTotalSides} total sides`);
  }
  return parts.join(" / ") || "Unknown";
}

function formatPropsFunnelLabel(result?: BoardDropResultSummary | null): string {
  if (!result) return "Unknown";
  const parts: string[] = [];
  if (typeof result.props_candidate_sides === "number") parts.push(`${result.props_candidate_sides} candidates`);
  if (typeof result.props_quality_gate_filtered === "number") parts.push(`${result.props_quality_gate_filtered} filtered`);
  if (typeof result.props_sides === "number") parts.push(`${result.props_sides} surfaced`);
  return parts.join(" / ") || "Unknown";
}

function formatBoardAlertLabel(run?: BoardDropRunStatus | null): string {
  if (!run) return "Unknown";
  const attempted = run.board_alert_attempted ?? run.board_alert?.attempted ?? false;
  const deliveryStatus = run.board_alert_delivery_status ?? run.board_alert?.delivery_status ?? null;
  const statusCode = run.board_alert_http_status ?? run.board_alert?.status_code ?? null;
  if (deliveryStatus) return statusCode ? `${deliveryStatus} (${statusCode})` : deliveryStatus;
  if (attempted) return "Attempted";
  return "Not attempted";
}

function formatAutoSettleSourceLabel(source?: string | null): string {
  const normalized = (source || "").trim().toLowerCase();
  if (normalized === "scheduler" || normalized === "auto_settle_scheduler") return "Scheduler";
  if (normalized === "cron" || normalized === "auto_settle_cron") return "Cron";
  if (normalized === "ops_trigger" || normalized === "auto_settle_ops_trigger") return "Ops trigger";
  if (normalized === "manual_cli") return "Manual CLI";
  return source || "Unknown";
}

function getRecentAutoSettleRuns(data: OperatorStatusResponse | undefined): AutoSettleRunStatus[] {
  const recent = Array.isArray(data?.ops?.recent_auto_settle_runs) ? [...data.ops.recent_auto_settle_runs] : [];
  const fallback = data?.ops?.last_auto_settle
    ? {
        ...data.ops.last_auto_settle,
        skipped_totals: data.ops.last_auto_settle_summary?.skipped_totals ?? data.ops.last_auto_settle.skipped_totals,
        sports: data.ops.last_auto_settle_summary?.sports ?? data.ops.last_auto_settle.sports,
        ml_settled: data.ops.last_auto_settle_summary?.ml_settled ?? data.ops.last_auto_settle.ml_settled,
        props_settled: data.ops.last_auto_settle_summary?.props_settled ?? data.ops.last_auto_settle.props_settled,
        parlays_settled: data.ops.last_auto_settle_summary?.parlays_settled ?? data.ops.last_auto_settle.parlays_settled,
        pickem_research_settled:
          data.ops.last_auto_settle_summary?.pickem_research_settled ?? data.ops.last_auto_settle.pickem_research_settled,
        manual_settlement_pending:
          data.ops.last_auto_settle_summary?.manual_settlement_pending ?? data.ops.last_auto_settle.manual_settlement_pending,
      }
    : null;
  const runs = fallback ? [fallback, ...recent] : recent;
  const deduped: AutoSettleRunStatus[] = [];
  const seen = new Set<string>();
  for (const run of runs) {
    const key = [
      run.run_id || "",
      run.source || "",
      run.finished_at || run.captured_at || "",
    ].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(run);
  }
  return deduped.sort((left, right) => {
    const leftTs = parseOpsTimestamp(left.finished_at || left.captured_at)?.getTime() || 0;
    const rightTs = parseOpsTimestamp(right.finished_at || right.captured_at)?.getTime() || 0;
    return rightTs - leftTs;
  });
}

function formatObservedRunTimes(runs: AutoSettleRunStatus[]): string {
  const labels = new Map<number, string>();
  for (const run of runs) {
    const timestamp = run.finished_at || run.captured_at;
    const parsed = parseOpsTimestamp(timestamp);
    if (!parsed) continue;
    const minuteOfDay = parsed.getHours() * 60 + parsed.getMinutes();
    if (!labels.has(minuteOfDay)) {
      labels.set(minuteOfDay, formatCompactTime(timestamp));
    }
  }
  return Array.from(labels.entries())
    .sort((left, right) => left[0] - right[0])
    .map(([, label]) => label)
    .join(" / ") || "Unknown";
}

function formatAutoSettleBreakdown(
  summary?: AutoSettleSummary | null,
  fallbackRun?: AutoSettleRunStatus | null,
): string {
  const total = summary?.total_settled ?? fallbackRun?.settled;
  const ml = summary?.ml_settled ?? fallbackRun?.ml_settled;
  const props = summary?.props_settled ?? fallbackRun?.props_settled;
  const parlays = summary?.parlays_settled ?? fallbackRun?.parlays_settled;
  const pickem = summary?.pickem_research_settled ?? fallbackRun?.pickem_research_settled;
  const parts: string[] = [];
  if (typeof total === "number") parts.push(`${total} total`);
  if (typeof ml === "number") parts.push(`ML ${ml}`);
  if (typeof props === "number") parts.push(`Props ${props}`);
  if (typeof parlays === "number") parts.push(`Parlays ${parlays}`);
  if (typeof pickem === "number") parts.push(`Research ${pickem}`);
  return parts.join(" / ") || "Unknown";
}

function formatSkippedSignal(skippedTotals?: Record<string, number> | null): string {
  if (!skippedTotals) return "Unknown";
  const total = countSkippedTotals(skippedTotals);
  if (total === 0) return "No skips recorded";
  const actionable = countActionableSkips(skippedTotals);
  if (actionable === 0) return `${total} total / passive`;
  return `${total} total / ${actionable} actionable`;
}

function formatManualSettlementPending(
  pending?: AutoSettleSummary["manual_settlement_pending"] | AutoSettleRunStatus["manual_settlement_pending"] | null,
): string {
  if (!pending) return "None recorded";
  const total = Number(pending.total || 0);
  if (total === 0) return "No manual backlog";
  const parts: string[] = [];
  if (Number(pending.prop_bets || 0) > 0) parts.push(`props ${pending.prop_bets}`);
  if (Number(pending.parlays || 0) > 0) parts.push(`parlays ${pending.parlays}`);
  if (Number(pending.pickem_research || 0) > 0) parts.push(`research ${pending.pickem_research}`);
  return `${total} pending${parts.length ? ` / ${parts.join(" / ")}` : ""}`;
}

function formatManualSettlementBySport(
  pending?: AutoSettleSummary["manual_settlement_pending"] | AutoSettleRunStatus["manual_settlement_pending"] | null,
): string[] {
  const bySport = pending?.by_sport;
  if (!bySport) return [];
  return Object.entries(bySport)
    .map(([sport, counts]) => {
      const parts: string[] = [];
      if (Number(counts?.prop_bets || 0) > 0) parts.push(`props ${counts?.prop_bets}`);
      if (Number(counts?.parlays || 0) > 0) parts.push(`parlays ${counts?.parlays}`);
      if (Number(counts?.pickem_research || 0) > 0) parts.push(`research ${counts?.pickem_research}`);
      return `${formatSportLabel(sport)}: ${parts.join(" / ") || scalarOrUnknown(counts?.total)}`;
    })
    .sort((left, right) => left.localeCompare(right));
}

function formatSourceLabel(source?: string | null): string {
  const normalized = source?.trim().toLowerCase();
  if (normalized === "manual_scan") return "Manual";
  if (normalized === "scheduled_scan" || normalized === "scheduled_board_drop") return "Scheduler";
  if (normalized === "ops_trigger_scan" || normalized === "ops_trigger_board_drop" || normalized === "cron_scan") {
    return "Ops trigger";
  }
  return source || "Unknown";
}

function formatSurfaceLabel(surface?: string | null): string {
  if (surface === "board_drop") return "Daily board";
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
  surface: "straight_bets" | "player_props" | "board_drop";
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
      source: scheduler?.board_drop ? "scheduled_board_drop" : "scheduled_scan",
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
      source: cron?.board_drop ? "ops_trigger_board_drop" : "ops_trigger_scan",
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
      source: scheduler?.board_drop ? "scheduled_board_drop" : "scheduled_scan",
      surface: scheduler?.board_drop ? "board_drop" : "straight_bets",
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
      source: cron?.board_drop ? "ops_trigger_board_drop" : "ops_trigger_scan",
      surface: cron?.board_drop ? "board_drop" : "straight_bets",
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

export function OpsDashboard() {
  const query = useOperatorStatus();
  const analyticsQuery = useAnalyticsSummary(7);
  const analyticsUserQuery = useAnalyticsUserDrilldown(7, 25, 12);
  const [isRefreshingBoard, setIsRefreshingBoard] = useState(false);
  const [isTriggeringAutoSettle, setIsTriggeringAutoSettle] = useState(false);
  const [showAllOddsScans, setShowAllOddsScans] = useState(false);
  const [showAllOddsCalls, setShowAllOddsCalls] = useState(false);
  const queryErrorMessage = query.error instanceof Error ? query.error.message : null;
  const analyticsErrorMessage = analyticsQuery.error instanceof Error ? analyticsQuery.error.message : null;
  const analyticsUsersErrorMessage = analyticsUserQuery.error instanceof Error ? analyticsUserQuery.error.message : null;
  const isAnyFetching = query.isFetching || analyticsQuery.isFetching || analyticsUserQuery.isFetching;

  const automationHealth = useMemo(() => deriveBoardAutomationHealth(query.data), [query.data]);
  const automationState = automationHealth.state;
  const automationWarningReason = automationHealth.reason;
  const settlementState = useMemo(() => deriveSettlementState(query.data), [query.data]);
  const oddsApiState = useMemo(() => deriveOddsApiState(query.data), [query.data]);

  const schedulerScan = query.data?.ops?.last_scheduler_scan;
  const cronScan = query.data?.ops?.last_ops_trigger_scan;
  const manualScan = query.data?.ops?.last_manual_scan;
  const autoSettle = query.data?.ops?.last_auto_settle;
  const settleSummary = query.data?.ops?.last_auto_settle_summary;
  const recentAutoSettleRuns = useMemo(() => getRecentAutoSettleRuns(query.data), [query.data]);
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
  const primaryBoardMode =
    query.data?.runtime?.scheduler_expected === false ? "Ops trigger refreshes" : "Scheduler automation";
  const latestBoardRun = useMemo(() => getLatestBoardRun(schedulerScan, cronScan), [schedulerScan, cronScan]);
  const latestBoardResult = latestBoardRun?.result ?? null;
  const noBoardRunsYet = !schedulerScan && !cronScan;
  const noSettlementRunsYet = recentAutoSettleRuns.length === 0 && !settleSummary;

  const latestSkippedTotals = settleSummary?.skipped_totals ?? recentAutoSettleRuns[0]?.skipped_totals ?? null;
  const skippedEntries = Object.entries(latestSkippedTotals || {});
  const latestAutoSettleRun = recentAutoSettleRuns[0] ?? autoSettle ?? null;
  const latestManualSettlementPending =
    settleSummary?.manual_settlement_pending ?? latestAutoSettleRun?.manual_settlement_pending ?? null;
  const latestManualSettlementBySport = formatManualSettlementBySport(latestManualSettlementPending);
  const analytics = analyticsQuery.data;
  const analyticsUsers = analyticsUserQuery.data;

  async function refreshAllPanels() {
    await Promise.all([
      query.refetch(),
      analyticsQuery.refetch(),
      analyticsUserQuery.refetch(),
    ]);
  }

  async function handleRefreshBoard() {
    try {
      setIsRefreshingBoard(true);
      const result = await adminRefreshMarkets();

      const refreshAccepted = Boolean(result.accepted || result.pending);
      if (refreshAccepted) {
        toast.success("Daily drop refresh started", {
          description: `Queued board refresh run ${result.run_id}. It will continue in the background.`,
        });
        await refreshAllPanels();
        return;
      }

      toast.success("Daily drop refresh started", {
        description: result.board_drop
          ? `Completed board refresh for ${result.total_sides ?? 0} surfaced picks.`
          : `Completed refresh run ${result.run_id}.`,
      });
      await refreshAllPanels();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not refresh daily drop.";
      toast.error("Daily drop refresh failed", { description: message });
    } finally {
      setIsRefreshingBoard(false);
    }
  }

  async function handleTriggerAutoSettle() {
    try {
      setIsTriggeringAutoSettle(true);
      const result = await adminTriggerAutoSettle();
      toast.success("Auto-settle run started", {
        description:
          result.settled > 0
            ? `Settled ${result.settled} bet${result.settled === 1 ? "" : "s"}.`
            : `Run ${result.run_id} completed with no bets needing grading.`,
      });
      await refreshAllPanels();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not run auto-settle.";
      toast.error("Auto-settle failed", { description: message });
    } finally {
      setIsTriggeringAutoSettle(false);
    }
  }

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-4xl px-4 py-6 space-y-4 pb-20">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Operator Status</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Focused health view for daily board automation, settlement cadence, odds usage, and beta-decision systems.
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Last snapshot: {formatTime(query.data?.timestamp)}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/ops/research">Research diagnostics</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/ops/alt-pitcher-k">Alt Pitcher K Lookup</Link>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleRefreshBoard}
              disabled={isAnyFetching || isRefreshingBoard || isTriggeringAutoSettle}
            >
              <RefreshCcw className={`h-4 w-4 mr-1.5 ${isRefreshingBoard ? "animate-spin" : ""}`} />
              Refresh Daily Drop
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleTriggerAutoSettle}
              disabled={isAnyFetching || isTriggeringAutoSettle || isRefreshingBoard}
            >
              <RefreshCcw className={`h-4 w-4 mr-1.5 ${isTriggeringAutoSettle ? "animate-spin" : ""}`} />
              Run Auto-Settle
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void refreshAllPanels();
              }}
              disabled={isAnyFetching}
            >
              <RefreshCcw className={`h-4 w-4 mr-1.5 ${isAnyFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
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
                <h2 className="font-semibold">Daily Board Automation</h2>
                <StatusBadge state={automationState} />
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <Row label="Primary mode" value={primaryBoardMode} />
              <Row label="Last scheduled board drop" value={formatTime(getBoardRunTimestamp(schedulerScan))} />
              <Row label="Last ops board refresh" value={formatTime(getBoardRunTimestamp(cronScan))} />
              <Row label="Last manual market scan" value={formatTime(manualScan?.captured_at)} />
              <Row label="Latest board window" value={formatBoardWindowLabel(latestBoardRun)} />
              <Row
                label="Latest board mix"
                value={formatBoardMixLabel(latestBoardResult, latestBoardRun?.total_sides ?? null)}
              />
              <Row label="Latest props funnel" value={formatPropsFunnelLabel(latestBoardResult)} />
              <Row label="Discord publish" value={formatBoardAlertLabel(latestBoardRun)} />
              <Row
                label="Recent run errors"
                value={String(Number(schedulerScan?.hard_errors || 0) + Number(cronScan?.error_count || 0))}
              />

              {automationState === "warning" && automationWarningReason && (
                <p className="text-xs text-[#5C4D2E] bg-[#C4A35A]/10 border border-[#C4A35A]/30 rounded px-2 py-1">
                  Why warning: {automationWarningReason}
                </p>
              )}

              {noBoardRunsYet && (
                <p className="text-xs text-muted-foreground pt-1">
                  No scheduled or ops-triggered board drops are recorded yet. This is expected in local development until a run is triggered.
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
              <Row
                label="Latest auto-settle run"
                value={formatTime(latestAutoSettleRun?.finished_at || latestAutoSettleRun?.captured_at)}
              />
              <Row label="Latest source" value={formatAutoSettleSourceLabel(latestAutoSettleRun?.source)} />
              <Row label="Observed run times" value={formatObservedRunTimes(recentAutoSettleRuns)} />
              <Row
                label="Latest breakdown"
                value={formatAutoSettleBreakdown(settleSummary, latestAutoSettleRun)}
              />
              <Row label="Latest skip signal" value={formatSkippedSignal(latestSkippedTotals)} />
              <Row label="Manual pending" value={formatManualSettlementPending(latestManualSettlementPending)} />
              <Row
                label="Manual oldest"
                value={formatTime(latestManualSettlementPending?.oldest_commence_time)}
              />
              <Row label="Summary captured" value={formatTime(settleSummary?.captured_at)} />
              {recentAutoSettleRuns.length > 0 && (
                <div className="pt-1">
                  <p className="text-xs text-muted-foreground mb-1">Recent runs</p>
                  <div className="space-y-1.5">
                    {recentAutoSettleRuns.slice(0, 4).map((run) => (
                      <div key={run.run_id || `${run.source}-${run.finished_at || run.captured_at || "unknown"}`} className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                        <div className="flex items-center justify-between gap-3 text-xs">
                          <span className="font-medium">{formatAutoSettleSourceLabel(run.source)}</span>
                          <span className="font-mono text-[11px] text-right">
                            {formatTimeWithRelative(run.finished_at || run.captured_at, "Unknown")}
                          </span>
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
                          <span>Settled</span>
                          <span className="font-mono text-foreground">{scalarOrUnknown(run.settled)}</span>
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
                          <span>Skip signal</span>
                          <span className="font-mono text-foreground">{formatSkippedSignal(run.skipped_totals)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
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
              {latestManualSettlementBySport.length > 0 ? (
                <div className="pt-1">
                  <p className="text-xs text-muted-foreground mb-1">Manual backlog by sport</p>
                  <div className="flex flex-wrap gap-1.5">
                    {latestManualSettlementBySport.map((label) => (
                      <span key={label} className="rounded bg-muted px-2 py-1 text-[11px] font-mono">
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {noSettlementRunsYet && (
                <p className="text-xs text-muted-foreground">
                  No auto-settlement runs are recorded yet. In local mode this is normal before the first run.
                </p>
              )}
            </CardContent>
          </Card>

          <OddsApiActivityCard data={query.data} />

          {false && (
          <Card className="md:col-span-2">
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
          )}

          <Card className="md:col-span-2">
            <CardHeader className="pb-3">
              <h2 className="font-semibold">Beta Analytics Summary (7d)</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                Aggregate health snapshot for product decisions: counts, funnel rates, reliability, and return usage.
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {analyticsQuery.isError ? (
                <p className="text-sm text-muted-foreground">
                  Analytics summary unavailable{analyticsErrorMessage ? `: ${analyticsErrorMessage}` : "."}
                </p>
              ) : (
                <>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Aggregate Counts</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Events</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analytics?.totals?.events)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Sessions</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analytics?.totals?.sessions)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Users</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analytics?.totals?.users)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Bet Logged</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analytics?.event_counts?.bet_logged)}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-2 text-xs">
                    <div className="rounded border border-border/60 bg-muted/15 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Funnel Rates</p>
                      <p>
                        Board -&gt; Log-open conversion: <span className="font-semibold">{formatPercentValue(analytics?.funnel?.board_to_log_open_rate_pct)}</span>
                      </p>
                      <p className="mt-1">
                        Log-open -&gt; Bet-logged conversion: <span className="font-semibold">{formatPercentValue(analytics?.funnel?.log_open_to_bet_logged_rate_pct)}</span>
                      </p>
                    </div>
                    <div className="rounded border border-border/60 bg-muted/15 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Reliability Signals</p>
                      <p>
                        Bet log failed rate: <span className="font-semibold">{formatPercentValue(analytics?.reliability?.bet_log_failed_rate_pct)}</span>
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        scanner_failed={scalarOrUnknown(analytics?.reliability?.scanner_failed)} | rate_limit_hit={scalarOrUnknown(analytics?.reliability?.rate_limit_hit)} | stale_data_banner_seen={scalarOrUnknown(analytics?.reliability?.stale_data_banner_seen)}
                      </p>
                    </div>
                    <div className="rounded border border-border/60 bg-muted/15 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Return Usage</p>
                      <p>
                        Returning users: <span className="font-semibold">{scalarOrUnknown(analytics?.return_usage?.returning_users)}</span>
                      </p>
                      <p className="mt-1">
                        Returning user rate: <span className="font-semibold">{formatPercentValue(analytics?.return_usage?.returning_user_rate_pct)}</span>
                      </p>
                      <p className="mt-1">
                        Avg sessions per known user: <span className="font-semibold">{scalarOrUnknown(analytics?.return_usage?.avg_sessions_per_known_user)}</span>
                      </p>
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <p className="text-xs text-muted-foreground">Key events</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="rounded bg-muted px-2 py-1 text-[11px] font-mono">signup_completed: {scalarOrUnknown(analytics?.event_counts?.signup_completed)}</span>
                      <span className="rounded bg-muted px-2 py-1 text-[11px] font-mono">tutorial_started: {scalarOrUnknown(analytics?.event_counts?.tutorial_started)}</span>
                      <span className="rounded bg-muted px-2 py-1 text-[11px] font-mono">board_viewed: {scalarOrUnknown(analytics?.event_counts?.board_viewed)}</span>
                      <span className="rounded bg-muted px-2 py-1 text-[11px] font-mono">log_bet_opened: {scalarOrUnknown(analytics?.event_counts?.log_bet_opened)}</span>
                      <span className="rounded bg-muted px-2 py-1 text-[11px] font-mono">feedback_submitted: {scalarOrUnknown(analytics?.event_counts?.feedback_submitted)}</span>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader className="pb-3">
              <h2 className="font-semibold">User Drilldown (7d)</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                Support view for beta follow-up: timeline, latest session, tutorial status, board/log/bet milestones, failures, and last seen.
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {analyticsUserQuery.isError ? (
                <p className="text-sm text-muted-foreground">
                  User drilldown unavailable{analyticsUsersErrorMessage ? `: ${analyticsUsersErrorMessage}` : "."}
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Tracked users</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analyticsUsers?.totals?.tracked_users)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Need follow-up</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analyticsUsers?.totals?.needs_follow_up)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Stuck users</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analyticsUsers?.totals?.stuck_users)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Active 24h</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(analyticsUsers?.totals?.active_last_24h)}</p>
                    </div>
                  </div>

                  {!analyticsUsers?.users?.length ? (
                    <p className="text-xs text-muted-foreground">No user activity captured in this window yet.</p>
                  ) : (
                    <div className="space-y-2">
                      <div className="hidden md:grid md:grid-cols-[1.5fr_1.2fr_1fr_1fr_0.7fr_0.8fr_1fr_1fr] gap-2 rounded border border-border/70 bg-muted/20 px-2.5 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                        <span>User</span>
                        <span>Last seen</span>
                        <span>Tutorial</span>
                        <span>First bet</span>
                        <span>Sessions</span>
                        <span>Bets</span>
                        <span>Last error</span>
                        <span>Follow-up</span>
                      </div>

                      {analyticsUsers.users.map((user) => (
                        <details
                          key={user.actor_key}
                          className="rounded border border-border/70 bg-muted/10 px-2.5 py-2 text-xs [&_summary::-webkit-details-marker]:hidden"
                        >
                          <summary className="cursor-pointer list-none">
                            <div className="md:grid md:grid-cols-[1.5fr_1.2fr_1fr_1fr_0.7fr_0.8fr_1fr_1fr] md:gap-2 space-y-1 md:space-y-0">
                              <div>
                                <p className="font-mono text-[11px] text-foreground">{user.user_email || user.user_label}</p>
                                {user.user_id ? (
                                  user.user_email ? <p className="text-[11px] text-muted-foreground">{user.user_id}</p> : null
                                ) : (
                                  <p className="text-[11px] text-muted-foreground">anonymous session</p>
                                )}
                              </div>
                              <p className="text-[11px] text-muted-foreground">{formatIsoWithRelative(user.last_seen_at)}</p>
                              <p className="text-[11px]">{formatTutorialStatusLabel(user.tutorial_status)}</p>
                              <p className="text-[11px] text-muted-foreground">{user.first_bet_logged_at ? formatRelativeTime(user.first_bet_logged_at) : "-"}</p>
                              <p className="text-[11px] font-mono">{user.total_sessions}</p>
                              <p className="text-[11px] font-mono">{user.total_bets_logged}</p>
                              <p className="text-[11px] text-muted-foreground">
                                {user.last_error_event ? `${formatAnalyticsEventLabel(user.last_error_event)} (${formatRelativeTime(user.last_error_at)})` : "-"}
                              </p>
                              <div>
                                <span className={`inline-flex rounded border px-1.5 py-0.5 text-[11px] ${followUpTagClass(user.follow_up_tag)}`}>
                                  {formatFollowUpTagLabel(user.follow_up_tag)}
                                </span>
                              </div>
                            </div>
                          </summary>

                          <div className="mt-2 border-t border-border/60 pt-2 space-y-1.5">
                            <p className="text-[11px] text-muted-foreground">Follow-up reason: {user.follow_up_reason}</p>
                            <p className="text-[11px] text-muted-foreground">
                              Latest session: <span className="font-mono">{user.latest_session.session_id || "-"}</span> • events: {user.latest_session.event_count}
                            </p>
                            <p className="text-[11px] text-muted-foreground">
                              Milestones: tutorial_started={formatRelativeTime(user.tutorial_started_at)} | tutorial_completed={formatRelativeTime(user.tutorial_completed_at)} | board_viewed={formatRelativeTime(user.first_board_view_at)} | log_open={formatRelativeTime(user.first_log_open_at)} | first_bet={formatRelativeTime(user.first_bet_logged_at)} | failures={user.failures_hit}
                            </p>

                            <div className="space-y-1">
                              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Activity timeline</p>
                              {user.timeline.length === 0 ? (
                                <p className="text-[11px] text-muted-foreground">No timeline events in this window.</p>
                              ) : (
                                user.timeline.map((event, idx) => (
                                  <div key={`${user.actor_key}-${event.captured_at}-${event.event_name}-${idx}`} className="rounded border border-border/60 bg-background/60 px-2 py-1 text-[11px]">
                                    <span className="font-mono">{formatCompactTime(event.captured_at)}</span>
                                    {" • "}
                                    <span>{formatAnalyticsEventLabel(event.event_name)}</span>
                                    {event.session_id ? <span>{` • session ${event.session_id}`}</span> : null}
                                    {event.route ? <span>{` • ${event.route}`}</span> : null}
                                    {event.is_failure ? <span className="text-[#8B3D20]"> • failure</span> : null}
                                  </div>
                                ))
                              )}
                            </div>
                          </div>
                        </details>
                      ))}
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
