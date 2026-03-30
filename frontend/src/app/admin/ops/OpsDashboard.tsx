"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCcw, Scale, ScanLine, XCircle } from "lucide-react";
import { toast } from "sonner";

import { adminRefreshMarkets, adminTriggerAutoSettle } from "@/lib/api";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useOperatorStatus, useResearchOpportunitySummary } from "@/lib/hooks";
import type {
  OperatorStatusResponse,
  ResearchOpportunityBreakdownItem,
  ResearchOpportunityRecentRow,
} from "@/lib/types";
import { OddsApiActivityCard } from "./OddsApiActivityCard";

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

function getTimeZoneOffsetMs(date: Date, timeZone: string): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const parts = dtf.formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value;
  const year = Number(get("year"));
  const month = Number(get("month"));
  const day = Number(get("day"));
  const hour = Number(get("hour"));
  const minute = Number(get("minute"));
  const second = Number(get("second"));
  return Date.UTC(year, month - 1, day, hour, minute, second) - date.getTime();
}

function zonedTimeToUtcMs(
  year: number,
  month1: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string,
): number {
  const utcGuess = Date.UTC(year, month1 - 1, day, hour, minute, 0);
  return utcGuess - getTimeZoneOffsetMs(new Date(utcGuess), timeZone);
}

