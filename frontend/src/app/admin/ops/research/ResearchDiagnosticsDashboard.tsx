"use client";

import Link from "next/link";
import { useState } from "react";
import { RefreshCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  useModelCalibrationSummary,
  usePickEmResearchSummary,
  useResearchOpportunitySummary,
} from "@/lib/hooks";
import type {
  ModelCalibrationBreakdownItem,
  ModelCalibrationSummary,
  PickEmResearchBreakdownItem,
  ResearchOpportunityBreakdownItem,
  ResearchOpportunitySummary,
} from "@/lib/types";

const RESEARCH_STATUS_LABEL: Record<ResearchOpportunitySummary["aggregate_status"], string> = {
  not_captured: "Not captured",
  pending_close: "Pending close",
  invalid_only: "Invalid only",
  pending_and_invalid: "Pending + invalid",
  sample_too_small: "Sample too small",
  aggregate_available: "CLV metrics ready",
};

type ResearchScope = "all" | "displayed";

function formatCount(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  return value.toLocaleString();
}

function formatPercent(value: number | null | undefined, digits: number = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  return `${value.toFixed(digits)}%`;
}

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  return value.toFixed(4);
}

function numericDelta(candidate: number | null | undefined, baseline: number | null | undefined): number | null {
  if (typeof candidate !== "number" || Number.isNaN(candidate)) return null;
  if (typeof baseline !== "number" || Number.isNaN(baseline)) return null;
  return candidate - baseline;
}

function gateChip(summary: ModelCalibrationSummary | undefined): { label: string; className: string; title: string } {
  const gate = summary?.release_gate;
  if (!gate) {
    return {
      label: "Unknown",
      className: "border-border bg-muted text-muted-foreground",
      title: "Release-gate data unavailable.",
    };
  }

  if (!gate.eligible) {
    return {
      label: "Hold - not enough lift",
      className: "border-[#C4A35A]/35 bg-[#C4A35A]/15 text-[#5C4D2E]",
      title: "Not enough valid closes yet to make a confident promotion decision.",
    };
  }

  if (!gate.passes) {
    return {
      label: "Fail",
      className: "border-[#B85C38]/30 bg-[#B85C38]/10 text-[#8B3D20]",
      title: "Candidate model regressed past one or more release-gate thresholds.",
    };
  }

  const clvDelta = numericDelta(gate.candidate_avg_clv_percent, gate.baseline_avg_clv_percent);
  const beatCloseDelta = numericDelta(gate.candidate_beat_close_pct, gate.baseline_beat_close_pct);
  const brierLift = numericDelta(gate.baseline_avg_brier_score, gate.candidate_avg_brier_score);
  const logLossLift = numericDelta(gate.baseline_avg_log_loss, gate.candidate_avg_log_loss);

  const hasMaterialLift =
    (clvDelta !== null && clvDelta >= 0.25) ||
    (beatCloseDelta !== null && beatCloseDelta >= 2.0) ||
    (brierLift !== null && logLossLift !== null && brierLift >= 0.002 && logLossLift >= 0.002);

  if (hasMaterialLift) {
    return {
      label: "Promote - material improvement",
      className: "border-[#4A7C59]/30 bg-[#4A7C59]/10 text-[#2C5235]",
      title: "Candidate passed and shows material lift versus baseline.",
    };
  }

  const isNeutralPass =
    (clvDelta === null || Math.abs(clvDelta) < 0.15) &&
    (beatCloseDelta === null || Math.abs(beatCloseDelta) < 1.0) &&
    (brierLift === null || Math.abs(brierLift) < 0.0015) &&
    (logLossLift === null || Math.abs(logLossLift) < 0.0015);

  if (isNeutralPass) {
    return {
      label: "Pass, but neutral",
      className: "border-[#1F5D50]/35 bg-[#1F5D50]/10 text-[#1F5D50]",
      title: "Candidate passed safeguards but lift is essentially neutral.",
    };
  }

  return {
    label: "Hold - not enough lift",
    className: "border-[#C4A35A]/35 bg-[#C4A35A]/15 text-[#5C4D2E]",
    title: "Candidate passed safeguards, but improvement is not strong enough for promotion.",
  };
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/70 bg-muted/30 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-sm">{value}</p>
    </div>
  );
}

