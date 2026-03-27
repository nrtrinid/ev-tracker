"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type {
  OddsApiActivityCall,
  OddsApiActivityScanDetail,
  OddsApiActivityScanSession,
  OddsApiActivitySummary,
  OperatorStatusResponse,
} from "@/lib/types";

type HealthState = "healthy" | "warning" | "degraded" | "unknown";
type SourceFilter = "all" | "board_drop" | "jit" | "settlement" | "manual" | "other";
type UsageCategory = "board_drop" | "jit" | "settlement" | "manual" | "legacy" | "other";

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

function getSourceCategory(source?: string | null): UsageCategory {
  const normalized = (source || "").trim().toLowerCase();
  if (BOARD_DROP_SOURCES.has(normalized)) return "board_drop";
  if (JIT_SOURCES.has(normalized)) return "jit";
  if (SETTLEMENT_SOURCES.has(normalized)) return "settlement";
  if (MANUAL_SOURCES.has(normalized)) return "manual";
  if (normalized === "scheduled_scan") return "legacy";
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

function formatOddsSourceLabel(source?: string | null): string {
  const normalized = (source || "").trim().toLowerCase();
  if (normalized === "scheduled_board_drop") return "Scheduled board drop";
  if (normalized === "ops_trigger_board_drop") return "Ops board drop";
  if (normalized === "cron_board_drop") return "Cron board drop";
  if (normalized === "jit_clv") return "JIT CLV";
  if (normalized === "jit_clv_props") return "JIT CLV props";
  if (normalized === "auto_settle_scheduler") return "Auto-settle (scheduler)";
  if (normalized === "auto_settle_cron") return "Auto-settle (cron)";
  if (normalized === "auto_settle_ops_trigger") return "Auto-settle (ops trigger)";
  if (normalized === "manual_refresh") return "Manual refresh";
  if (normalized === "manual_refresh_props_events") return "Manual refresh props events";
  if (normalized === "manual_scan") return "Manual scan";
  if (normalized === "manual_scan_props_events") return "Manual scan props events";
  if (normalized === "scheduled_scan") return "Scheduled straight scan (legacy)";
  if (normalized === "manual_cli") return "Manual CLI";
  return source || "Unknown source";
}

function formatOddsEndpointLabel(endpoint?: string | null): string {
  const value = (endpoint || "").trim();
  if (!value) return "Unknown endpoint";
  if (value.includes("odds?markets=totals")) return "NBA totals slate";
  if (/\/sports\/[^/]+\/events\/[^/]+\/odds/i.test(value)) return "Event odds (props bundle)";
  if (value.endsWith("/scores")) return "Scores (settlement)";
  if (value.endsWith("/events")) return "Events list";
  if (/\/sports\/[^/]+\/odds/i.test(value)) return "Sport odds";
  return value;
}

function mapToSourceFilter(category: UsageCategory): SourceFilter {
  if (category === "board_drop") return "board_drop";
  if (category === "jit") return "jit";
  if (category === "settlement") return "settlement";
  if (category === "manual" || category === "legacy") return "manual";
  return "other";
}

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

type GapWarning = {
  afterTimestamp: string | null;
  beforeTimestamp: string | null;
  gapMinutes: number;
  unaccountedCredits: number;
};

function detectGaps(calls: OddsApiActivityCall[]): GapWarning[] {
  const liveOutbound = calls
    .filter((c) => c.outbound_call_made && !c.cache_hit)
    .sort((a, b) => {
      const at = parseOpsTimestamp(a.timestamp || null)?.getTime() ?? 0;
      const bt = parseOpsTimestamp(b.timestamp || null)?.getTime() ?? 0;
      return at - bt;
    });

  const gaps: GapWarning[] = [];
  for (let i = 1; i < liveOutbound.length; i++) {
    const prev = liveOutbound[i - 1];
    const curr = liveOutbound[i];
    const prevRemaining = parseRemainingValue(prev.api_requests_remaining);
    const currRemaining = parseRemainingValue(curr.api_requests_remaining);
    if (prevRemaining === null || currRemaining === null) continue;
    const drop = prevRemaining - currRemaining;
    if (drop <= 0) continue;

    const currCost = typeof curr.credits_used_last === "number" ? curr.credits_used_last : null;
    const unaccountedCredits = currCost !== null ? drop - currCost : drop;
    if (unaccountedCredits < 5) continue;

    const prevTs = parseOpsTimestamp(prev.timestamp || null)?.getTime() ?? 0;
    const currTs = parseOpsTimestamp(curr.timestamp || null)?.getTime() ?? 0;
    gaps.push({
      afterTimestamp: prev.timestamp || null,
      beforeTimestamp: curr.timestamp || null,
      gapMinutes: Math.round((currTs - prevTs) / 60000),
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
    return { label: "Healthy", className: "border-[#4A7C59]/30 bg-[#4A7C59]/10 text-[#2C5235]" };
  }
  if (state === "warning") {
    return { label: "Warning", className: "border-[#C4A35A]/35 bg-[#C4A35A]/15 text-[#5C4D2E]" };
  }
  if (state === "degraded") {
    return { label: "Degraded", className: "border-[#B85C38]/30 bg-[#B85C38]/10 text-[#8B3D20]" };
  }
  return { label: "Unknown", className: "border-border bg-muted text-muted-foreground" };
}

function Row({ label, value, dim }: { label: string; value: string; dim?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-mono text-xs text-right ${dim ? "text-muted-foreground" : ""}`}>{value}</span>
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
  return parts.join(" / ") || "No scan calls";
}

function formatCreditCost(call: OddsApiActivityCall): string {
  if (typeof call.credits_used_last === "number") return `${call.credits_used_last} cr`;
  return "cr n/a";
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

  // Credit budget
  const remainingSnapshot = useMemo(() => {
    for (const call of oddsRecentCalls) {
      if (call.api_requests_remaining !== null && call.api_requests_remaining !== undefined) {
        return parseRemainingValue(call.api_requests_remaining);
      }
    }
    return null;
  }, [oddsRecentCalls]);

  // Board drop
  const schedulerScan = data?.ops?.last_scheduler_scan;
  const schedulerBoardDrop = Boolean(schedulerScan?.board_drop || schedulerScan?.result);
  const boardDropCalls = useMemo(
    () => oddsRecentCalls.filter((c) => BOARD_DROP_SOURCES.has((c.source || "").trim().toLowerCase())),
    [oddsRecentCalls],
  );
  const boardDropLastRunAt =
    oddsApiActivity?.board_drop?.last_run_at ||
    schedulerScan?.finished_at ||
    schedulerScan?.captured_at ||
    boardDropCalls[0]?.timestamp ||
    null;
  const boardDropErrors =
    oddsApiActivity?.board_drop?.errors ?? boardDropCalls.filter((c) => isFailedActivity(c)).length;
  const boardDropExactCost = useMemo(
    () =>
      boardDropCalls.every((c) => typeof c.credits_used_last === "number")
        ? boardDropCalls.reduce((s, c) => s + (c.credits_used_last ?? 0), 0)
        : null,
    [boardDropCalls],
  );

  const boardDropDefaultVisibleCalls = 3;
  const boardDropCallsVisible = showBoardDropCalls
    ? boardDropCalls
    : boardDropCalls.slice(0, boardDropDefaultVisibleCalls);

  // Attribution rows (exact + inferred)
  const usageByCategory = useMemo(
    () =>
      buildUsageRows(
        oddsRecentCalls,
        (c) => getSourceCategory(c.source),
        (c) => CATEGORY_LABELS[getSourceCategory(c.source)],
      ),
    [oddsRecentCalls],
  );
  const usageByEndpoint = useMemo(
    () =>
      buildUsageRows(
        oddsRecentCalls,
        (c) => formatOddsEndpointLabel(c.endpoint),
        (c) => formatOddsEndpointLabel(c.endpoint),
      ),
    [oddsRecentCalls],
  );

  const exactTotalCredits = useMemo(
    () => usageByCategory.reduce((s, r) => s + r.exactCredits, 0),
    [usageByCategory],
  );
  const inferredTotalCredits = useMemo(
    () => usageByCategory.reduce((s, r) => s + r.inferredCredits, 0),
    [usageByCategory],
  );
  const hasAnyExactData = useMemo(() => usageByCategory.some((r) => r.hasExactData), [usageByCategory]);

  // Gap detector
  const gaps = useMemo(() => detectGaps(oddsRecentCalls), [oddsRecentCalls]);

  // Filtered call log
  const filteredCalls = useMemo(() => {
    if (sourceFilter === "all") return oddsRecentCalls;
    return oddsRecentCalls.filter((c) => mapToSourceFilter(getSourceCategory(c.source)) === sourceFilter);
  }, [oddsRecentCalls, sourceFilter]);

  const callsDefaultVisible = 6;
  const visibleCalls = showAllCalls ? filteredCalls : filteredCalls.slice(0, callsDefaultVisible);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Odds API</h2>
          <span
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${style.className}`}
          >
            {style.label}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* Credit budget */}
        <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2 space-y-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Credit budget</p>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Remaining</p>
              <p className={`text-sm font-semibold mt-0.5 ${remainingSnapshot !== null && remainingSnapshot <= 10 ? "text-[#B85C38]" : ""}`}>
                {remainingSnapshot === null ? "—" : remainingSnapshot}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Calls / hr</p>
              <p className="text-sm font-semibold mt-0.5">{scalarOrUnknown(oddsSummary?.calls_last_hour)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Errors / hr</p>
              <p className={`text-sm font-semibold mt-0.5 ${Number(oddsSummary?.errors_last_hour || 0) > 0 ? "text-[#B85C38]" : ""}`}>
                {scalarOrUnknown(oddsSummary?.errors_last_hour)}
              </p>
            </div>
          </div>
          <Row
            label="Last success"
            value={formatTimeWithRelative(oddsSummary?.last_success_at, "Unknown")}
            dim
          />
        </div>

        {/* Board drop — primary job */}
        <div className="rounded border border-border/60 bg-muted/30 px-2.5 py-2 space-y-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Daily board drop · primary job
          </p>
          {schedulerBoardDrop || boardDropCalls.length > 0 ? (
            <>
              <Row label="Last run" value={formatTimeWithRelative(boardDropLastRunAt, "Not recorded")} />
              <Row
                label="Props sides"
                value={scalarOrUnknown(schedulerScan?.result?.props_sides ?? schedulerScan?.total_sides)}
              />
              <Row
                label="Duration"
                value={schedulerScan?.duration_ms ? `${Math.round(schedulerScan.duration_ms)}ms` : "—"}
              />
              <Row
                label="Scan window"
                value={schedulerScan?.scan_window?.label || "Unknown"}
              />
              <Row
                label="Props events scanned"
                value={scalarOrUnknown(schedulerScan?.props_events_scanned)}
              />
              <Row
                label="Featured games"
                value={scalarOrUnknown(schedulerScan?.featured_games_count)}
              />
              <Row
                label="Credit cost"
                value={
                  boardDropExactCost !== null
                    ? `${boardDropExactCost} (exact)`
                    : boardDropCalls.length > 0
                      ? "Waiting for x-requests-last header"
                      : "—"
                }
              />
              <Row label="Calls" value={String(boardDropCalls.length)} />
              {boardDropErrors > 0 && (
                <p className="text-xs text-[#8B3D20]">⚠ {boardDropErrors} call error{boardDropErrors !== 1 ? "s" : ""}</p>
              )}
              {boardDropCalls.length > 0 && (
                <div className="mt-1 border-t border-border/50 pt-2 space-y-1">
                  {boardDropCallsVisible.map((call, idx) => {
                    const failed = isFailedActivity(call);
                    return (
                      <div
                        key={`board-call-${idx}`}
                        className={`rounded px-1.5 py-1 text-xs ${failed ? "bg-[#B85C38]/10 text-[#8B3D20]" : ""}`}
                      >
                        <p className="leading-relaxed">
                          {formatCompactTime(call.timestamp)} • {formatOddsEndpointLabel(call.endpoint)} •{" "}
                          <span className="font-semibold">{formatCreditCost(call)}</span> •{" "}
                          {formatQuotaLabel(call.api_requests_remaining)}
                          {failed ? ` • ${call.status_code ?? "ERR"} ${call.error_type ?? ""}` : ""}
                        </p>
                        {call.endpoint && formatOddsEndpointLabel(call.endpoint) !== call.endpoint && (
                          <p className="text-[10px] text-muted-foreground break-all mt-0.5">{call.endpoint}</p>
                        )}
                        {failed && call.error_message && (
                          <p className="text-[10px] text-muted-foreground mt-0.5">{call.error_message}</p>
                        )}
                      </div>
                    );
                  })}
                  {boardDropCalls.length > boardDropDefaultVisibleCalls && (
                    <div className="pt-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="px-0 h-auto text-xs"
                        onClick={() => setShowBoardDropCalls((v) => !v)}
                      >
                        {showBoardDropCalls
                          ? "Hide board drop logs"
                          : `Show ${boardDropCalls.length - boardDropDefaultVisibleCalls} more calls`}
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-muted-foreground">No board-drop run recorded yet.</p>
          )}
        </div>

        {/* Gap / unaccounted credits warning */}
        {gaps.length > 0 && (
          <div className="rounded border border-[#C4A35A]/40 bg-[#C4A35A]/10 px-2.5 py-2 space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[#5C4D2E]">
              ⚠ Unaccounted credits detected
            </p>
            {gaps.map((gap, idx) => (
              <p key={idx} className="text-xs text-[#5C4D2E]">
                {formatCompactTime(gap.afterTimestamp)} → {formatCompactTime(gap.beforeTimestamp)}:{" "}
                <span className="font-semibold">{gap.unaccountedCredits} credits</span> drained during a{" "}
                {gap.gapMinutes}m window with no calls logged. Check for a second deployment or another process using the same API key.
              </p>
            ))}
          </div>
        )}

        {/* Attribution by source */}
        <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-2 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Credit attribution
            </p>
            <span className="text-xs font-semibold">
              {hasAnyExactData ? `${exactTotalCredits} exact` : `${inferredTotalCredits} inferred`}
            </span>
          </div>
          {!hasAnyExactData && (
            <p className="text-[11px] text-muted-foreground">
              Inferred from balance drops — may show false attribution across gaps. Exact costs will appear after the next API call once the <code className="text-[10px]">credits_used_last</code> column is added to Supabase.
            </p>
          )}
          <div className="space-y-1">
            {usageByCategory.map((row) => (
              <div key={`cat-${row.key}`} className="flex items-center justify-between text-xs">
                <span>{row.label}</span>
                <span className="font-mono text-right">
                  {row.exactCredits > 0 && (
                    <span className="text-[#2C5235]">{row.exactCredits} exact</span>
                  )}
                  {row.exactCredits > 0 && row.inferredCredits > 0 && " + "}
                  {row.inferredCredits > 0 && (
                    <span className="text-muted-foreground">{row.inferredCredits} inferred</span>
                  )}
                  {row.exactCredits === 0 && row.inferredCredits === 0 && "0"}
                  <span className="text-muted-foreground ml-1.5">
                    {row.callCount} call{row.callCount !== 1 ? "s" : ""}
                    {row.errorCount > 0 ? ` · ${row.errorCount} err` : ""}
                  </span>
                </span>
              </div>
            ))}
            {usageByCategory.length === 0 && (
              <p className="text-xs text-muted-foreground">No recent call data available.</p>
            )}
          </div>
          {usageByEndpoint.length > 0 && (
            <details>
              <summary className="cursor-pointer text-[11px] text-muted-foreground">By endpoint</summary>
              <div className="mt-1.5 space-y-1">
                {usageByEndpoint.map((row) => (
                  <div key={`ep-${row.key}`} className="flex items-center justify-between text-xs">
                    <span className="break-all pr-2">{row.label}</span>
                    <span className="font-mono shrink-0">
                      {row.exactCredits > 0
                        ? `${row.exactCredits} exact`
                        : `${row.inferredCredits} inferred`}
                      <span className="text-muted-foreground ml-1">· {row.callCount}</span>
                    </span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>

        {/* Scanner sessions (collapsed by default) */}
        {oddsRecentScans.length > 0 && (
          <details open={showScanSessions} onToggle={(e) => setShowScanSessions((e.target as HTMLDetailsElement).open)}>
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Scanner sessions ({oddsRecentScans.length})
            </summary>
            <div className="mt-2 space-y-1.5">
              {oddsRecentScans.slice(0, 6).map((scan, index) => {
                const hasErrors = Boolean(scan.has_errors);
                return (
                  <details
                    key={`${scan.scan_session_id || scan.timestamp || "scan"}-${index}`}
                    className={`rounded border px-2 py-1.5 text-xs ${hasErrors ? "border-[#B85C38]/25 bg-[#B85C38]/10" : "border-border/70 bg-background/60"} [&_summary::-webkit-details-marker]:hidden`}
                  >
                    <summary className="cursor-pointer list-none">
                      <p className="leading-relaxed">
                        {formatCompactTime(scan.timestamp)} | {formatOddsSourceLabel(scan.source)} |{" "}
                        {formatLiveCacheMix(scan)} | {scalarOrUnknown(scan.total_events_fetched)} events |{" "}
                        {scalarOrUnknown(scan.total_sides)} sides
                      </p>
                    </summary>
                    <div className="mt-2 space-y-1 border-t border-border/50 pt-2">
                      {(scan.details ?? []).map((detail: OddsApiActivityScanDetail, di) => (
                        <p key={`${di}-${detail.sport || "sport"}`} className="text-xs leading-relaxed">
                          {detail.sport || "unknown sport"} •{" "}
                          {formatModeLabel(detail.cache_hit, detail.outbound_call_made)} •{" "}
                          {scalarOrUnknown(detail.events_fetched)} events •{" "}
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
        )}

        {/* Full call log with source filter */}
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
              ] as Array<[SourceFilter, string]>).map(([id, label]) => (
                <button
                  type="button"
                  key={id}
                  onClick={() => setSourceFilter(id)}
                  className={`rounded px-1.5 py-0.5 text-[10px] ${
                    sourceFilter === id
                      ? "bg-foreground text-background"
                      : "bg-muted text-muted-foreground"
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
                    className={`rounded border px-2 py-1.5 text-xs ${failed ? "border-[#B85C38]/25 bg-[#B85C38]/10" : "border-border/70 bg-muted/20"}`}
                  >
                    <p className="leading-relaxed">
                      {formatCompactTime(call.timestamp)} • {formatOddsSourceLabel(call.source)} •{" "}
                      {formatOddsEndpointLabel(call.endpoint)} • {status} •{" "}
                      <span className={typeof call.credits_used_last === "number" ? "font-semibold" : "text-muted-foreground"}>
                        {formatCreditCost(call)}
                      </span>{" "}
                      • {formatQuotaLabel(call.api_requests_remaining)}
                      {typeof call.duration_ms === "number" ? ` • ${Math.round(call.duration_ms)}ms` : ""}
                    </p>
                    {call.endpoint && formatOddsEndpointLabel(call.endpoint) !== call.endpoint && (
                      <p className="mt-0.5 text-[10px] text-muted-foreground break-all">{call.endpoint}</p>
                    )}
                    {failed && call.error_message && (
                      <p className="mt-0.5 text-[10px] text-muted-foreground">{call.error_message}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {filteredCalls.length > callsDefaultVisible && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="px-0 h-auto text-xs"
              onClick={() => setShowAllCalls((prev) => !prev)}
            >
              {showAllCalls
                ? "Show fewer calls"
                : `Show ${filteredCalls.length - callsDefaultVisible} more calls`}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