function formatLocalScanWindow(scanWindow?: {
  label?: string;
  anchor_timezone?: string;
  anchor_time_mst?: string;
} | null): string {
  if (!scanWindow?.label) return "Unknown";
  const anchor = scanWindow.anchor_time_mst;
  if (!anchor) return scanWindow.label;
  const [hRaw, mRaw] = anchor.split(":");
  const h = Number(hRaw);
  const m = Number(mRaw);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return scanWindow.label;
  const now = new Date();
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Phoenix",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = fmt.formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value;
  const y = Number(get("year"));
  const mo = Number(get("month"));
  const d = Number(get("day"));
  const utcMs = zonedTimeToUtcMs(y, mo, d, h, m, "America/Phoenix");
  const local = new Date(utcMs).toLocaleString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${scanWindow.label} • ${local} local`;
}

function ageMinutes(value?: string | null): number | null {
  const parsed = parseOpsTimestamp(value);
  if (!parsed) return null;
  const ts = parsed.getTime();
  return Math.max(0, Math.round((Date.now() - ts) / 60000));
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

function formatMaybePercentDash(value: number | null | undefined, digits: number = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function formatGatedPercentValue(value: number | null | undefined, validCloseCount: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    if (validCloseCount === 0) return "No valid closes";
    return "Need more valid closes";
  }
  return formatPercentValue(value);
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
              {row.key}: {row.captured_count} cap / {row.valid_close_count} valid | BC {formatMaybePercentDash(row.beat_close_pct)} | CLV{" "}
              {formatMaybePercentDash(row.avg_clv_percent)}
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
  const odds = row.reference_odds_at_close === null || row.reference_odds_at_close === undefined ? null : formatAmericanOdds(row.reference_odds_at_close);
  if (row.close_status === "pending") return "Pending";
  if (row.close_status === "invalid") return odds ? `Invalid close (${odds})` : "Invalid close";
  return odds ? `Valid close (${odds})` : "Valid close";
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
                    {row.close_status === "valid" && (
                      <>
                        {" • "}
                        CLV {formatPercentValue(row.clv_ev_percent)}
                      </>
                    )}
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
  const [modelVersion, setModelVersion] = useState<"current" | "legacy" | "all">("current");
  const [captureClass, setCaptureClass] = useState<"live" | "experiment" | "all">("live");
  const [cohortMode, setCohortMode] = useState<"latest" | "trailing_7">("latest");
  const [showAdvancedBreakdowns, setShowAdvancedBreakdowns] = useState(false);
  const [isRefreshingMarkets, setIsRefreshingMarkets] = useState(false);
  const [isRunningAutoSettle, setIsRunningAutoSettle] = useState(false);
  const researchQuery = useResearchOpportunitySummary({
    model_version: modelVersion,
    capture_class: captureClass,
    cohort_mode: cohortMode,
  });
  const queryErrorMessage = query.error instanceof Error ? query.error.message : null;
  const researchErrorMessage = researchQuery.error instanceof Error ? researchQuery.error.message : null;

  const automationState = useMemo(() => deriveScannerState(query.data), [query.data]);
  const settlementState = useMemo(() => deriveSettlementState(query.data), [query.data]);
  const readinessState = useMemo(() => deriveReadinessState(query.data), [query.data]);

  const schedulerScan = query.data?.ops?.last_scheduler_scan;
  const cronScan = query.data?.ops?.last_ops_trigger_scan;
  const manualScan = query.data?.ops?.last_manual_scan;
  const autoSettle = query.data?.ops?.last_auto_settle;
  const readinessFailure = query.data?.ops?.last_readiness_failure;
  const settleSummary = query.data?.ops?.last_auto_settle_summary;
  const schedulerExpected = query.data?.runtime?.scheduler_expected;
  const noScanRunsYet = !schedulerScan && !cronScan && !manualScan;
  const noSettlementRunsYet = !autoSettle && !settleSummary;

  const skippedTotals = settleSummary?.skipped_totals || {};
  const skippedEntries = Object.entries(skippedTotals);
  const settleSource = normalizeSettleSource(autoSettle?.source);
  const fallbackAvailable = yesNoUnknown(query.data?.runtime?.cron_token_configured);
  const research = researchQuery.data;
  const recentResearch = research?.recent_opportunities ?? [];
  const recentStraightResearch = recentResearch.filter((row) => row.surface !== "player_props");
  const recentPropResearch = recentResearch.filter((row) => row.surface === "player_props");

  const runFullMarketScan = async () => {
    if (isRefreshingMarkets) return;
    setIsRefreshingMarkets(true);
    try {
      const out = await adminRefreshMarkets();
      const parts = out.results.map(
        (r) =>
          `${r.surface.replace(/_/g, " ")}: ${r.total_sides} sides, ${r.events_fetched} events`,
      );
      toast("Markets refreshed", {
        description: parts.join(" · "),
      });
      await Promise.all([query.refetch(), researchQuery.refetch()]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Refresh failed";
      toast.error("Full market scan failed", { description: msg });
    } finally {
      setIsRefreshingMarkets(false);
    }
  };

  const runAutoSettle = async () => {
    if (isRunningAutoSettle) return;
    setIsRunningAutoSettle(true);
    try {
      const out = await adminTriggerAutoSettle();
      toast("Auto-settle finished", {
        description: `Graded ${out.settled} bet(s) · ${Math.round(out.duration_ms)} ms`,
      });
      await query.refetch();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Auto-settle failed";
      toast.error("Auto-settle failed", { description: msg });
    } finally {
      setIsRunningAutoSettle(false);
    }
  };

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-4xl px-4 py-6 space-y-4 pb-20">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold">Operator Status</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Internal runtime and automation visibility for scanner and settlement health.
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Last snapshot: {formatTime(query.data?.timestamp)}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-stretch gap-2 sm:justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full sm:w-auto"
              onClick={() => {
                query.refetch();
                researchQuery.refetch();
              }}
              disabled={query.isFetching || researchQuery.isFetching || isRefreshingMarkets || isRunningAutoSettle}
            >
              <RefreshCcw className={`h-4 w-4 mr-1.5 ${(query.isFetching || researchQuery.isFetching) ? "animate-spin" : ""}`} />
              Refresh status
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Card className="border-primary/30 bg-primary/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg">Full market scan</CardTitle>
              <CardDescription>
                Re-fetch all sports for straight bets and player props (same work as the scanner &quot;scan&quot;, without the per-user rate limit).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                type="button"
                variant="default"
                size="touch"
                className="w-full sm:w-auto"
                onClick={() => void runFullMarketScan()}
                disabled={isRefreshingMarkets || isRunningAutoSettle}
              >
                <ScanLine className={`h-5 w-5 mr-2 ${isRefreshingMarkets ? "animate-pulse" : ""}`} />
                {isRefreshingMarkets ? "Scanning…" : "Run full scan"}
              </Button>
            </CardContent>
          </Card>

          <Card className="border-border bg-muted/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg">Auto-settle</CardTitle>
              <CardDescription>
                Run the pending-bet grader (same as cron/ops trigger). Use when you want results updated without waiting for the scheduler.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                type="button"
                variant="secondary"
                size="touch"
                className="w-full sm:w-auto"
                onClick={() => void runAutoSettle()}
                disabled={isRunningAutoSettle || isRefreshingMarkets}
              >
                <Scale className={`h-5 w-5 mr-2 ${isRunningAutoSettle ? "animate-pulse" : ""}`} />
                {isRunningAutoSettle ? "Settling…" : "Run auto-settle"}
              </Button>
            </CardContent>
          </Card>
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
              <Row
                label={schedulerScan?.board_drop ? "Last daily board drop" : "Last scheduler scan"}
                value={formatTime(schedulerScan?.finished_at || schedulerScan?.captured_at)}
              />
              <Row label="Last scan window" value={formatLocalScanWindow(schedulerScan?.scan_window)} />
              <Row label="Scheduler freshness" value={schedulerFreshnessLabel(query.data)} />
              <Row label="Props events scanned" value={scalarOrUnknown(schedulerScan?.props_events_scanned)} />
              <Row label="Featured games included" value={scalarOrUnknown(schedulerScan?.featured_games_count)} />
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

          <OddsApiActivityCard data={query.data} />

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
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-xs text-muted-foreground">Tracker view</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-muted-foreground">Model</span>
                        <select
                          className="rounded-md border border-border/70 bg-background px-2 py-1 text-[11px]"
                          value={modelVersion}
                          onChange={(e) => setModelVersion(e.target.value as "current" | "legacy" | "all")}
                        >
                          <option value="current">Current Model</option>
                          <option value="legacy">Legacy</option>
                          <option value="all">All</option>
                        </select>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-muted-foreground">Capture</span>
                        <select
                          className="rounded-md border border-border/70 bg-background px-2 py-1 text-[11px]"
                          value={captureClass}
                          onChange={(e) => setCaptureClass(e.target.value as "live" | "experiment" | "all")}
                        >
                          <option value="live">Live Captures</option>
                          <option value="experiment">Experiment / QA</option>
                          <option value="all">All</option>
                        </select>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-muted-foreground">Cohort</span>
                        <select
                          className="rounded-md border border-border/70 bg-background px-2 py-1 text-[11px]"
                          value={cohortMode}
                          onChange={(e) => setCohortMode(e.target.value as "latest" | "trailing_7")}
                        >
                          <option value="latest">Latest Drop</option>
                          <option value="trailing_7">Trailing 7 Drops</option>
                        </select>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Captured</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.captured_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Pending Close</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.pending_close_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Valid Close</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.valid_close_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Invalid Close</p>
                      <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(research?.invalid_close_count)}</p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Beat Close</p>
                      <p className="text-sm font-semibold mt-0.5">
                        {formatGatedPercentValue(research?.beat_close_pct, research?.valid_close_count ?? 0)}
                      </p>
                    </div>
                    <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Avg CLV</p>
                      <p className="text-sm font-semibold mt-0.5">
                        {formatGatedPercentValue(research?.avg_clv_percent, research?.valid_close_count ?? 0)}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-md border border-border/60 bg-muted/30 p-3 space-y-2">
                    <Row
                      label="Close coverage"
                      value={formatPercentValue(research?.valid_close_coverage_pct ?? null, 1)}
                    />
                    <Row
                      label="Invalid close rate"
                      value={formatPercentValue(research?.invalid_close_rate_pct ?? null, 1)}
                    />
                  </div>

                  {research?.cohort_trend && research.cohort_trend.length > 0 && (
                    <div className="rounded-md border border-border/60 bg-muted/30 p-3 space-y-2">
                      <p className="text-xs text-muted-foreground">Cohort trend (last {research.cohort_trend.length})</p>
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {research.cohort_trend.map((c) => (
                          <div
                            key={c.cohort_key}
                            className="min-w-[190px] rounded border border-border/70 bg-background px-2 py-1.5 text-[11px] font-mono"
                          >
                            {c.cohort_key} • Valid {c.valid_close_count} • BC {formatMaybePercentDash(c.beat_close_pct)} • CLV{" "}
                            {formatMaybePercentDash(c.avg_clv_percent)}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <BreakdownChips title="By Surface" rows={research?.by_surface ?? []} />
                  <BreakdownChips title="By Source" rows={research?.by_source ?? []} />
                  <BreakdownChips title="By Edge Bucket" rows={research?.by_edge_bucket ?? []} />

                  <div className="pt-1 flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setShowAdvancedBreakdowns((v) => !v)}
                    >
                      {showAdvancedBreakdowns ? "Hide advanced breakdowns" : "Show advanced breakdowns"}
                    </Button>
                  </div>

                  {showAdvancedBreakdowns && (
                    <>
                      <BreakdownChips title="By Sportsbook" rows={research?.by_sportsbook ?? []} />
                      <BreakdownChips title="By Odds Bucket" rows={research?.by_odds_bucket ?? []} />
                    </>
                  )}

                  <div className="space-y-1.5">
                    <p className="text-xs text-muted-foreground">Recent opportunities</p>
                    <p className="text-[11px] text-muted-foreground">
                      Close statuses: Pending = reference at close not captured yet; Valid = captured inside the last 20-minute window; Invalid = captured/mapped but outside the valid window or missing CLV fields.
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
        </div>
      </div>
    </main>
  );
}