function DataNotLoaded() {
  return (
    <div className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
      Load diagnostics to run these endpoint summaries on demand.
    </div>
  );
}

function DataError({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-[#B85C38]/35 bg-[#B85C38]/10 px-3 py-2 text-sm text-[#8B3D20]">
      {message}
    </div>
  );
}

function DataLoading() {
  return <div className="text-sm text-muted-foreground">Loading diagnostics...</div>;
}

function ModelCalibrationBreakdownTable({ rows }: { rows: ModelCalibrationBreakdownItem[] }) {
  if (!rows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By model</p>
      <div className="rounded-md border border-border/70 bg-muted/20 px-2.5 py-2">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[540px] table-fixed text-xs">
            <colgroup>
              <col className="w-[28%]" />
              <col className="w-[12%]" />
              <col className="w-[12%]" />
              <col className="w-[16%]" />
              <col className="w-[16%]" />
              <col className="w-[16%]" />
            </colgroup>
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="pb-1.5 text-left font-medium">Model</th>
                <th className="pb-1.5 text-right font-medium">Valid</th>
                <th className="pb-1.5 text-right font-medium">Paired</th>
                <th className="pb-1.5 text-right font-medium">&gt;Close</th>
                <th className="pb-1.5 text-right font-medium">Avg CLV</th>
                <th className="pb-1.5 text-right font-medium">Brier</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 8).map((row) => (
                <tr key={row.key} className="border-t border-border/50">
                  <td className="py-1.5 pr-2 text-muted-foreground truncate">{row.key}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatCount(row.valid_close_count)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatCount(row.paired_close_count)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatPercent(row.beat_close_pct)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatPercent(row.avg_clv_percent)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatScore(row.avg_brier_score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function PickEmProbabilityBucketTable({ rows }: { rows: PickEmResearchBreakdownItem[] }) {
  if (!rows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By probability bucket</p>
      <div className="rounded-md border border-border/70 bg-muted/20 px-2.5 py-2">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] table-fixed text-xs">
            <colgroup>
              <col className="w-[30%]" />
              <col className="w-[14%]" />
              <col className="w-[18%]" />
              <col className="w-[18%]" />
              <col className="w-[20%]" />
            </colgroup>
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="pb-1.5 text-left font-medium">Bucket</th>
                <th className="pb-1.5 text-right font-medium">Settled</th>
                <th className="pb-1.5 text-right font-medium">Expected</th>
                <th className="pb-1.5 text-right font-medium">Actual</th>
                <th className="pb-1.5 text-right font-medium">Delta</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 8).map((row) => (
                <tr key={row.key} className="border-t border-border/50">
                  <td className="py-1.5 pr-2 text-muted-foreground truncate">{row.key}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatCount(row.settled_count)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatPercent(row.expected_hit_rate_pct)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatPercent(row.actual_hit_rate_pct)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatPercent(row.hit_rate_delta_pct_points, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ResearchEdgeBucketBreakdown({ rows }: { rows: ResearchOpportunityBreakdownItem[] }) {
  if (!rows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By edge bucket</p>
      <div className="rounded-md border border-border/70 bg-muted/20 px-2.5 py-2">
        <div className="overflow-x-auto">
          <table className="w-full table-fixed text-xs">
            <colgroup>
              <col className="w-[45%]" />
              <col className="w-[15%]" />
              <col className="w-[20%]" />
              <col className="w-[20%]" />
            </colgroup>
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="pb-1.5 text-left font-medium">Bucket</th>
                <th className="pb-1.5 text-right font-medium">Count</th>
                <th className="pb-1.5 text-right font-medium" title="Beat close % (better than close)">
                  &gt;Close
                </th>
                <th className="pb-1.5 text-right font-medium">Avg CLV</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 8).map((row) => (
                <tr key={row.key} className="border-t border-border/50">
                  <td className="py-1.5 pr-2 text-muted-foreground truncate">{row.key}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatCount(row.captured_count)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatPercent(row.beat_close_pct)}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{formatPercent(row.avg_clv_percent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function ResearchDiagnosticsDashboard() {
  const [loaded, setLoaded] = useState(false);
  const [researchScope, setResearchScope] = useState<ResearchScope>("all");
  const researchQuery = useResearchOpportunitySummary({
    enabled: loaded,
    scope: researchScope === "displayed" ? "board_default" : "all",
  });
  const calibrationQuery = useModelCalibrationSummary(loaded);
  const pickEmQuery = usePickEmResearchSummary(loaded);

  const isAnyFetching = researchQuery.isFetching || calibrationQuery.isFetching || pickEmQuery.isFetching;

  const research = researchQuery.data;
  const calibration = calibrationQuery.data;
  const pickEm = pickEmQuery.data;

  const researchError = researchQuery.error instanceof Error ? researchQuery.error.message : "Failed to load research opportunity summary.";
  const calibrationError = calibrationQuery.error instanceof Error ? calibrationQuery.error.message : "Failed to load model calibration summary.";
  const pickEmError = pickEmQuery.error instanceof Error ? pickEmQuery.error.message : "Failed to load pick'em research summary.";

  const gateStyle = gateChip(calibration);

  function triggerRefresh() {
    if (!loaded) {
      setLoaded(true);
      return;
    }
    researchQuery.refetch();
    calibrationQuery.refetch();
    pickEmQuery.refetch();
  }

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-5xl px-4 py-6 pb-20 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">Research Diagnostics</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Secondary diagnostics view for CLV research, model calibration, and pick&apos;em validation.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/ops">Back to ops</Link>
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={triggerRefresh} disabled={isAnyFetching}>
              <RefreshCcw className={`mr-1.5 h-4 w-4 ${isAnyFetching ? "animate-spin" : ""}`} />
              {loaded ? "Refresh" : "Load diagnostics"}
            </Button>
          </div>
        </div>

        <Card className="border-[#1F5D50]/20">
          <CardContent className="pt-6 text-sm text-muted-foreground">
            These queries are off by default on the main ops page to avoid background noise. Use this page when you need
            deeper diagnostics.
          </CardContent>
        </Card>

        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-base font-semibold">CLV Research Tracker</h2>
                <span className="inline-flex items-center rounded-md border border-border bg-muted px-2 py-1 text-xs text-muted-foreground">
                  {research ? RESEARCH_STATUS_LABEL[research.aggregate_status] : "Not loaded"}
                </span>
              </div>
              <div className="flex items-center gap-1.5 pt-1">
                <button
                  type="button"
                  className={`rounded-md border px-2 py-0.5 text-[11px] ${
                    researchScope === "all"
                      ? "border-[#1F5D50]/35 bg-[#1F5D50]/10 text-[#1F5D50]"
                      : "border-border text-muted-foreground"
                  }`}
                  onClick={() => setResearchScope("all")}
                >
                  All research
                </button>
                <button
                  type="button"
                  className={`rounded-md border px-2 py-0.5 text-[11px] ${
                    researchScope === "displayed"
                      ? "border-[#1F5D50]/35 bg-[#1F5D50]/10 text-[#1F5D50]"
                      : "border-border text-muted-foreground"
                  }`}
                  onClick={() => setResearchScope("displayed")}
                  title="Displayed set mirrors default opportunities board scope (entry EV > 1%)"
                >
                  Displayed set
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground pt-0.5">
                Displayed set mirrors the default Opportunities board scope: entry EV &gt; 1%.
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {!loaded && <DataNotLoaded />}
              {loaded && researchQuery.isLoading && !research && <DataLoading />}
              {loaded && researchQuery.isError && <DataError message={researchError} />}
              {loaded && research && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <StatCell label="Captured" value={formatCount(research.captured_count)} />
                    <StatCell label="Valid close" value={formatCount(research.valid_close_count)} />
                    <StatCell label="Pending close" value={formatCount(research.pending_close_count)} />
                    <StatCell label="Invalid" value={formatCount(research.invalid_close_count)} />
                    <StatCell label="Beat close" value={formatPercent(research.beat_close_pct)} />
                    <StatCell label="Avg CLV" value={formatPercent(research.avg_clv_percent)} />
                  </div>
                  <ResearchEdgeBucketBreakdown rows={research.by_edge_bucket} />
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-base font-semibold">Calibration Release Gate</h2>
                <span
                  className={`inline-flex items-center rounded-md border px-2 py-1 text-xs whitespace-nowrap ${gateStyle.className}`}
                  title={gateStyle.title}
                >
                  {gateStyle.label}
                </span>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {!loaded && <DataNotLoaded />}
              {loaded && calibrationQuery.isLoading && !calibration && <DataLoading />}
              {loaded && calibrationQuery.isError && <DataError message={calibrationError} />}
              {loaded && calibration && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <StatCell label="Captured" value={formatCount(calibration.captured_count)} />
                    <StatCell label="Valid close" value={formatCount(calibration.valid_close_count)} />
                    <StatCell label="Paired" value={formatCount(calibration.paired_close_count)} />
                    <StatCell label="Paired %" value={formatPercent(calibration.paired_close_pct)} />
                    <StatCell label="Candidate Brier" value={formatScore(calibration.release_gate.candidate_avg_brier_score)} />
                    <StatCell label="Baseline Brier" value={formatScore(calibration.release_gate.baseline_avg_brier_score)} />
                    <StatCell label="Candidate CLV" value={formatPercent(calibration.release_gate.candidate_avg_clv_percent)} />
                    <StatCell label="Baseline CLV" value={formatPercent(calibration.release_gate.baseline_avg_clv_percent)} />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    By model: Valid = trusted close snapshots. Paired = opportunities where baseline and candidate both have close-derived metrics.
                  </p>
                  <ModelCalibrationBreakdownTable rows={calibration.by_model} />
                  {calibration.release_gate.reasons.length > 0 && (
                    <p className="text-xs text-muted-foreground">Gate notes: {calibration.release_gate.reasons.join("; ")}</p>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <h2 className="text-base font-semibold">Pick&apos;em Validation</h2>
            </CardHeader>
            <CardContent className="space-y-3">
              {!loaded && <DataNotLoaded />}
              {loaded && pickEmQuery.isLoading && !pickEm && <DataLoading />}
              {loaded && pickEmQuery.isError && <DataError message={pickEmError} />}
              {loaded && pickEm && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <StatCell label="Captured" value={formatCount(pickEm.captured_count)} />
                    <StatCell label="Settled" value={formatCount(pickEm.settled_count)} />
                    <StatCell label="Decisive" value={formatCount(pickEm.decisive_count)} />
                    <StatCell label="Close ready" value={formatCount(pickEm.close_ready_count)} />
                    <StatCell label="Expected hit" value={formatPercent(pickEm.expected_hit_rate_pct)} />
                    <StatCell label="Actual hit" value={formatPercent(pickEm.actual_hit_rate_pct)} />
                    <StatCell label="Hit delta" value={formatPercent(pickEm.hit_rate_delta_pct_points, 2)} />
                    <StatCell label="Avg Brier" value={formatScore(pickEm.avg_brier_score)} />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    By probability bucket: Expected = displayed-probability hit rate, Actual = settled hit rate, Delta = Actual minus Expected.
                  </p>
                  <PickEmProbabilityBucketTable rows={pickEm.by_probability_bucket} />
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
