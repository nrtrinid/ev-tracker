"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
} from "@/components/ui/sheet";
import { cn, formatCurrency, formatPercent, formatOdds } from "@/lib/utils";
import { 
  TrendingUp, 
  TrendingDown, 
  Trophy, 
  Target, 
  DollarSign,
  BarChart3,
  Activity,
  X,
  SlidersHorizontal,
  Info
} from "lucide-react";
import { TopKpiCards } from "@/components/TopKpiCards";
import { useQuery } from "@tanstack/react-query";
import { getBets, getSummary, getBalances } from "@/lib/api";
import { useBackendReadiness } from "@/lib/hooks";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  Tooltip, 
  ResponsiveContainer,
  Cell,
  LineChart,
  Line,
  CartesianGrid,
  ComposedChart
} from "recharts";
import type { Bet } from "@/lib/types";

// Filter options
const TIMEFRAME_OPTIONS = ["All Time", "YTD", "Last 30 Days", "Last 7 Days"] as const;
const BET_TYPE_OPTIONS = ["All Types", "Bonus Bets", "Boosts", "Standard"] as const;
const SPORT_OPTIONS = ["All Sports", "NFL", "NBA", "MLB", "NHL", "NCAAF", "NCAAB", "Soccer", "Tennis", "UFC"] as const;

type TimeframeOption = typeof TIMEFRAME_OPTIONS[number];
type BetTypeOption = typeof BET_TYPE_OPTIONS[number];
type SportOption = typeof SPORT_OPTIONS[number];
type SportsbookOption = "All Books" | string;

// Filter Pill component
function FilterPill({ 
  label, 
  active, 
  onClick 
}: { 
  label: string; 
  active: boolean; 
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0",
        active 
          ? "bg-foreground text-background shadow-sm" 
          : "bg-muted text-muted-foreground hover:bg-secondary"
      )}
    >
      {label}
    </button>
  );
}

// Filter bar component
function AnalyticsFilterBar({
  timeframe,
  setTimeframe,
  betType,
  setBetType,
  sport,
  setSport,
  sportsbook,
  setSportsbook,
  sportsbookOptions,
  hasActiveFilters,
  onClearFilters,
}: {
  timeframe: TimeframeOption;
  setTimeframe: (v: TimeframeOption) => void;
  betType: BetTypeOption;
  setBetType: (v: BetTypeOption) => void;
  sport: SportOption;
  setSport: (v: SportOption) => void;
  sportsbook: SportsbookOption;
  setSportsbook: (v: SportsbookOption) => void;
  sportsbookOptions: string[];
  hasActiveFilters: boolean;
  onClearFilters: () => void;
}) {
  return (
    <div className="space-y-4">
      {/* Timeframe - Horizontal Scroll */}
      <div>
        <span className="text-xs text-muted-foreground font-medium block mb-2">Time</span>
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
          {TIMEFRAME_OPTIONS.map((option) => (
            <FilterPill
              key={option}
              label={option}
              active={timeframe === option}
              onClick={() => setTimeframe(option)}
            />
          ))}
        </div>
      </div>
      
      {/* Sportsbook - Horizontal Scroll */}
      <div>
        <span className="text-xs text-muted-foreground font-medium block mb-2">Book</span>
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
          <FilterPill
            label="All Books"
            active={sportsbook === "All Books"}
            onClick={() => setSportsbook("All Books")}
          />
          {sportsbookOptions.map((option) => (
            <FilterPill
              key={option}
              label={option}
              active={sportsbook === option}
              onClick={() => setSportsbook(option)}
            />
          ))}
        </div>
      </div>
      
      {/* Bet Type - Horizontal Scroll */}
      <div>
        <span className="text-xs text-muted-foreground font-medium block mb-2">Type</span>
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
          {BET_TYPE_OPTIONS.map((option) => (
            <FilterPill
              key={option}
              label={option}
              active={betType === option}
              onClick={() => setBetType(option)}
            />
          ))}
        </div>
      </div>
      
      {/* Sport - Horizontal Scroll */}
      <div>
        <span className="text-xs text-muted-foreground font-medium block mb-2">Sport</span>
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
          {SPORT_OPTIONS.map((option) => (
            <FilterPill
              key={option}
              label={option}
              active={sport === option}
              onClick={() => setSport(option)}
            />
          ))}
        </div>
      </div>

      {/* Clear filters */}
      {hasActiveFilters && (
        <button
          onClick={onClearFilters}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="h-3 w-3" />
          Clear filters
        </button>
      )}
    </div>
  );
}

// Sportsbook colors for charts (authentic brand colors)
const SPORTSBOOK_COLORS: Record<string, string> = {
  DraftKings: "#4CBB17",
  FanDuel: "#0E7ACA",
  BetMGM: "#C5A562",
  Caesars: "#C49A6C",
  "ESPN Bet": "#ED174C",
  Fanatics: "#0047BB",
  "Hard Rock": "#FDB913",
  bet365: "#00843D",
};

const CHART_COLORS = ["#4A7C59", "#C4A35A", "#6B5E4F", "#B85C38", "#8B7355", "#7A9E7E", "#D4C4A8", "#9B8A7B"];

// Promo type chart colors (distinct hues for readability)
// Note: Chart palette intentionally diverges from tag colors for better differentiation.
const PROMO_TYPE_CHART_COLORS: Record<string, string> = {
  "Bonus Bet": "#7A9E7E",
  "Boosts": "#C4A35A",
  "30% Boost": "#C4A35A",
  "50% Boost": "#B8963E",
  "100% Boost": "#8B7355",
  "Custom Boost": "#D4C4A8",
  "No Sweat": "#4A7C59",
  "Promo Qualifier": "#B85C38",
  "Standard": "#6B5E4F",
};

