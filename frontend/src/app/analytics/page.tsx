"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MetricCard, MetricTile } from "@/components/shared/MetricCard";
import { useBankrollDrawer } from "@/components/bankroll/BankrollProvider";
import { getAllBetsForStats, getBalances, getSettings } from "@/lib/api";
import {
  buildStatsPageModel,
  type StatsChartFilter,
  type StatsChartPoint,
  type VerdictState,
} from "@/lib/stats-page";
import { getTrackerSourceLabel, matchesTrackerSourceFilter } from "@/lib/tracker-source";
import { buildTrackerViewQuery, parseTrackerSourceFilter } from "@/lib/tracker-view";
import { cn, formatCurrency } from "@/lib/utils";

// ─── Theme ───────────────────────────────────────────────────────────────────

const CHART_THEME = {
  varianceFill: "hsl(var(--primary) / 0.10)",
  varianceStroke: "hsl(var(--primary) / 0.20)",
  evStroke: "hsl(var(--primary))",
  profitStroke: "hsl(var(--profit))",
};

// Verdict card: left-border accent — slightly thicker for more presence.
const VERDICT_STYLES: Record<
  VerdictState,
  { leftBorder: string; label: string; accent: string }
> = {
  hot:            { leftBorder: "border-l-[3px] border-l-primary",  label: "text-primary", accent: "text-primary" },
  on_track:       { leftBorder: "border-l-[3px] border-l-profit",   label: "text-profit",  accent: "text-profit"  },
  cold_but_okay:  { leftBorder: "border-l-[3px] border-l-border",   label: "text-foreground", accent: "text-muted-foreground" },
  worth_reviewing:{ leftBorder: "border-l-[3px] border-l-loss",     label: "text-loss",    accent: "text-loss"    },
};

const CHART_FILTERS: Array<{ value: StatsChartFilter; label: string }> = [
  { value: "all",    label: "All"    },
  { value: "core",   label: "Core Bets"  },
  { value: "promos", label: "Promos" },
];

// ─── Formatters ──────────────────────────────────────────────────────────────

function formatSignedCurrency(value: number | null): string {
  if (value === null) return "—";
  return `${value >= 0 ? "+" : ""}${formatCurrency(value)}`;
}

function formatSwing(value: number): string {
  return `±${formatCurrency(value)}`;
}

function formatWeeklyChange(value: number): string {
  return `${formatSignedCurrency(value)} this wk`;
}

function formatPercent(value: number | null): string {
  if (value === null) return "-";
  return `${value.toFixed(1)}%`;
}

function formatCoverage(value: number | null): string | null {
  if (value === null) return null;
  return `${value.toFixed(1)}%`;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

/**
 * Chart filter pills — same visual language as the duplicate-state badges
 * on scanner cards: small, bordered, uppercase tracking.
 */
function ChartFilterPill({
  active,
  label,
  disabled = false,
  onClick,
}: {
  active: boolean;
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded px-2.5 py-1 text-xs font-medium transition-colors",
        disabled && "cursor-not-allowed opacity-60",
        active
          ? "bg-primary/20 text-foreground font-semibold ring-1 ring-primary/30"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}

/**
 * Inline chart legend — sits on the same row as the filter pills.
 */
function ChartLegend() {
  return (
    <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-[2px] w-4 rounded-full bg-[hsl(var(--primary))]" />
        EV
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-[2px] w-4 rounded-full bg-[hsl(var(--profit))]" />
        Profit
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2.5 w-3.5 rounded-sm border border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.10)]" />
        Range
      </span>
    </div>
  );
}

/**
 * Chart hover tooltip — warm card surface, mono numbers, colored line dots.
 */
function StatsChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: StatsChartPoint }>;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;

  return (
    <div className="rounded border border-border/80 bg-card px-3 py-2.5 shadow-md">
      <p className="text-[11px] font-semibold text-foreground">{point.dateLabel}</p>
      <div className="mt-2 space-y-1.5 text-xs">
        <div className="flex items-center justify-between gap-5">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span className="inline-block h-[2px] w-3 rounded-full bg-[hsl(var(--profit))]" />
            Profit
          </span>
          <span className={cn("font-mono font-bold tabular-nums", point.cumulativeProfit >= 0 ? "text-profit" : "text-loss")}>
            {formatSignedCurrency(point.cumulativeProfit)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-5">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span className="inline-block h-[2px] w-3 rounded-full bg-[hsl(var(--primary))]" />
            EV
          </span>
          <span className="font-mono font-bold tabular-nums text-primary">
            {formatSignedCurrency(point.cumulativeEv)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-5 border-t border-border/50 pt-1.5">
          <span className="text-muted-foreground">Range</span>
          <span className="font-mono tabular-nums text-muted-foreground">
            {formatCurrency(point.varianceLow)} – {formatCurrency(point.varianceHigh)}
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Source breakdown row — Core Bets / Promos.
 * Two-column tile layout so EV and Profit sit side-by-side at the same size.
 * When an href is provided the whole row is a link — chevron + hover state
 * make that affordance obvious.
 */
function SourceBreakdownRow({
  label,
  ev,
  profit,
  dotClass,
  href,
}: {
  label: string;
  ev: number;
  profit: number;
  dotClass?: string;
  href?: string;
}) {
  const gap = profit - ev;

  const inner = (
    <>
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("h-1.5 w-1.5 rounded-full opacity-70", dotClass ?? "bg-muted-foreground")} />
          <p className="text-xs font-medium text-foreground">{label}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "font-mono text-[11px] tabular-nums",
              gap >= 0 ? "text-profit/80" : "text-loss/80",
            )}
          >
            {gap >= 0 ? "+" : ""}{formatCurrency(gap)} vs EV
          </span>
          {href && (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-muted-foreground" />
          )}
        </div>
      </div>

      {/* Profit / EV tiles */}
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <div className="rounded border border-border/70 bg-background px-2.5 py-2">
          <p className="text-[11px] font-medium text-muted-foreground">Profit</p>
          <p className={cn("mt-1 font-mono text-sm font-bold tabular-nums", profit >= 0 ? "text-profit" : "text-loss")}>
            {formatSignedCurrency(profit)}
          </p>
        </div>
        <div className="rounded border border-border/70 bg-background px-2.5 py-2">
          <p className="text-[11px] font-medium text-muted-foreground">EV</p>
          <p className="mt-1 font-mono text-sm font-bold tabular-nums text-primary">
            {formatSignedCurrency(ev)}
          </p>
        </div>
      </div>
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        data-testid="source-row"
        aria-label={`View ${label} bets`}
        className="group block rounded border border-border/60 bg-background/50 px-3 py-3 transition-colors hover:border-border hover:bg-muted/20 active:scale-[0.98] active:bg-muted/25"
      >
        {inner}
      </Link>
    );
  }

  return (
    <div data-testid="source-row" className="rounded border border-border/60 bg-background/50 px-3 py-3">
      {inner}
    </div>
  );
}

function ProcessStatRow({
  label,
  subtitle,
  value,
  secondaryValue,
}: {
  label: string;
  subtitle: string;
  value: string;
  secondaryValue?: string | null;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3.5">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-foreground">
          {label}
        </p>
        <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
          {subtitle}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="font-mono text-base font-semibold tabular-nums text-foreground">
          {value}
        </p>
        {secondaryValue ? (
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {secondaryValue}
          </p>
        ) : null}
      </div>
    </div>
  );
}

// ─── Skeleton ────────────────────────────────────────────────────────────────

