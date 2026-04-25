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
  ModelCalibrationReleaseGate,
  ModelCalibrationSummary,
  PlayerPropShadowCandidateSummary,
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

function formatScore(value: number | null | undefined, digits: number = 4): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  return value.toFixed(digits);
}

function formatSignedDecimal(value: number | null | undefined, digits: number, suffix: string = ""): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  const displayZeroThreshold = 0.5 / Math.pow(10, digits);
  if (Math.abs(value) < displayZeroThreshold) return `${value.toFixed(digits)}${suffix}`;
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

function formatDeltaPoints(value: number | null | undefined, digits: number = 2): string {
  return formatSignedDecimal(value, digits, " pp");
}

function formatPoints(value: number | null | undefined, digits: number = 2): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  return `${value.toFixed(digits)} pp`;
}

function formatRatioWithPct(
  count: number | null | undefined,
  total: number | null | undefined,
  pct: number | null | undefined,
): string {
  const safeCount = formatCount(count);
  const safeTotal = formatCount(total);
  return `${safeCount} / ${safeTotal} (${formatPercent(pct)})`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Unknown";
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatSportLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return "Unknown";
  const parts = normalized.split("_").filter(Boolean);
  if (parts.length > 1) return parts[parts.length - 1].toUpperCase();
  return normalized.replace(/_/g, " ").toUpperCase();
}

function numericDelta(candidate: number | null | undefined, baseline: number | null | undefined): number | null {
  if (typeof candidate !== "number" || Number.isNaN(candidate)) return null;
  if (typeof baseline !== "number" || Number.isNaN(baseline)) return null;
  return candidate - baseline;
}

function roundedDelta(
  explicitDelta: number | null | undefined,
  candidate: number | null | undefined,
  baseline: number | null | undefined,
  digits: number,
): number | null {
  if (typeof explicitDelta === "number" && !Number.isNaN(explicitDelta)) return explicitDelta;
  const computedDelta = numericDelta(candidate, baseline);
  return computedDelta === null ? null : Number(computedDelta.toFixed(digits));
}

function hasReleaseGateSignalDiagnostics(gate: ModelCalibrationReleaseGate): boolean {
  return (
    typeof gate.identical_true_prob_count === "number" &&
    typeof gate.avg_abs_true_prob_delta_pct_points === "number" &&
    typeof gate.brier_candidate_better_count === "number" &&
    typeof gate.log_loss_candidate_better_count === "number"
  );
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

  switch (gate.verdict) {
    case "not_enough_sample":
      return {
        label: "Hold - sample small",
        className: "border-[#C4A35A]/35 bg-[#C4A35A]/15 text-[#5C4D2E]",
        title: "Not enough valid closes yet to make a confident promotion decision.",
      };
    case "hold_neutral":
      return {
        label: "Hold - neutral",
        className: "border-[#C4A35A]/35 bg-[#C4A35A]/15 text-[#5C4D2E]",
        title: "Candidate differences are inside the neutral deadband, so promotion remains blocked.",
      };
    case "fail":
      return {
        label: "Fail",
        className: "border-[#B85C38]/30 bg-[#B85C38]/10 text-[#8B3D20]",
        title: "Candidate model regressed past one or more release-gate thresholds.",
      };
    case "promote":
      return {
        label: "Promote",
        className: "border-[#4A7C59]/30 bg-[#4A7C59]/10 text-[#2C5235]",
        title: "Candidate cleared the promotion safeguards.",
      };
  }
  return {
    label: "Unknown",
    className: "border-border bg-muted text-muted-foreground",
    title: "Release-gate verdict is unavailable.",
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

function BreakdownMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border/60 bg-background/60 px-2 py-1">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-[11px] tabular-nums text-foreground">{value}</p>
    </div>
  );
}

function deltaToneClass(delta: number | null | undefined, lowerIsBetter: boolean): string {
  if (typeof delta !== "number" || Number.isNaN(delta) || Math.abs(delta) < 1e-9) {
    return "text-muted-foreground";
  }
  const improved = lowerIsBetter ? delta < 0 : delta > 0;
  return improved ? "text-[#1F5D50]" : "text-[#8B3D20]";
}