export default function AnalyticsPage() {
  // Filter state
  const [timeframe, setTimeframe] = useState<TimeframeOption>("All Time");
  const [betType, setBetType] = useState<BetTypeOption>("All Types");
  const [sport, setSport] = useState<SportOption>("All Sports");
  const [sportsbook, setSportsbook] = useState<SportsbookOption>("All Books");
  const [filterOpen, setFilterOpen] = useState(false);
  const [breakdownTab, setBreakdownTab] = useState<"book" | "sport" | "type">("book");
  const [bookMetric, setBookMetric] = useState<"ev" | "profit">("ev");

  const activeFilterCount = [
    timeframe !== "All Time",
    betType !== "All Types",
    sport !== "All Sports",
    sportsbook !== "All Books",
  ].filter(Boolean).length;

  const hasActiveFilters = activeFilterCount > 0;

  const clearFilters = () => {
    setTimeframe("All Time");
    setBetType("All Types");
    setSport("All Sports");
    setSportsbook("All Books");
  };

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["summary"],
    queryFn: getSummary,
  });

  const { data: bets, isLoading: betsLoading } = useQuery({
    queryKey: ["bets"],
    queryFn: () => getBets(),
  });

  const { data: balances, isLoading: balancesLoading } = useQuery({
    queryKey: ["balances"],
    queryFn: getBalances,
  });
  const { data: readiness } = useBackendReadiness();

  const isLoading = summaryLoading || betsLoading;
  const showAnalyticsHint = !!readiness && (readiness.status !== "ready" || !readiness.checks.scheduler_freshness);

  // Get unique sportsbooks for filter options
  const sportsbookOptions = useMemo(() => {
    if (!bets) return [];
    return Array.from(new Set(bets.map(b => b.sportsbook))).sort();
  }, [bets]);

  // Apply filters to bets
  const filteredBets = useMemo(() => {
    if (!bets) return [];
    
    return bets.filter(bet => {
      // Timeframe filter
      const betDate = new Date(bet.created_at);
      const now = new Date();
      let dateMatch = true;
      
      if (timeframe === "Last 7 Days") {
        const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        dateMatch = betDate >= weekAgo;
      } else if (timeframe === "Last 30 Days") {
        const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        dateMatch = betDate >= monthAgo;
      } else if (timeframe === "YTD") {
        const startOfYear = new Date(now.getFullYear(), 0, 1);
        dateMatch = betDate >= startOfYear;
      }
      
      // Sportsbook filter
      const bookMatch = sportsbook === "All Books" || bet.sportsbook === sportsbook;
      
      // Bet type filter
      let typeMatch = true;
      if (betType === "Bonus Bets") {
        typeMatch = bet.promo_type === "bonus_bet";
      } else if (betType === "Boosts") {
        typeMatch = bet.promo_type.startsWith("boost");
      } else if (betType === "Standard") {
        typeMatch = bet.promo_type === "standard" || bet.promo_type === "no_sweat" || bet.promo_type === "promo_qualifier";
      }
      
      // Sport filter
      const sportMatch = sport === "All Sports" || bet.sport === sport;
      
      return dateMatch && bookMatch && typeMatch && sportMatch;
    });
  }, [bets, timeframe, sportsbook, betType, sport]);

  // Calculate metrics from filtered bets
  const settledBets = filteredBets.filter(b => b.result !== "pending");
  const pendingBets = filteredBets.filter(b => b.result === "pending");
  
  // Total stake risked (settled bets only for ROI calc)
  const totalSettledStake = settledBets.reduce((sum, b) => sum + b.stake, 0);
  const totalPendingStake = pendingBets.reduce((sum, b) => sum + b.stake, 0);
  
  // Pending EV
  const pendingEV = pendingBets.reduce((sum, b) => sum + b.ev_total, 0);
  const settledEV = settledBets.reduce((sum, b) => sum + b.ev_total, 0);
  
  // Z-Score Calculation
  // Z = (Real Profit - Total EV) / Standard Deviation
  // Standard deviation estimated from stake variance
  const totalVariance = settledBets.reduce((sum, b) => {
    // Variance per bet ≈ stake² × (decimal_odds) for simplified calculation
    // More accurate: stake² × p × (1-p) × (odds-1)² where p = 1/odds
    const p = 1 / b.odds_decimal;
    const betVariance = (b.stake ** 2) * p * (1 - p) * ((b.odds_decimal - 1) ** 2 + 1);
    return sum + betVariance;
  }, 0);
  const standardDeviation = Math.sqrt(totalVariance);
  const settledProfit = settledBets.reduce((sum, b) => sum + (b.real_profit || 0), 0);
  // Z-score only becomes meaningful with a small sample (>= 2 settled bets).
  // With 0-1 bets the UI should keep the "need more data" message.
  const zScore =
    settledBets.length <= 1
      ? null
      : standardDeviation > 0
        ? (settledProfit - settledEV) / standardDeviation
        : null;
  
  // Calculate filtered totals
  const filteredTotalEV = filteredBets.reduce((sum, b) => sum + b.ev_total, 0);
  const filteredRealProfit = settledBets.reduce((sum, b) => sum + (b.real_profit || 0), 0);
  
  // EV Conversion (Real Profit / Settled EV)
  const evConversion = settledEV > 0 ? (filteredRealProfit / settledEV) : null;
  
  // ROI based on settled cash
  const settledROI = totalSettledStake > 0 ? (filteredRealProfit / totalSettledStake) : null;
  
  // Fun Metrics Calculations
  // Biggest Win
  const biggestWin = settledBets
    .filter(b => b.real_profit !== null && b.real_profit > 0)
    .reduce((max, b) => (b.real_profit! > (max?.real_profit || 0)) ? b : max, null as Bet | null);
  
  // Win Rate
  const wins = settledBets.filter(b => b.result === "win").length;
  const totalSettled = settledBets.length;
  const actualWinRate = totalSettled > 0 ? (wins / totalSettled) * 100 : null;
  const expectedWinRate = totalSettled > 0 
    ? (settledBets.reduce((sum, b) => sum + (1 / b.odds_decimal), 0) / totalSettled) * 100
    : null;
  
  // Profit Factor
  const grossWinnings = settledBets
    .filter(b => b.result === "win" && b.real_profit !== null)
    .reduce((sum, b) => sum + (b.real_profit || 0), 0);
  const grossLosses = settledBets
    .filter(b => b.result === "loss")
    .reduce((sum, b) => sum + b.stake, 0);
  const profitFactor = grossLosses > 0 ? grossWinnings / grossLosses : null;
  
  // Bonus Efficiency
  const bonusBets = settledBets.filter(b => b.promo_type === "bonus_bet");
  const bonusStaked = bonusBets.reduce((sum, b) => sum + b.stake, 0);
  const bonusReturns = bonusBets
    .filter(b => b.result === "win")
    .reduce((sum, b) => sum + b.win_payout, 0);
  const bonusEfficiency = bonusStaked > 0 ? (bonusReturns / bonusStaked) * 100 : null;

  // CLV Analytics — standard bets only. Promos (bonus bets, boosts, qualifiers) optimize
  // for retention/boost value, not for beating the closing line, so including them would
  // pollute the signal.
  const standardBets = filteredBets.filter(b => b.promo_type === "standard");
  const clvBets = standardBets.filter(b => b.clv_ev_percent !== null);
  const clvTrackedCount = standardBets.filter(b => b.pinnacle_odds_at_entry !== null).length;
  const beatCloseCount = clvBets.filter(b => b.beat_close === true).length;
  const beatClosePct = clvBets.length > 0 ? (beatCloseCount / clvBets.length) * 100 : null;
  const avgCLV = clvBets.length > 0
    ? clvBets.reduce((sum, b) => sum + (b.clv_ev_percent ?? 0), 0) / clvBets.length
    : null;
  const settledStandardCount = standardBets.filter((b) => b.result !== "pending").length;

  // Active bets (cash exposure + potential profit)
  const pendingCashStake = pendingBets.filter((b) => b.promo_type !== "bonus_bet").reduce((sum, b) => sum + b.stake, 0);
  const pendingPotentialProfit = pendingBets.reduce((sum, b) => {
    const profitIfWin = b.promo_type === "bonus_bet" ? b.win_payout : (b.win_payout - b.stake);
    return sum + profitIfWin;
  }, 0);

  const performanceLabel = useMemo(() => {
    if (zScore === null) return "Need more data";
    if (zScore >= 0.5) return "Above Expected";
    if (zScore <= -0.5) return "Below Expected";
    return "On Track";
  }, [zScore]);

  const performanceSubtext = useMemo(() => {
    if (zScore === null) return "Settle a couple bets to see how results compare to EV.";
    const diff = settledProfit - settledEV;
    const abs = Math.abs(diff);
    const dir = diff >= 0 ? "up" : "down";
    return `Currently ${dir} ${formatCurrency(abs)} vs what EV predicted. Short-term swings are normal.`;
  }, [zScore, settledProfit, settledEV]);

  // Prepare chart data from FILTERED bets
  const sportsbookChartData = useMemo(() => {
    const evBySportsbook: Record<string, number> = {};
    const profitBySportsbook: Record<string, number> = {};
    
    filteredBets.forEach(bet => {
      evBySportsbook[bet.sportsbook] = (evBySportsbook[bet.sportsbook] || 0) + bet.ev_total;
      if (bet.result !== "pending" && bet.real_profit !== null) {
        profitBySportsbook[bet.sportsbook] = (profitBySportsbook[bet.sportsbook] || 0) + bet.real_profit;
      }
    });
    
    return Object.entries(evBySportsbook)
      .map(([name, ev]) => ({
        name: name.replace("ESPN Bet", "ESPN").replace("Hard Rock", "HR"),
        ev,
        profit: profitBySportsbook[name] || 0,
        color: SPORTSBOOK_COLORS[name] || "#888",
      }))
      .sort((a, b) => b.ev - a.ev);
  }, [filteredBets]);

  const sportChartData = useMemo(() => {
    const evBySport: Record<string, number> = {};
    filteredBets.forEach(bet => {
      evBySport[bet.sport] = (evBySport[bet.sport] || 0) + bet.ev_total;
    });
    const totalEV = Object.values(evBySport).reduce((sum, v) => sum + Math.abs(v), 0);
    if (totalEV === 0) return [];

    const THRESHOLD = 0.05; // sports below 5% of total EV go into "Other"
    const bars: Array<{ name: string; ev: number; color: string }> = [];
    let otherEV = 0;

    Object.entries(evBySport)
      .sort(([, a], [, b]) => b - a)
      .forEach(([name, ev]) => {
        const share = Math.abs(ev) / totalEV;
        if (share >= THRESHOLD) {
          bars.push({
            name,
            ev,
            color: CHART_COLORS[bars.length % CHART_COLORS.length],
          });
        } else {
          otherEV += ev;
        }
      });

    if (otherEV !== 0) {
      bars.push({
        name: "Other",
        ev: otherEV,
        color: "#A8A29E",
      });
    }

    return bars.sort((a, b) => b.ev - a.ev);
  }, [filteredBets]);

  // Bets by promo type — boost subtypes are merged into one "Boosts" bar for chart clarity
  const promoTypeData = useMemo(() => {
    const counts: Record<string, number> = {};
    filteredBets.forEach(bet => {
      const label = bet.promo_type.startsWith("boost_") ? "Boosts" : formatPromoType(bet.promo_type);
      counts[label] = (counts[label] || 0) + 1;
    });
    return Object.entries(counts)
      .map(([name, value]) => ({
        name,
        value,
        color: PROMO_TYPE_CHART_COLORS[name] || CHART_COLORS[0],
      }))
      .sort((a, b) => b.value - a.value);
  }, [filteredBets]);

  // Cumulative EV vs Real Profit over time (by date)
  const cumulativeData = settledBets.length > 0
    ? settledBets
        .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
        .reduce((acc, bet) => {
          const betDate = new Date(bet.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
          const lastEntry = acc.length > 0 ? acc[acc.length - 1] : null;
          
          const newEV = (lastEntry?.cumulativeEV || 0) + bet.ev_total;
          const newProfit = (lastEntry?.cumulativeProfit || 0) + (bet.real_profit || 0);
          
          // Always add a new point (don't try to group by date)
          acc.push({
            date: betDate,
            cumulativeEV: newEV,
            cumulativeProfit: newProfit,
            variance: newProfit - newEV,
          });
          
          return acc;
        }, [] as Array<{ date: string; cumulativeEV: number; cumulativeProfit: number; variance: number }>)
    : [];

  const totalBalance =
    balances && balances.length > 0 ? balances.reduce((sum, b) => sum + (b.balance || 0), 0) : null;

  const bestSource = useMemo(() => {
    if (!filteredBets || filteredBets.length === 0) return null;
    const evByBook: Record<string, number> = {};
    const evBySport: Record<string, number> = {};
    filteredBets.forEach((b) => {
      evByBook[b.sportsbook] = (evByBook[b.sportsbook] || 0) + b.ev_total;
      evBySport[b.sport] = (evBySport[b.sport] || 0) + b.ev_total;
    });
    const bestBook = Object.entries(evByBook).sort((a, b) => b[1] - a[1])[0];
    if (bestBook) return { label: bestBook[0], value: bestBook[1], type: "book" as const };
    const bestSport = Object.entries(evBySport).sort((a, b) => b[1] - a[1])[0];
    return bestSport ? { label: bestSport[0], value: bestSport[1], type: "sport" as const } : null;
  }, [filteredBets]);

  const bestDay = useMemo(() => {
    if (!settledBets || settledBets.length === 0) return null;
    const byDay: Record<string, number> = {};
    settledBets.forEach((b) => {
      const dateKey = new Date(b.settled_at ?? b.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" });
      byDay[dateKey] = (byDay[dateKey] || 0) + (b.real_profit || 0);
    });
    const best = Object.entries(byDay).sort((a, b) => b[1] - a[1])[0];
    if (!best) return null;
    return { label: best[0], profit: best[1] };
  }, [settledBets]);

  return (
    <main className="min-h-screen bg-background">
      {/* Sticky Filter Bar - Positioned below TopNav (56px) */}
      <div className="sticky top-14 z-10 w-full py-3 bg-[#FAF8F5] border-b border-border shadow-sm">
        <div className="container mx-auto px-4 max-w-4xl">
          <div className="flex justify-between items-center">
            <h1 className="text-lg font-semibold">Analytics</h1>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setFilterOpen(true)}
              className={cn(
                "gap-2",
                hasActiveFilters && "border-foreground bg-foreground/5"
              )}
            >
              <SlidersHorizontal className="h-4 w-4" />
              <span className="hidden sm:inline">Filter</span>
              {hasActiveFilters && (
                <span className="bg-foreground text-background text-xs font-semibold px-1.5 py-0.5 rounded-full">
                  {activeFilterCount}
                </span>
              )}
            </Button>
          </div>
        </div>
      </div>
      
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-4xl">
        {showAnalyticsHint && (
          <div className="inline-flex items-center gap-1.5 rounded-md border border-[#C4A35A]/35 bg-[#C4A35A]/15 px-2.5 py-1.5 text-xs text-[#5C4D2E]">
            <Info className="h-3.5 w-3.5" />
            Recent analytics may be incomplete while data finishes syncing.
          </div>
        )}
        {isLoading ? (
          <div className="space-y-6">
            {/* Z-Score Hero Card Skeleton */}
            <Card>
              <CardContent className="pt-6 pb-4">
                <div className="text-center space-y-2">
                  <Skeleton className="h-4 w-32 mx-auto" />
                  <Skeleton className="h-7 w-40 mx-auto" />
                  <Skeleton className="h-4 w-48 mx-auto" />
                </div>
              </CardContent>
            </Card>

            {/* Summary Cards Skeleton */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[1, 2, 3, 4].map((i) => (
                <Card key={i}>
                  <CardContent className="p-4">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Skeleton className="h-3.5 w-3.5 rounded" />
                      <Skeleton className="h-3 w-16" />
                    </div>
                    <Skeleton className="h-7 w-20" />
                  </CardContent>
                </Card>
              ))}
            </div>
            
            {/* Chart Skeletons */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card>
                <CardHeader className="pb-2">
                  <Skeleton className="h-5 w-32" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-[200px] w-full rounded" />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <Skeleton className="h-5 w-28" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-[200px] w-full rounded" />
                </CardContent>
              </Card>
            </div>
            
            {/* Line Chart Skeleton */}
            <Card>
              <CardHeader className="pb-2">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-3 w-56 mt-1" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-[200px] w-full rounded" />
              </CardContent>
            </Card>
          </div>
        ) : (
          <>

            {/* Filter Sheet (Drawer) */}
            <Sheet open={filterOpen} onOpenChange={setFilterOpen}>
              <SheetContent side="bottom" className="p-6">
                <SheetHeader className="p-0 pb-4">
                  <SheetTitle>Filter Analytics</SheetTitle>
                </SheetHeader>
                <AnalyticsFilterBar
                  timeframe={timeframe}
                  setTimeframe={setTimeframe}
                  betType={betType}
                  setBetType={setBetType}
                  sport={sport}
                  setSport={setSport}
                  sportsbook={sportsbook}
                  setSportsbook={setSportsbook}
                  sportsbookOptions={sportsbookOptions}
                  hasActiveFilters={hasActiveFilters}
                  onClearFilters={clearFilters}
                />
                <div className="flex gap-3 pt-6">
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={clearFilters}
                    disabled={!hasActiveFilters}
                  >
                    Clear All
                  </Button>
                  <SheetClose asChild>
                    <Button className="flex-1">
                      Apply Filters
                    </Button>
                  </SheetClose>
                </div>
              </SheetContent>
            </Sheet>

            {/* Active Filters Summary (optional inline indicator) */}
            {hasActiveFilters && (
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs text-muted-foreground">Showing:</span>
                {timeframe !== "All Time" && (
                  <span className="px-2 py-1 bg-muted rounded-full text-xs font-medium">{timeframe}</span>
                )}
                {betType !== "All Types" && (
                  <span className="px-2 py-1 bg-muted rounded-full text-xs font-medium">{betType}</span>
                )}
                {sport !== "All Sports" && (
                  <span className="px-2 py-1 bg-muted rounded-full text-xs font-medium">{sport}</span>
                )}
                {sportsbook !== "All Books" && (
                  <span className="px-2 py-1 bg-muted rounded-full text-xs font-medium">{sportsbook}</span>
                )}
                <button
                  onClick={clearFilters}
                  className="text-xs text-muted-foreground hover:text-foreground underline"
                >
                  Clear
                </button>
              </div>
            )}

            {/* OVERVIEW */}
            <Card className={cn(
              "border card-hover",
              zScore === null ? "border-border" :
              zScore >= 1.5 ? "border-[#4A7C59]/50 bg-[#4A7C59]/10" :
              zScore >= 0.5 ? "border-[#4A7C59]/30 bg-[#4A7C59]/5" :
              zScore >= -0.5 ? "border-[#C4A35A]/30 bg-[#C4A35A]/5" :
              zScore >= -1.5 ? "border-[#B85C38]/30 bg-[#B85C38]/5" :
              "border-[#B85C38]/50 bg-[#B85C38]/10"
            )}>
              <CardContent className="pt-6 pb-4">
                <div className="text-center">
                  <div className="flex items-center justify-center gap-1.5 mb-2">
                    <p className="text-sm text-muted-foreground uppercase tracking-wide">Overview</p>
                    <span
                      title="Z-Score measures how much your actual profit deviates from expected EV. Positive = outrunning variance (running hot). Negative = underrunning variance (running cold). Values between -1 and +1 are normal luck variance."
                      className="inline-flex"
                    >
                      <Info
                        className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0"
                        aria-label="Z-Score explanation"
                      />
                    </span>
                  </div>
                  <div>
                    <p className={cn(
                      "text-2xl font-bold",
                      zScore === null ? "text-muted-foreground" :
                      zScore >= 0.5 ? "text-[#4A7C59]" :
                      zScore >= -0.5 ? "text-[#C4A35A]" :
                      "text-[#B85C38]"
                    )}>
                      {performanceLabel}
                    </p>
                    <p className="text-sm text-muted-foreground mt-1">{performanceSubtext}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Top KPIs (matches Home) */}
            <TopKpiCards
              netProfit={filteredRealProfit}
              expectedProfit={settledEV}
              totalBalance={totalBalance}
              beatClose={{ beatClosePct, avgClvPct: avgCLV, trackedCount: clvBets.length }}
            />

            {/* HOW YOU’RE TRACKING */}
            {cumulativeData.length > 1 && (
              <Card className="card-hover">
                <CardHeader className="pb-2">
                  <h2 className="font-semibold">How You’re Tracking</h2>
                  <p className="text-xs text-muted-foreground">EV is what your results should average over time. Profit will swing above/below it.</p>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={200} className="md:!h-[250px]">
                    <ComposedChart data={cumulativeData} margin={{ left: 0, right: 10, top: 5, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis 
                        dataKey="date" 
                        fontSize={10} 
                        angle={0}
                        textAnchor="middle" 
                        height={30}
                        interval="preserveStartEnd"
                        tickCount={5}
                        stroke="hsl(var(--muted-foreground))"
                      />
                      <YAxis 
                        tickFormatter={(v) => `$${v}`} 
                        fontSize={11} 
                        stroke="hsl(var(--muted-foreground))"
                        width={45}
                      />
                      <Tooltip 
                        formatter={(value: number, name: string) => [
                          formatCurrency(value),
                          name
                        ]}
                        labelFormatter={(label) => label}
                      />
                      <Line type="monotone" dataKey="cumulativeEV" stroke="#C4A35A" strokeWidth={2} dot={false} name="EV (Expected)" />
                      <Line type="monotone" dataKey="cumulativeProfit" stroke="#4A7C59" strokeWidth={2} dot={false} name="Profit (Actual)" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}

            {/* ACTIVE BETS */}
            <Card>
              <CardHeader className="pb-2">
                <h3 className="font-semibold text-sm">Active Bets</h3>
                <p className="text-xs text-muted-foreground">What you have riding right now.</p>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-3 mb-4">
                  <div className="rounded-lg bg-muted p-3 text-center">
                    <p className="text-xs text-muted-foreground">At Risk</p>
                    <p className="text-lg font-bold font-mono text-foreground">{formatCurrency(pendingCashStake)}</p>
                  </div>
                  <div className="rounded-lg bg-muted p-3 text-center">
                    <p className="text-xs text-muted-foreground">To Win</p>
                    <p className="text-lg font-bold font-mono text-foreground">{formatCurrency(pendingPotentialProfit)}</p>
                  </div>
                  <div className="rounded-lg bg-muted p-3 text-center">
                    <p className="text-xs text-muted-foreground">Open Bets</p>
                    <p className="text-lg font-bold font-mono text-foreground">{pendingBets.length}</p>
                  </div>
                </div>

                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium">Sportsbook Balances</p>
                  <p className="text-xs text-muted-foreground">cash available by book</p>
                </div>
                {balancesLoading ? (
                  <Skeleton className="h-24 w-full rounded" />
                ) : balances && balances.length > 0 ? (
                  <div className="overflow-x-auto -mx-4 px-4">
                    <table className="w-full min-w-[560px] text-sm">
                      <thead>
                        <tr className="border-b text-xs text-muted-foreground">
                          <th className="text-left py-1.5 sm:py-2 font-medium whitespace-nowrap">Book</th>
                          <th className="text-right py-1.5 sm:py-2 font-medium whitespace-nowrap">Deposits</th>
                          <th className="text-right py-1.5 sm:py-2 font-medium whitespace-nowrap">Withdrawals</th>
                          <th className="text-right py-1.5 sm:py-2 font-medium whitespace-nowrap">Profit</th>
                          <th className="text-right py-1.5 sm:py-2 font-medium whitespace-nowrap">Pending</th>
                          <th className="text-right py-1.5 sm:py-2 font-medium whitespace-nowrap">Balance</th>
                        </tr>
                      </thead>
                      <tbody>
                        {balances.map((b) => (
                          <tr key={b.sportsbook} className="border-b border-border hover:bg-muted/50">
                            <td className="py-1.5 sm:py-2 font-medium whitespace-nowrap">{b.sportsbook}</td>
                            <td className="text-right py-1.5 sm:py-2 text-[#4A7C59] font-medium whitespace-nowrap">{formatCurrency(b.deposits)}</td>
                            <td className="text-right py-1.5 sm:py-2 text-[#B85C38] font-medium whitespace-nowrap">{formatCurrency(b.withdrawals)}</td>
                            <td className={cn("text-right py-1.5 sm:py-2 whitespace-nowrap", b.profit >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
                              {formatCurrency(b.profit)}
                            </td>
                            <td className="text-right py-1.5 sm:py-2 text-muted-foreground whitespace-nowrap">{formatCurrency(b.pending)}</td>
                            <td className={cn("text-right py-1.5 sm:py-2 font-semibold whitespace-nowrap", b.balance >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
                              {formatCurrency(b.balance)}
                            </td>
                          </tr>
                        ))}
                        <tr className="bg-muted/50 font-semibold">
                          <td className="py-1.5 sm:py-2 whitespace-nowrap">Total</td>
                          <td className="text-right py-1.5 sm:py-2 text-[#4A7C59] font-semibold whitespace-nowrap">
                            {formatCurrency(balances.reduce((sum, b) => sum + b.deposits, 0))}
                          </td>
                          <td className="text-right py-1.5 sm:py-2 text-[#B85C38] font-semibold whitespace-nowrap">
                            {formatCurrency(balances.reduce((sum, b) => sum + b.withdrawals, 0))}
                          </td>
                          <td className={cn("text-right py-1.5 sm:py-2 whitespace-nowrap", balances.reduce((sum, b) => sum + b.profit, 0) >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
                            {formatCurrency(balances.reduce((sum, b) => sum + b.profit, 0))}
                          </td>
                          <td className="text-right py-1.5 sm:py-2 text-muted-foreground whitespace-nowrap">
                            {formatCurrency(balances.reduce((sum, b) => sum + b.pending, 0))}
                          </td>
                          <td className={cn("text-right py-1.5 sm:py-2 whitespace-nowrap", balances.reduce((sum, b) => sum + b.balance, 0) >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
                            {formatCurrency(balances.reduce((sum, b) => sum + b.balance, 0))}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No deposits recorded yet. Add your first deposit on the Settings page.
                  </p>
                )}
              </CardContent>
            </Card>

            {/* PERFORMANCE */}
            <Card>
              <CardHeader className="pb-2">
                <h3 className="font-semibold text-sm">Performance</h3>
                <p className="text-xs text-muted-foreground">Familiar stats, with context.</p>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <StatCard label="ROI" value={settledROI} format="percent" colorize subtitle={totalSettledStake > 0 ? "settled" : undefined} />
                  <StatCard
                    label="Win Rate"
                    value={actualWinRate === null ? null : actualWinRate / 100}
                    format="percent"
                    subtitle={
                      actualWinRate !== null && expectedWinRate !== null
                        ? `Exp: ${expectedWinRate.toFixed(1)}%`
                        : undefined
                    }
                  />
                  <StatCard
                    label="Luck vs EV"
                    value={settledBets.length > 0 ? (settledProfit - settledEV) : null}
                    format="currency"
                    colorize
                    subtitle="profit vs EV"
                  />
                  <StatCard label="Settled Bets" value={settledBets.length} format="number" subtitle="sample size" />
                </div>
              </CardContent>
            </Card>

            {/* HIGHLIGHTS */}
            <Card>
              <CardHeader className="pb-2">
                <h3 className="font-semibold text-sm">Highlights</h3>
                <p className="text-xs text-muted-foreground">Quick wins and momentum.</p>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <StatCard
                    label="Biggest Win"
                    value={biggestWin ? biggestWin.real_profit : null}
                    format="currency"
                    colorize
                    subtitle={biggestWin ? `${biggestWin.event.length > 18 ? `${biggestWin.event.slice(0, 18)}…` : biggestWin.event}` : undefined}
                  />
                  <StatCard
                    label="Best Day"
                    value={bestDay ? bestDay.profit : null}
                    format="currency"
                    colorize
                    subtitle={bestDay ? bestDay.label : undefined}
                  />
                  <StatCard
                    label="Best Source"
                    value={bestSource ? bestSource.label : "—"}
                    format="text"
                    subtitle={bestSource ? `${bestSource.value >= 0 ? "+" : ""}${formatCurrency(bestSource.value)} EV` : undefined}
                  />
                  <StatCard label="Beat Close" value={beatClosePct === null ? "—" : `${beatClosePct.toFixed(0)}%`} format="text" subtitle={`of ${clvBets.length} tracked`} />
                </div>
              </CardContent>
            </Card>

            {/* BREAKDOWNS */}
            <Card className="card-hover">
              <CardHeader className="pb-2">
                <h3 className="font-semibold text-sm">Breakdowns</h3>
                <p className="text-xs text-muted-foreground">Tap to explore where results come from.</p>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex gap-2">
                  <Button type="button" variant={breakdownTab === "book" ? "default" : "outline"} size="sm" className="flex-1" onClick={() => setBreakdownTab("book")}>
                    By Book
                  </Button>
                  <Button type="button" variant={breakdownTab === "sport" ? "default" : "outline"} size="sm" className="flex-1" onClick={() => setBreakdownTab("sport")}>
                    By Sport
                  </Button>
                  <Button type="button" variant={breakdownTab === "type" ? "default" : "outline"} size="sm" className="flex-1" onClick={() => setBreakdownTab("type")}>
                    By Type
                  </Button>
                </div>

                {breakdownTab === "book" && (
                  <div className="flex gap-2">
                    <Button type="button" variant={bookMetric === "ev" ? "default" : "outline"} size="sm" className="flex-1" onClick={() => setBookMetric("ev")}>
                      EV
                    </Button>
                    <Button type="button" variant={bookMetric === "profit" ? "default" : "outline"} size="sm" className="flex-1" onClick={() => setBookMetric("profit")}>
                      Profit
                    </Button>
                  </div>
                )}

                <div>
                  {breakdownTab === "book" && (
                    sportsbookChartData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={sportsbookChartData} layout="vertical" margin={{ left: 0, right: 10, top: 0, bottom: 0 }}>
                          <XAxis type="number" tickFormatter={(v) => `$${v}`} fontSize={10} stroke="hsl(var(--muted-foreground))" />
                          <YAxis type="category" dataKey="name" width={70} fontSize={10} stroke="hsl(var(--muted-foreground))" />
                          <Tooltip formatter={(value: number) => formatCurrency(value)} />
                          <Bar dataKey={bookMetric} radius={[0, 4, 4, 0]}>
                            {sportsbookChartData.map((entry, index) => (
                              <Cell
                                key={index}
                                fill={
                                  bookMetric === "ev"
                                    ? entry.color
                                    : entry.profit >= 0
                                      ? "#4A7C59"
                                      : "#B85C38"
                                }
                              />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <EmptyChart message="No data yet" />
                    )
                  )}

                  {breakdownTab === "sport" && (
                    sportChartData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={Math.max(160, sportChartData.length * 32)}>
                        <BarChart data={sportChartData} layout="vertical" margin={{ left: 0, right: 10, top: 0, bottom: 0 }}>
                          <XAxis type="number" tickFormatter={(v) => `$${v}`} fontSize={10} stroke="hsl(var(--muted-foreground))" />
                          <YAxis type="category" dataKey="name" width={70} fontSize={10} stroke="hsl(var(--muted-foreground))" />
                          <Tooltip formatter={(value: number) => formatCurrency(value)} />
                          <Bar dataKey="ev" radius={[0, 4, 4, 0]}>
                            {sportChartData.map((entry, index) => (
                              <Cell key={index} fill={entry.color} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <EmptyChart message="No data yet" />
                    )
                  )}

                  {breakdownTab === "type" && (
                    promoTypeData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={Math.max(160, promoTypeData.length * 32)}>
                        <BarChart data={promoTypeData} layout="vertical" margin={{ left: 0, right: 10, top: 0, bottom: 0 }}>
                          <XAxis type="number" allowDecimals={false} fontSize={10} stroke="hsl(var(--muted-foreground))" />
                          <YAxis type="category" dataKey="name" width={90} fontSize={10} stroke="hsl(var(--muted-foreground))" />
                          <Tooltip formatter={(value: number) => [`${value} bet${value !== 1 ? "s" : ""}`, "Count"]} />
                          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                            {promoTypeData.map((entry, index) => (
                              <Cell key={index} fill={entry.color} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <EmptyChart message="No data yet" />
                    )
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Advanced Metrics - Collapsible */}
            <Card>
              <details className="group">
                <summary className="cursor-pointer list-none hover:bg-muted/50 transition-colors rounded-lg">
                  <CardContent className="py-4 flex items-center justify-between">
                    <span className="font-medium">Advanced Metrics</span>
                    <span className="text-muted-foreground text-sm group-open:rotate-180 transition-transform">▼</span>
                  </CardContent>
                </summary>

                <div className="px-6 pb-6 pt-6 space-y-6 border-t">

                {/* Market Validation */}
                <Card>
                  <CardHeader className="pb-2">
                    <div className="flex items-center gap-2">
                      <Target className="h-4 w-4 text-muted-foreground" />
                      <h3 className="font-semibold text-sm">Market Validation</h3>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Standard bets only. Tracked = we captured entry + close lines.
                    </p>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                      <StatCard
                        label="Avg CLV"
                        value={avgCLV === null ? "—" : `${avgCLV >= 0 ? "+" : ""}${avgCLV.toFixed(2)}%`}
                        format="text"
                        subtitle={clvBets.length > 0 ? "tracked standard bets" : undefined}
                        className={
                          avgCLV === null
                            ? ""
                            : avgCLV >= 1.5
                              ? "text-[#4A7C59]"
                              : avgCLV >= 0
                                ? "text-[#8B7355]"
                                : "text-[#B85C38]"
                        }
                      />
                      <StatCard
                        label="Beat Close"
                        value={beatClosePct === null ? "—" : `${beatClosePct.toFixed(0)}%`}
                        format="text"
                        subtitle="of tracked"
                        className={
                          beatClosePct === null
                            ? ""
                            : beatClosePct >= 55
                              ? "text-[#4A7C59]"
                              : beatClosePct >= 45
                                ? "text-foreground"
                                : "text-[#B85C38]"
                        }
                      />
                      <StatCard
                        label="Tracked Sample"
                        value={`${clvBets.length} tracked`}
                        format="text"
                        subtitle={`standard bets (of ${settledStandardCount} settled)`}
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* Diagnostics */}
                <Card>
                  <CardHeader className="pb-2">
                    <h3 className="font-semibold text-sm">Diagnostics</h3>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                      <StatCard label="Pending EV" value={pendingEV} format="currency" colorize />
                      <StatCard label="Cash Risked" value={totalSettledStake} format="currency" subtitle="settled" />
                      <StatCard
                        label="EV Conversion"
                        value={evConversion === null ? "—" : `${(evConversion * 100).toFixed(0)}%`}
                        format="text"
                        subtitle="actual / expected"
                        className={
                          evConversion === null
                            ? ""
                            : evConversion >= 1.2
                              ? "text-[#4A7C59]"
                              : evConversion >= 0.8
                                ? "text-foreground"
                                : "text-[#B85C38]"
                        }
                      />
                      <StatCard
                        label="Profit Factor"
                        value={profitFactor === null ? "—" : `${profitFactor.toFixed(2)} PF`}
                        format="text"
                        subtitle={profitFactor === null ? undefined : `$${profitFactor.toFixed(2)} earned per $1 lost`}
                      />
                      <StatCard
                        label="Bonus Efficiency"
                        value={bonusEfficiency === null ? "—" : `${bonusEfficiency.toFixed(0)}%`}
                        format="text"
                        subtitle={bonusEfficiency === null ? undefined : `+${formatCurrency(bonusReturns)} from ${formatCurrency(bonusStaked)}`}
                      />
                      <StatCard
                        label="Z-Score"
                        value={zScore === null ? "—" : zScore.toFixed(2)}
                        format="text"
                        subtitle={zScore === null ? undefined : `${zScore >= 0 ? "+" : ""}${formatCurrency(settledProfit - settledEV)} vs EV`}
                      />
                    </div>
                  </CardContent>
                </Card>
              </div>
            </details>
            </Card>

          </>
        )}
      </div>
    </main>
  );
}

// Stat Card Component
function StatCard({ 
  label, 
  value, 
  format, 
  colorize = false,
  subtitle,
  className
}: { 
  label: string; 
  value: number | string | null | undefined;
  format: "currency" | "percent" | "number" | "text";
  colorize?: boolean;
  subtitle?: string;
  className?: string;
}) {
  let displayValue: string;
  let colorClass = "";
  
  if (value === null || value === undefined) {
    displayValue = "—";
  } else if (format === "currency" && typeof value === "number") {
    displayValue = formatCurrency(value);
    if (colorize) colorClass = value >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]";
  } else if (format === "percent" && typeof value === "number") {
    displayValue = formatPercent(value);
    if (colorize) colorClass = value >= 0.05 ? "text-[#4A7C59]" : value <= -0.05 ? "text-[#B85C38]" : "text-[#8B7355]";
  } else if (format === "number" && typeof value === "number") {
    displayValue = value.toLocaleString();
  } else {
    displayValue = String(value);
  }

  return (
    <div className="rounded-lg bg-muted p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-xl font-bold", colorClass, className)}>
        {displayValue}
      </p>
      {subtitle && (
        <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}

// Empty Chart State
function EmptyChart({ message }: { message: string }) {
  return (
    <div className="h-[250px] flex items-center justify-center text-muted-foreground">
      <p className="text-sm">{message}</p>
    </div>
  );
}

// Format promo type for display
function formatPromoType(promo: string): string {
  const map: Record<string, string> = {
    standard: "Standard",
    bonus_bet: "Bonus Bet",
    no_sweat: "No Sweat",
    promo_qualifier: "Promo Qualifier",
    boost_30: "30% Boost",
    boost_50: "50% Boost",
    boost_100: "100% Boost",
    boost_custom: "Custom Boost",
  };
  return map[promo] || promo;
}