function StatsPageSkeleton() {
  return (
    <div className="space-y-3">
      <Card className="border-l-4 border-l-border border-border/70">
        <CardContent className="px-4 py-4">
          <Skeleton className="h-6 w-28" />
          <Skeleton className="mt-2.5 h-3 w-64" />
          <Skeleton className="mt-1 h-3 w-48" />
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Skeleton className="h-14 rounded" />
            <Skeleton className="h-14 rounded" />
          </div>
          <Skeleton className="mt-2.5 h-9 rounded" />
        </CardContent>
      </Card>
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2].map((i) => (
          <Card key={i} className="border-border/70">
            <CardContent className="px-3 py-3">
              <Skeleton className="h-2.5 w-14" />
              <Skeleton className="mt-2.5 h-5 w-16" />
              {i === 1 && <Skeleton className="mt-1.5 h-2.5 w-20" />}
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="border-border/70">
        <CardContent className="px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex gap-1.5">
              {CHART_FILTERS.map((f) => <Skeleton key={f.value} className="h-6 w-12 rounded" />)}
            </div>
            <Skeleton className="h-3 w-36" />
          </div>
          <Skeleton className="mt-3 h-[220px] rounded" />
        </CardContent>
      </Card>
      <Card className="border-border/70">
        <CardContent className="px-4 py-4">
          <Skeleton className="h-2.5 w-32" />
          <div className="mt-3 space-y-2">
            <Skeleton className="h-20 rounded" />
            <Skeleton className="h-20 rounded" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

function AnalyticsPageContent() {
  const searchParams = useSearchParams();
  const [chartFilter, setChartFilter] = useState<StatsChartFilter>("all");
  const { openBankrollDrawer } = useBankrollDrawer();
  const selectedBook = searchParams.get("sportsbook") ?? "all";
  const sourceFilter = parseTrackerSourceFilter(searchParams.get("source"));

  const {
    data: bets = [],
    isLoading: betsLoading,
    error: betsError,
  } = useQuery({
    queryKey: ["bets", "stats", "all"],
    queryFn: getAllBetsForStats,
  });

  const {
    data: balances = [],
    isLoading: balancesLoading,
    error: balancesError,
  } = useQuery({
    queryKey: ["balances"],
    queryFn: getBalances,
  });

  const { data: settings } = useQuery({
    queryKey: ["settings", "stats"],
    queryFn: getSettings,
  });

  const filteredBets = useMemo(
    () => bets.filter((bet) => {
      const bookMatch = selectedBook === "all" || bet.sportsbook === selectedBook;
      return bookMatch && matchesTrackerSourceFilter(bet, sourceFilter);
    }),
    [bets, selectedBook, sourceFilter],
  );

  useEffect(() => {
    if (sourceFilter !== "all") {
      setChartFilter(sourceFilter);
    }
  }, [sourceFilter]);

  const model = useMemo(
    () => buildStatsPageModel({ bets: filteredBets, balances, settings, showProcessStatsRow: true }),
    [filteredBets, balances, settings],
  );

  const chartFilterLocked = sourceFilter !== "all";
  const effectiveChartFilter: StatsChartFilter = chartFilterLocked ? sourceFilter : chartFilter;
  const chartPoints = model.chartSeriesByFilter[effectiveChartFilter];
  const finalChartPoint = chartPoints.at(-1);
  const activeChartFilterLabel = CHART_FILTERS.find((filter) => filter.value === effectiveChartFilter)?.label ?? "All";
  const vs = VERDICT_STYLES[model.verdict.state];
  const isLoading = betsLoading || balancesLoading;
  const error = betsError ?? balancesError;

  if (error) {
    return (
      <main className="min-h-screen bg-background">
        <div className="container mx-auto max-w-3xl px-4 py-4">
          <Card className="border-destructive/30 bg-destructive/5">
            <CardContent className="px-4 py-3">
              <p className="text-sm font-semibold text-foreground">Stats could not load right now.</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
            </CardContent>
          </Card>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-3xl px-4 py-4 sm:py-5">
        {isLoading ? (
          <StatsPageSkeleton />
        ) : (
          <div className="space-y-3">

            {/* ── Verdict ──────────────────────────────────────────────
                Left border accent communicates state in dark mode without
                fighting the warm slate surface with a tinted background.
            ─────────────────────────────────────────────────────────── */}
            <Card
              data-testid="verdict-card"
              className={cn("border-border/80 animate-slide-up", vs.leftBorder)}
              style={{ animationFillMode: "both" }}
            >
              <CardContent className="px-4 py-4">
                <p className={cn("text-lg font-bold tracking-wide animate-ink-reveal", vs.label)}
                   style={{ animationDelay: "80ms", animationFillMode: "both" }}>
                  {model.verdict.label}
                </p>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {model.verdict.copy}
                </p>

                <div className="mt-3.5 grid grid-cols-2 gap-2">
                  <MetricTile
                    label="Profit"
                    value={formatSignedCurrency(model.profit)}
                    valueClassName={model.profit >= 0 ? "text-profit" : "text-loss"}
                  />
                  <MetricTile
                    label="EV Earned"
                    value={formatSignedCurrency(model.evEarned)}
                    valueClassName="text-primary"
                  />
                </div>

                {/* Swing row — inline label + value, no extra card nesting */}
                <div className="mt-2.5 flex items-center justify-between border-t border-border/60 pt-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Expected swing at {model.settledBetsCount} bets
                  </p>
                  <p className={cn("font-mono text-sm font-bold tabular-nums", vs.accent)}>
                    {formatSwing(model.normalSwing)}
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* ── Summary strip ─────────────────────────────────────── */}
            <section
              data-testid="summary-cards"
              className="grid grid-cols-3 gap-2 animate-slide-up"
              style={{ animationDelay: "60ms", animationFillMode: "both" }}
            >
              <MetricCard
                label="Bankroll"
                value={model.bankroll === null ? "—" : formatCurrency(model.bankroll)}
                secondary={formatWeeklyChange(model.sevenDayProfitChange)}
                valueClassName={model.bankroll !== null && model.bankroll < 0 ? "text-loss" : "text-foreground"}
                onClick={() => openBankrollDrawer()}
                ariaLabel="Open bankroll details"
                dataTestId="summary-card"
                triggerTestId="bankroll-summary-trigger"
                affordance={
                  <span className="flex items-center gap-0.5 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    Details
                    <ChevronRight className="h-3 w-3" />
                  </span>
                }
              />
              <MetricCard
                label="Bets Logged"
                value={String(model.totalBetsLogged)}
                secondary={`${model.settledBetsCount} settled`}
                valueClassName="text-foreground"
                dataTestId="summary-card"
              />
              <MetricCard
                label="At Risk"
                value={formatCurrency(model.atRisk)}
                secondary={`${formatSignedCurrency(model.pendingEv)} pending EV`}
                valueClassName="text-foreground"
                dataTestId="summary-card"
              />
            </section>

            {/* ── Chart ─────────────────────────────────────────────── */}
            <Card
              className="border-border animate-slide-up"
              style={{ animationDelay: "120ms", animationFillMode: "both" }}
            >
              <CardContent className="px-4 py-4">
                {/* Controls row: pills left, legend right */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex gap-1.5" aria-label="Chart filter pills">
                    {CHART_FILTERS.map((filter) => (
                      <ChartFilterPill
                        key={filter.value}
                        active={effectiveChartFilter === filter.value}
                        label={filter.label}
                        disabled={chartFilterLocked}
                        onClick={() => setChartFilter(filter.value)}
                      />
                    ))}
                  </div>
                  <ChartLegend />
                </div>

                {chartFilterLocked && (
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    Chart filter is set by Source: {getTrackerSourceLabel(sourceFilter)}
                  </p>
                )}

                <p className="mt-2 text-[11px] text-muted-foreground">
                  Cumulative all-time · shaded band = normal variance
                </p>

                <div
                  key={effectiveChartFilter}
                  data-testid="stats-chart"
                  data-chart-filter={effectiveChartFilter}
                  data-point-count={chartPoints.length}
                  data-final-profit={finalChartPoint?.cumulativeProfit.toFixed(2) ?? "0.00"}
                  data-final-ev={finalChartPoint?.cumulativeEv.toFixed(2) ?? "0.00"}
                  className="mt-3 animate-fade-in"
                >
                  {chartPoints.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <ComposedChart data={chartPoints} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                        <CartesianGrid
                          strokeDasharray="3 4"
                          stroke="hsl(var(--border))"
                          strokeOpacity={0.45}
                          vertical={false}
                        />
                        <XAxis
                          dataKey="dateLabel"
                          stroke="hsl(var(--muted-foreground))"
                          fontSize={11}
                          tickLine={false}
                          axisLine={false}
                          interval="preserveStartEnd"
                          minTickGap={32}
                          dy={4}
                        />
                        <YAxis
                          stroke="hsl(var(--muted-foreground))"
                          fontSize={11}
                          tickFormatter={(v: number) => formatCurrency(v)}
                          tickLine={false}
                          axisLine={false}
                          width={58}
                        />
                        <Tooltip
                          content={<StatsChartTooltip />}
                          cursor={{ stroke: "hsl(var(--border))", strokeWidth: 1, strokeDasharray: "4 3" }}
                        />
                        {/* Variance band — keep isAnimationActive=false, stacked areas
                            animate from zero height which looks broken with this technique */}
                        <Area
                          type="monotone"
                          dataKey="bandBase"
                          stackId="vb"
                          stroke="none"
                          fill="transparent"
                          isAnimationActive={false}
                        />
                        <Area
                          type="monotone"
                          dataKey="bandSize"
                          stackId="vb"
                          stroke={CHART_THEME.varianceStroke}
                          strokeWidth={1}
                          fill={CHART_THEME.varianceFill}
                          fillOpacity={1}
                          isAnimationActive={false}
                        />
                        {/* Lines animate on — draws left-to-right like a pen tracing the data */}
                        <Line
                          type="monotone"
                          dataKey="cumulativeEv"
                          stroke={CHART_THEME.evStroke}
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={true}
                          animationDuration={600}
                          animationEasing="ease-out"
                        />
                        <Line
                          type="monotone"
                          dataKey="cumulativeProfit"
                          stroke={CHART_THEME.profitStroke}
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={true}
                          animationDuration={600}
                          animationEasing="ease-out"
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-[220px] items-center justify-center rounded border border-dashed border-border/50 bg-muted/15 px-6 text-center">
                      <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">
                        {effectiveChartFilter === "all"
                          ? "Settle a few bets and this chart will compare your cumulative EV with your actual results."
                          : `No settled ${activeChartFilterLabel.toLowerCase()} yet.`}
                      </p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* ── Source breakdown ──────────────────────────────────── */}
            <Card
              data-testid="source-breakdown"
              className="border-border animate-slide-up"
              style={{ animationDelay: "180ms", animationFillMode: "both" }}
            >
              <CardContent className="px-4 py-4">
                <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
                  Where it came from
                </p>
                <div className="mt-3 space-y-2">
                  {sourceFilter !== "promos" && (
                    <SourceBreakdownRow
                      label="Core Bets"
                      ev={model.sourceBreakdown.core.ev}
                      profit={model.sourceBreakdown.core.profit}
                      dotClass="bg-primary"
                      href={`/bets?${buildTrackerViewQuery({ tab: "history", source: "core", sportsbook: selectedBook, search: "" })}`}
                    />
                  )}
                  {sourceFilter !== "core" && (
                    <SourceBreakdownRow
                      label="Promos"
                      ev={model.sourceBreakdown.promos.ev}
                      profit={model.sourceBreakdown.promos.profit}
                      dotClass="bg-profit"
                      href={`/bets?${buildTrackerViewQuery({ tab: "history", source: "promos", sportsbook: selectedBook, search: "" })}`}
                    />
                  )}
                </div>
              </CardContent>
            </Card>

            {/* ── Advanced details collapse ─────────────────────────── */}
            {model.showProcessStatsRow ? (
              <details
                data-testid="process-stats"
                className="group rounded-md border border-border bg-card animate-slide-up"
                style={{ animationDelay: "220ms", animationFillMode: "both" }}
              >
                <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-4 select-none rounded-md transition-colors hover:bg-muted/20 active:bg-muted/30 active:scale-[0.99]">
                  <div>
                    <span className="text-sm font-semibold text-foreground">Process Stats</span>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">Advanced betting metrics</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground group-open:hidden">
                      Show
                    </span>
                    <span className="hidden rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground group-open:inline">
                      Hide
                    </span>
                    <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform duration-200 group-open:rotate-90" />
                  </div>
                </summary>
                <div className="border-t border-border/60 px-4 py-2">
                  <div className="divide-y divide-border/40">
                    <ProcessStatRow
                      label="Beat Close"
                      subtitle="How often your price beat the market close"
                      value={formatPercent(model.processStats.beatClosePct)}
                    />
                    <ProcessStatRow
                      label="Avg CLV"
                      subtitle="How much better your prices were than close, on average"
                      value={formatPercent(model.processStats.avgClvPct)}
                    />
                    <ProcessStatRow
                      label="Close Coverage"
                      subtitle="How many bets had valid close data"
                      value={`${model.processStats.validCloseCount} / ${model.processStats.trackedCloseCount} tracked`}
                      secondaryValue={formatCoverage(model.processStats.closeCoveragePct)}
                    />
                    <ProcessStatRow
                      label="Avg Edge"
                      subtitle="Average expected edge on your logged core bets"
                      value={formatPercent(model.processStats.avgEdgePct)}
                    />
                    <ProcessStatRow
                      label="Win Rate"
                      subtitle={
                        model.processStats.winRateSampleCount > 0
                          ? `${model.processStats.winRateSampleCount} tracked`
                          : "No tracked sample yet"
                      }
                      value={
                        model.processStats.expectedWinRatePct === null
                          ? "-"
                          : formatPercent(model.processStats.actualWinRatePct)
                      }
                      secondaryValue={
                        model.processStats.expectedWinRatePct === null
                          ? null
                          : `Expected ${formatPercent(model.processStats.expectedWinRatePct)}`
                      }
                    />
                  </div>
                </div>
              </details>
            ) : null}

          </div>
        )}
      </div>

    </main>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-background">
          <div className="container mx-auto max-w-3xl px-4 py-4 sm:py-5">
            <StatsPageSkeleton />
          </div>
        </main>
      }
    >
      <AnalyticsPageContent />
    </Suspense>
  );
}