function CalibrationComparisonTable({ gate }: { gate: ModelCalibrationReleaseGate }) {
  const brierDelta = roundedDelta(
    gate.brier_delta,
    gate.candidate_avg_brier_score,
    gate.baseline_avg_brier_score,
    6,
  );
  const logLossDelta = roundedDelta(
    gate.log_loss_delta,
    gate.candidate_avg_log_loss,
    gate.baseline_avg_log_loss,
    6,
  );
  const avgClvDelta = roundedDelta(
    gate.avg_clv_delta_pct_points,
    gate.candidate_avg_clv_percent,
    gate.baseline_avg_clv_percent,
    2,
  );
  const beatCloseDelta = roundedDelta(
    gate.beat_close_delta_pct_points,
    gate.candidate_beat_close_pct,
    gate.baseline_beat_close_pct,
    2,
  );
  const rows = [
    {
      key: "brier",
      label: "Brier (lower)",
      baseline: formatScore(gate.baseline_avg_brier_score, 6),
      candidate: formatScore(gate.candidate_avg_brier_score, 6),
      delta: brierDelta,
      deltaLabel: formatSignedDecimal(brierDelta, 6),
      lowerIsBetter: true,
    },
    {
      key: "log_loss",
      label: "Log loss (lower)",
      baseline: formatScore(gate.baseline_avg_log_loss, 6),
      candidate: formatScore(gate.candidate_avg_log_loss, 6),
      delta: logLossDelta,
      deltaLabel: formatSignedDecimal(logLossDelta, 6),
      lowerIsBetter: true,
    },
    {
      key: "avg_clv",
      label: "Avg CLV (higher)",
      baseline: formatPercent(gate.baseline_avg_clv_percent, 2),
      candidate: formatPercent(gate.candidate_avg_clv_percent, 2),
      delta: avgClvDelta,
      deltaLabel: formatDeltaPoints(avgClvDelta, 2),
      lowerIsBetter: false,
    },
    {
      key: "beat_close",
      label: ">Close (higher)",
      baseline: formatPercent(gate.baseline_beat_close_pct, 2),
      candidate: formatPercent(gate.candidate_beat_close_pct, 2),
      delta: beatCloseDelta,
      deltaLabel: formatDeltaPoints(beatCloseDelta, 2),
      lowerIsBetter: false,
    },
  ];

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Gate comparison</p>
      <div className="rounded-md border border-border/70 bg-muted/20 px-2.5 py-2">
        <div className="overflow-x-auto">
          <table className="w-full table-fixed text-xs">
            <colgroup>
              <col className="w-[34%]" />
              <col className="w-[22%]" />
              <col className="w-[22%]" />
              <col className="w-[22%]" />
            </colgroup>
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="pb-1.5 text-left font-medium">Metric</th>
                <th className="pb-1.5 text-right font-medium">Baseline</th>
                <th className="pb-1.5 text-right font-medium">Candidate</th>
                <th className="pb-1.5 text-right font-medium">Delta</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-t border-border/50">
                  <td className="py-1.5 pr-2 text-muted-foreground">{row.label}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{row.baseline}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{row.candidate}</td>
                  <td className={`py-1.5 text-right font-mono tabular-nums ${deltaToneClass(row.delta, row.lowerIsBetter)}`}>
                    {row.deltaLabel}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function CalibrationGateReadout({ gate, pairedCount }: { gate: ModelCalibrationReleaseGate; pairedCount: number }) {
  const brierDelta = roundedDelta(
    gate.brier_delta,
    gate.candidate_avg_brier_score,
    gate.baseline_avg_brier_score,
    6,
  );
  const logLossDelta = roundedDelta(
    gate.log_loss_delta,
    gate.candidate_avg_log_loss,
    gate.baseline_avg_log_loss,
    6,
  );
  const hasSignalDiagnostics = hasReleaseGateSignalDiagnostics(gate);
  const allProbabilitiesSame = pairedCount > 0 && gate.identical_true_prob_count === pairedCount;
  const brierFlat = typeof brierDelta === "number" && Math.abs(brierDelta) < 0.0000005;
  const logLossFlat = typeof logLossDelta === "number" && Math.abs(logLossDelta) < 0.0000005;
  const logLossWorse = typeof logLossDelta === "number" && logLossDelta > 0;

  let message = "Release decision is driven by paired-row Brier, log loss, CLV, and beat-close deltas.";
  if (gate.verdict === "not_enough_sample") {
    message = "Candidate does not have enough paired valid closes for a release decision yet.";
  } else if (gate.verdict === "hold_neutral") {
    message = "Candidate has enough paired closes, but the differences are inside the neutral deadband rather than a meaningful lift.";
  } else if (allProbabilitiesSame && brierFlat && logLossFlat) {
    message = "Candidate probabilities are identical on every paired opportunity; the gate is holding because there is no measurable Brier or log-loss lift.";
  } else if (!hasSignalDiagnostics && !gate.passes && gate.eligible && brierFlat && logLossWorse) {
    message = "Candidate has enough paired closes, but log loss is microscopically worse while Brier is not visibly better at this precision.";
  } else if (gate.verdict === "fail") {
    message = "Candidate has enough paired closes, but one or more paired-row metrics did not improve versus the live baseline.";
  } else if (gate.verdict === "promote") {
    message = "Candidate clears the paired-row safeguards; use the deltas below to judge whether the lift is material.";
  }

  return (
    <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      {message}
    </div>
  );
}

function CalibrationSignalDiagnostics({
  gate,
  pairedCount,
}: {
  gate: ModelCalibrationReleaseGate;
  pairedCount: number;
}) {
  if (!hasReleaseGateSignalDiagnostics(gate)) {
    return (
      <div className="space-y-1.5">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Model signal check</p>
        <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          Pairwise probability and row-win diagnostics were not returned by the current backend response. The gate comparison above is computed from the aggregate fields that are available.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Model signal check</p>
      <div className="grid grid-cols-2 gap-1.5">
        <BreakdownMetric
          label="Same true prob"
          value={formatRatioWithPct(gate.identical_true_prob_count, pairedCount, gate.identical_true_prob_pct)}
        />
        <BreakdownMetric label="Avg |prob delta|" value={formatPoints(gate.avg_abs_true_prob_delta_pct_points, 4)} />
        <BreakdownMetric label="Max |prob delta|" value={formatPoints(gate.max_abs_true_prob_delta_pct_points, 4)} />
        <BreakdownMetric label="Avg EV delta" value={formatDeltaPoints(gate.avg_ev_delta_pct_points, 4)} />
        <BreakdownMetric
          label="Same EV"
          value={formatRatioWithPct(gate.identical_ev_count, pairedCount, gate.identical_ev_pct)}
        />
        <BreakdownMetric label="Avg |EV delta|" value={formatPoints(gate.avg_abs_ev_delta_pct_points, 4)} />
        <BreakdownMetric
          label="Brier C/B/T"
          value={`${formatCount(gate.brier_candidate_better_count)} / ${formatCount(gate.brier_baseline_better_count)} / ${formatCount(gate.brier_tie_count)}`}
        />
        <BreakdownMetric
          label="Log C/B/T"
          value={`${formatCount(gate.log_loss_candidate_better_count)} / ${formatCount(gate.log_loss_baseline_better_count)} / ${formatCount(gate.log_loss_tie_count)}`}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Paired CLV and &gt;Close compare the same opportunity/book/close. Probability deltas show whether the candidate model actually moved the math.
      </p>
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

function ModelCalibrationBreakdownTable({ rows }: { rows?: ModelCalibrationBreakdownItem[] | null }) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By model</p>
      <div className="space-y-1.5">
        {safeRows.slice(0, 8).map((row) => (
          <div key={row.key} className="rounded-md border border-border/70 bg-muted/20 px-2.5 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-xs font-medium text-foreground">{row.key}</p>
              <p className="font-mono text-[11px] tabular-nums text-muted-foreground">
                Valid rows {formatCount(row.valid_close_count)}
              </p>
            </div>
            <div className="mt-1.5 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
              <BreakdownMetric label="Paired opps" value={formatCount(row.paired_close_count)} />
              <BreakdownMetric label=">Close" value={formatPercent(row.beat_close_pct)} />
              <BreakdownMetric label="Avg CLV" value={formatPercent(row.avg_clv_percent)} />
              <BreakdownMetric label="Brier" value={formatScore(row.avg_brier_score)} />
              <BreakdownMetric label="Log loss" value={formatScore(row.avg_log_loss)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function weightStatusLabel(summary: PlayerPropShadowCandidateSummary | null | undefined): string {
  const status = summary?.weight_status;
  if (!status || !status.available) return "Weights unavailable";
  if (status.default_only) return "Default weights only";
  if (status.stale) return "Weights stale";
  return "Weights active";
}

function ShadowCandidateSetCard({
  summary,
  isLoading,
  isError,
  errorMessage,
}: {
  summary?: PlayerPropShadowCandidateSummary | null;
  isLoading: boolean;
  isError: boolean;
  errorMessage: string;
}) {
  const weightStatus = summary?.weight_status;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">V2 Shadow Candidate Set</h2>
          <span className="inline-flex items-center rounded-md border border-border bg-muted px-2 py-1 text-xs whitespace-nowrap text-muted-foreground">
            {weightStatusLabel(summary)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && !summary && <DataLoading />}
        {isError && <DataError message={errorMessage} />}
        {summary && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <StatCell label="V1 only" value={formatCount(summary.v1_only_count)} />
              <StatCell label="V2 only" value={formatCount(summary.v2_only_count)} />
              <StatCell label="Both" value={formatCount(summary.both_count)} />
              <StatCell label="Overlap" value={formatPercent(summary.overlap_pct)} />
              <StatCell label="V2 actionable" value={formatCount(summary.v2_only_displayed_count)} />
              <StatCell label="Captured at" value={formatTimestamp(summary.latest_captured_at)} />
            </div>

            <div className="space-y-1.5">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Latest movement</p>
              <div className="grid grid-cols-2 gap-1.5">
                <BreakdownMetric label="Top 25 overlap" value={formatPercent(summary.top_25_overlap_pct)} />
                <BreakdownMetric label="Top 50 overlap" value={formatPercent(summary.top_50_overlap_pct)} />
                <BreakdownMetric label="Avg EV delta" value={formatDeltaPoints(summary.avg_ev_delta_pct_points, 4)} />
                <BreakdownMetric label="Avg rank delta" value={formatSignedDecimal(summary.avg_rank_delta, 2)} />
              </div>
            </div>

            <div className="space-y-1.5">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Rolling sets</p>
              <div className="grid grid-cols-2 gap-1.5">
                <BreakdownMetric label="Sets" value={formatCount(summary.rolling_candidate_set_count)} />
                <BreakdownMetric label="Overlap" value={formatPercent(summary.rolling_overlap_pct)} />
                <BreakdownMetric label="V1 only" value={formatCount(summary.rolling_v1_only_count)} />
                <BreakdownMetric label="V2 only" value={formatCount(summary.rolling_v2_only_count)} />
              </div>
            </div>

            <div className="space-y-1.5">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">V2-only close performance</p>
              <div className="grid grid-cols-2 gap-1.5">
                <BreakdownMetric label="Valid closes" value={formatCount(summary.v2_only_valid_close_count)} />
                <BreakdownMetric label=">Close" value={formatPercent(summary.v2_only_beat_close_pct)} />
                <BreakdownMetric label="Avg CLV" value={formatPercent(summary.v2_only_avg_clv_percent)} />
                <BreakdownMetric label="Brier" value={formatScore(summary.v2_only_avg_brier_score)} />
                <BreakdownMetric label="Log loss" value={formatScore(summary.v2_only_avg_log_loss)} />
                <BreakdownMetric label="Actionable roll" value={formatCount(summary.rolling_v2_only_displayed_count)} />
              </div>
            </div>

            <div className="space-y-1.5">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Weight status</p>
              <div className="grid grid-cols-2 gap-1.5">
                <BreakdownMetric label="Overrides" value={formatCount(weightStatus?.override_count)} />
                <BreakdownMetric label="Markets" value={formatCount(weightStatus?.markets_covered)} />
                <BreakdownMetric label="Latest" value={formatTimestamp(weightStatus?.latest_updated_at)} />
                <BreakdownMetric label="Stale after" value={`${formatCount(weightStatus?.stale_after_hours)}h`} />
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function PickEmProbabilityBucketTable({ rows }: { rows?: PickEmResearchBreakdownItem[] | null }) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By probability bucket</p>
      <div className="space-y-1.5">
        {safeRows.slice(0, 8).map((row) => (
          <div key={row.key} className="rounded-md border border-border/70 bg-muted/20 px-2.5 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-xs font-medium text-foreground">{row.key}</p>
              <p className="font-mono text-[11px] tabular-nums text-muted-foreground">
                Settled {formatCount(row.settled_count)}
              </p>
            </div>
            <div className="mt-1.5 grid grid-cols-3 gap-1.5">
              <BreakdownMetric label="Expected" value={formatPercent(row.expected_hit_rate_pct)} />
              <BreakdownMetric label="Actual" value={formatPercent(row.actual_hit_rate_pct)} />
              <BreakdownMetric label="Delta" value={formatPercent(row.hit_rate_delta_pct_points, 2)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResearchEdgeBucketBreakdown({ rows }: { rows?: ResearchOpportunityBreakdownItem[] | null }) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) return null;

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
              {safeRows.slice(0, 8).map((row) => (
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

function ResearchMarketBreakdown({ rows }: { rows?: ResearchOpportunityBreakdownItem[] | null }) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By market</p>
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
                <th className="pb-1.5 text-left font-medium">Market</th>
                <th
                  className="pb-1.5 text-right font-medium"
                  title="Valid close rows / captured rows"
                >
                  Count (valid/cap)
                </th>
                <th className="pb-1.5 text-right font-medium" title="Beat close % (better than close)">
                  &gt;Close
                </th>
                <th className="pb-1.5 text-right font-medium">Avg CLV</th>
              </tr>
            </thead>
            <tbody>
              {safeRows.map((row) => (
                <tr key={row.key} className="border-t border-border/50">
                  <td className="py-1.5 pr-2 text-muted-foreground truncate">{row.key}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {formatCount(row.valid_close_count)} / {formatCount(row.captured_count)}
                  </td>
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

function ResearchDropTimeBreakdown({ rows }: { rows?: ResearchOpportunityBreakdownItem[] | null }) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By drop time</p>
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
                <th className="pb-1.5 text-left font-medium">Drop time</th>
                <th className="pb-1.5 text-right font-medium">Count</th>
                <th className="pb-1.5 text-right font-medium" title="Beat close % (better than close)">
                  &gt;Close
                </th>
                <th className="pb-1.5 text-right font-medium">Avg CLV</th>
              </tr>
            </thead>
            <tbody>
              {safeRows.slice(0, 8).map((row) => (
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

function ResearchEventDayBreakdown({ rows }: { rows?: ResearchOpportunityBreakdownItem[] | null }) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">By event day</p>
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
                <th className="pb-1.5 text-left font-medium">Event day</th>
                <th
                  className="pb-1.5 text-right font-medium"
                  title="Valid close rows / captured rows"
                >
                  Count
                </th>
                <th className="pb-1.5 text-right font-medium" title="Beat close % (better than close)">
                  &gt;Close
                </th>
                <th className="pb-1.5 text-right font-medium">Avg CLV</th>
              </tr>
            </thead>
            <tbody>
              {safeRows.slice(0, 8).map((row) => (
                <tr key={row.key} className="border-t border-border/50">
                  <td className="py-1.5 pr-2 text-muted-foreground truncate">{row.key}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {formatCount(row.valid_close_count)} / {formatCount(row.captured_count)}
                  </td>
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
  const [researchScope, setResearchScope] = useState<ResearchScope>("all");
  const researchQuery = useResearchOpportunitySummary({
    enabled: true,
    scope: researchScope === "displayed" ? "board_default" : "all",
  });
  const calibrationQuery = useModelCalibrationSummary(true);
  const pickEmQuery = usePickEmResearchSummary(true);

  const isAnyFetching = researchQuery.isFetching || calibrationQuery.isFetching || pickEmQuery.isFetching;

  const research = researchQuery.data;
  const calibration = calibrationQuery.data;
  const pickEm = pickEmQuery.data;

  const researchError = researchQuery.error instanceof Error ? researchQuery.error.message : "Failed to load research opportunity summary.";
  const calibrationError = calibrationQuery.error instanceof Error ? calibrationQuery.error.message : "Failed to load model calibration summary.";
  const pickEmError = pickEmQuery.error instanceof Error ? pickEmQuery.error.message : "Failed to load pick'em research summary.";

  const gateStyle = gateChip(calibration);

  function triggerRefresh() {
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
              Refresh
            </Button>
          </div>
        </div>

        <Card className="border-[#1F5D50]/20">
          <CardContent className="pt-6 text-sm text-muted-foreground">
            These queries are off by default on the main ops page to avoid background noise. Use this page when you need
            deeper diagnostics.
          </CardContent>
        </Card>

        <div className="grid gap-4 xl:grid-cols-2">
          <Card className="xl:col-span-2">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-base font-semibold">CLV Research Tracker</h2>
                <span className="inline-flex items-center rounded-md border border-border bg-muted px-2 py-1 text-xs text-muted-foreground">
                  {research ? RESEARCH_STATUS_LABEL[research.aggregate_status] : "Loading..."}
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
              {researchQuery.isLoading && !research && <DataLoading />}
              {researchQuery.isError && <DataError message={researchError} />}
              {research && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <StatCell label="Captured" value={formatCount(research.captured_count)} />
                    <StatCell label="Valid close" value={formatCount(research.valid_close_count)} />
                    <StatCell label="Pending close" value={formatCount(research.pending_close_count)} />
                    <StatCell label="Invalid" value={formatCount(research.invalid_close_count)} />
                    <StatCell label="Beat close" value={formatPercent(research.beat_close_pct)} />
                    <StatCell label="Avg CLV" value={formatPercent(research.avg_clv_percent)} />
                  </div>
                  <ResearchMarketBreakdown rows={research.by_market} />
                  <ResearchEdgeBucketBreakdown rows={research.by_edge_bucket} />
                  <ResearchDropTimeBreakdown rows={research.by_drop_time} />
                  <ResearchEventDayBreakdown rows={research.by_event_day} />
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
              {calibrationQuery.isLoading && !calibration && <DataLoading />}
              {calibrationQuery.isError && <DataError message={calibrationError} />}
              {calibration && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <StatCell label="Captured rows" value={formatCount(calibration.captured_count)} />
                    <StatCell label="Valid rows" value={formatCount(calibration.valid_close_count)} />
                    <StatCell label="Paired opps" value={formatCount(calibration.paired_close_count)} />
                    <StatCell label="Paired %" value={formatPercent(calibration.paired_close_pct)} />
                    <StatCell label="Candidate rows" value={formatCount(calibration.release_gate.candidate_valid_close_count)} />
                    <StatCell label="Baseline rows" value={formatCount(calibration.release_gate.baseline_valid_close_count)} />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Captured and valid counts are evaluation rows. Paired opportunities are unique opportunity keys where both baseline and candidate have valid close-derived metrics.
                  </p>
                  <CalibrationGateReadout gate={calibration.release_gate} pairedCount={calibration.paired_close_count} />
                  <CalibrationComparisonTable gate={calibration.release_gate} />
                  <CalibrationSignalDiagnostics gate={calibration.release_gate} pairedCount={calibration.paired_close_count} />
                  <ModelCalibrationBreakdownTable rows={calibration.by_model} />
                  {Array.isArray(calibration.release_gate.reasons) && calibration.release_gate.reasons.length > 0 && (
                    <p className="text-xs text-muted-foreground">Gate notes: {calibration.release_gate.reasons.join("; ")}</p>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          <ShadowCandidateSetCard
            summary={calibration?.shadow_candidate_set}
            isLoading={calibrationQuery.isLoading}
            isError={calibrationQuery.isError}
            errorMessage={calibrationError}
          />

          <Card>
            <CardHeader className="pb-3">
              <h2 className="text-base font-semibold">Pick&apos;em Validation</h2>
            </CardHeader>
            <CardContent className="space-y-3">
              {pickEmQuery.isLoading && !pickEm && <DataLoading />}
              {pickEmQuery.isError && <DataError message={pickEmError} />}
              {pickEm && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <StatCell label="Captured" value={formatCount(pickEm.captured_count)} />
                    <StatCell label="Settled" value={formatCount(pickEm.settled_count)} />
                    <StatCell label="Decisive" value={formatCount(pickEm.decisive_count)} />
                    <StatCell label="Auto pending" value={formatCount(pickEm.auto_settle_pending_count)} />
                    <StatCell label="Manual only" value={formatCount(pickEm.manual_result_count)} />
                    <StatCell label="Close ready" value={formatCount(pickEm.close_ready_count)} />
                    <StatCell label="Expected hit" value={formatPercent(pickEm.expected_hit_rate_pct)} />
                    <StatCell label="Actual hit" value={formatPercent(pickEm.actual_hit_rate_pct)} />
                    <StatCell label="Hit delta" value={formatPercent(pickEm.hit_rate_delta_pct_points, 2)} />
                    <StatCell label="Avg Brier" value={formatScore(pickEm.avg_brier_score)} />
                  </div>
                  {Array.isArray(pickEm.manual_only_sports) && pickEm.manual_only_sports.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Manual-only sports in this sample: {pickEm.manual_only_sports.map(formatSportLabel).join(", ")}.
                      These rows stay in validation tracking, but results are expected to be graded manually during beta.
                    </p>
                  )}
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
