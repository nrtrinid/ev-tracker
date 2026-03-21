"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCcw, XCircle } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useOperatorStatus } from "@/lib/hooks";
import type { OperatorStatusResponse } from "@/lib/types";

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
  if (!backendSummary && fallback.recentCalls.length === 0) return "unknown";
  if (errorsLastHour >= 3) return "degraded";
  if (errorsLastHour > 0) return "warning";
  return "healthy";
}

type OddsActivitySummary = {
  calls_last_hour?: number;
  errors_last_hour?: number;
  last_success_at?: string | null;
  last_error_at?: string | null;
};

type OddsActivityCall = {
  timestamp?: string | null;
  source?: string | null;
  endpoint?: string | null;
  sport?: string | null;
  cache_hit?: boolean;
  outbound_call_made?: boolean;
  status_code?: number | null;
  duration_ms?: number | null;
  api_requests_remaining?: string | number | null;
  error_type?: string | null;
  error_message?: string | null;
};

function buildFallbackOddsActivity(data: OperatorStatusResponse | undefined): {
  summary: OddsActivitySummary;
  recentCalls: OddsActivityCall[];
} {
  const scheduler = data?.ops?.last_scheduler_scan;
  const cron = data?.ops?.last_ops_trigger_scan;
  const manual = data?.ops?.last_manual_scan;

  const candidates: OddsActivityCall[] = [
    {
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
      timestamp: cron?.finished_at || cron?.captured_at,
      source: "cron_scan",
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

  return {
    summary: {
      calls_last_hour: callsLastHour,
      errors_last_hour: errorsLastHour,
      last_success_at: lastSuccessAt,
      last_error_at: lastErrorAt,
    },
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
  const [showAllOddsCalls, setShowAllOddsCalls] = useState(false);
  const queryErrorMessage = query.error instanceof Error ? query.error.message : null;

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
  const oddsRecentCalls = Array.isArray(oddsApiActivity?.recent_calls) && oddsApiActivity.recent_calls.length > 0
    ? oddsApiActivity.recent_calls
    : oddsFallback.recentCalls;
  const oddsDefaultVisible = 8;
  const oddsVisibleCalls = showAllOddsCalls ? oddsRecentCalls : oddsRecentCalls.slice(0, oddsDefaultVisible);
  const schedulerExpected = query.data?.runtime?.scheduler_expected;
  const noScanRunsYet = !schedulerScan && !cronScan && !manualScan;
  const noSettlementRunsYet = !autoSettle && !settleSummary;

  const skippedTotals = settleSummary?.skipped_totals || {};
  const skippedEntries = Object.entries(skippedTotals);
  const settleSource = normalizeSettleSource(autoSettle?.source);
  const fallbackAvailable = yesNoUnknown(query.data?.runtime?.cron_token_configured);

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
            onClick={() => query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCcw className={`h-4 w-4 mr-1.5 ${query.isFetching ? "animate-spin" : ""}`} />
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
                <p className="text-xs text-muted-foreground">Recent calls</p>
                {oddsVisibleCalls.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No recent Odds API activity recorded yet.</p>
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

              {oddsRecentCalls.length > oddsDefaultVisible && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="px-0 h-auto text-xs"
                  onClick={() => setShowAllOddsCalls((prev) => !prev)}
                >
                  {showAllOddsCalls ? "Show less" : `Show more (${oddsRecentCalls.length - oddsDefaultVisible} more)`}
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
        </div>
      </div>
    </main>
  );
}
