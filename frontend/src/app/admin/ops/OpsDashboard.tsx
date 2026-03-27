"use client";

import { useMemo } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCcw, XCircle } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
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
              {row.key}: {row.captured_count} captured | {formatPercentValue(row.beat_close_pct)}
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
            }}
            disabled={query.isFetching || researchQuery.isFetching}
          >
            <RefreshCcw className={`h-4 w-4 mr-1.5 ${(query.isFetching || researchQuery.isFetching) ? "animate-spin" : ""}`} />
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
              <Row
                label={schedulerScan?.board_drop ? "Last daily board drop" : "Last scheduler scan"}
                value={formatTime(schedulerScan?.finished_at || schedulerScan?.captured_at)}
              />
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
        </div>
      </div>
    </main>
  );
}
