"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
  PieChart as PieChartIcon,
  Activity,
  X,
  SlidersHorizontal
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getBets, getSummary, getBalances } from "@/lib/api";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  Tooltip, 
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
  LineChart,
  Line,
  CartesianGrid,
  Area,
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

export default function AnalyticsPage() {
  // Filter state
  const [timeframe, setTimeframe] = useState<TimeframeOption>("All Time");
  const [betType, setBetType] = useState<BetTypeOption>("All Types");
  const [sport, setSport] = useState<SportOption>("All Sports");
  const [sportsbook, setSportsbook] = useState<SportsbookOption>("All Books");
  const [filterOpen, setFilterOpen] = useState(false);

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

  const isLoading = summaryLoading || betsLoading;

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
  const zScore = standardDeviation > 0 
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
    
    // Separate large and small slices
    const largeSlices: Array<{ name: string; value: number; color: string }> = [];
    let otherValue = 0;
    
    // Sort entries by value first
    const sortedEntries = Object.entries(evBySport).sort((a, b) => b[1] - a[1]);
    
    sortedEntries.forEach(([name, ev], i) => {
      const percent = Math.abs(ev) / totalEV;
      if (percent >= 0.05) {
        largeSlices.push({
          name,
          value: ev,
          color: CHART_COLORS[largeSlices.length % CHART_COLORS.length],
        });
      } else {
        otherValue += ev;
      }
    });
    
    // Add "Other" slice at the end if there are small slices
    if (otherValue !== 0) {
      largeSlices.push({
        name: "Other",
        value: otherValue,
        color: "#78716C", // stone-500 for better contrast
      });
    }
    
    return largeSlices;
  }, [filteredBets]);

  // Bets by promo type (from filtered bets) - no "Other" grouping since there are limited types
  const promoTypeData = useMemo(() => {
    const counts: Record<string, number> = {};
    
    filteredBets.forEach(bet => {
      const label = formatPromoType(bet.promo_type);
      counts[label] = (counts[label] || 0) + 1;
    });
    
    return Object.entries(counts)
      .map(([name, value], i) => ({
        name,
        value,
        color: CHART_COLORS[i % CHART_COLORS.length],
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
        {isLoading ? (
          <div className="text-center py-12 text-muted-foreground">
            <Activity className="h-8 w-8 mx-auto mb-2 animate-pulse text-[#C4A35A]" />
            <p>Loading analytics...</p>
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
                <button
                  onClick={clearFilters}
                  className="text-xs text-muted-foreground hover:text-foreground underline"
                >
                  Clear
                </button>
              </div>
            )}

            {/* HERO: Performance Status with Z-Score */}
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
                  <p className="text-sm text-muted-foreground mb-2 uppercase tracking-wide">Performance Status</p>
                  <div>
                    <p className={cn(
                      "text-2xl font-bold",
                      zScore === null ? "text-muted-foreground" :
                      zScore >= 0.5 ? "text-[#4A7C59]" :
                      zScore >= -0.5 ? "text-[#C4A35A]" :
                      "text-[#B85C38]"
                    )}>
                      {zScore === null ? "Need more data" :
                       zScore >= 1.5 ? "Running Hot" :
                       zScore >= 0.5 ? "Above Average" :
                       zScore >= -0.5 ? "On Track" :
                       zScore >= -1.5 ? "Below Average" : "Running Cold"}
                    </p>
                    {zScore !== null && (
                      <p className="text-sm text-muted-foreground mt-1">
                        Z-Score: <span className="font-mono">{zScore.toFixed(2)}</span> ({zScore >= 0 ? "+" : ""}{formatCurrency(settledProfit - settledEV)} vs expected)
                      </p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Key Numbers - The 4 Things That Matter for EV Bettors */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Card className="card-hover">
                <CardContent className="pt-4 pb-3 flex flex-col items-center justify-center">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Real Profit</p>
                  <p className={cn("text-xl sm:text-2xl font-bold font-mono leading-tight", filteredRealProfit >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
                    {filteredRealProfit >= 0 ? "+" : ""}{formatCurrency(filteredRealProfit)}
                  </p>
                </CardContent>
              </Card>
              <Card className="card-hover">
                <CardContent className="pt-4 pb-3 flex flex-col items-center justify-center">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Total EV</p>
                  <p className="text-xl sm:text-2xl font-bold font-mono text-[#C4A35A] leading-tight">
                    {filteredTotalEV >= 0 ? "+" : ""}{formatCurrency(filteredTotalEV)}
                  </p>
                </CardContent>
              </Card>
              <Card className="card-hover">
                <CardContent className="pt-4 pb-3 flex flex-col items-center justify-center">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">EV Conversion</p>
                  <p className={cn(
                    "text-xl sm:text-2xl font-bold font-mono leading-tight",
                    evConversion === null ? "text-muted-foreground" :
                    evConversion >= 1.2 ? "text-[#4A7C59]" :
                    evConversion >= 0.8 ? "text-foreground" :
                    "text-[#B85C38]"
                  )}>
                    {evConversion !== null ? `${(evConversion * 100).toFixed(0)}%` : "—"}
                  </p>
                </CardContent>
              </Card>
              <Card className="card-hover">
                <CardContent className="pt-4 pb-3 flex flex-col items-center justify-center">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Pending EV</p>
                  <p className="text-xl sm:text-2xl font-bold font-mono text-[#C4A35A] leading-tight">
                    +{formatCurrency(pendingEV)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {pendingBets.length} bet{pendingBets.length !== 1 ? "s" : ""}
                  </p>
                </CardContent>
              </Card>
            </div>

            {/* Cumulative EV vs Profit Chart */}
            {cumulativeData.length > 1 && (
              <Card className="card-hover">
                <CardHeader className="pb-2">
                  <h2 className="font-semibold">EV vs Reality (Settled Bets)</h2>
                  <p className="text-xs text-muted-foreground">
                    Gold = expected EV • Green = actual profit
                  </p>
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
                        width={60}
                      />
                      <Tooltip 
                        formatter={(value: number, name: string) => [
                          formatCurrency(value),
                          name
                        ]}
                        labelFormatter={(label) => label}
                      />
                      <Line type="monotone" dataKey="cumulativeEV" stroke="#C4A35A" strokeWidth={2} dot={false} name="Expected EV" />
                      <Line type="monotone" dataKey="cumulativeProfit" stroke="#4A7C59" strokeWidth={2} dot={false} name="Actual Profit" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}

            {/* Detailed Breakdown - Collapsible */}
            <Card>
              <details className="group">
                <summary className="cursor-pointer list-none hover:bg-muted/50 transition-colors rounded-lg">
                  <CardContent className="py-4 flex items-center justify-between">
                    <span className="font-medium">Detailed Breakdown</span>
                    <span className="text-muted-foreground text-sm group-open:rotate-180 transition-transform">▼</span>
                  </CardContent>
                </summary>
                
                <div className="px-6 pb-6 pt-6 space-y-6 border-t">
                {/* Bankroll Box */}
                <Card>
                  <CardHeader className="pb-2">
                    <h3 className="font-semibold text-sm">Bankroll Status</h3>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <StatCard label="Pending Exposure" value={totalPendingStake} format="currency" subtitle={`${pendingBets.length} bets`} />
                      <StatCard label="Pending EV" value={pendingEV} format="currency" colorize />
                      <StatCard label="Cash Risked" value={totalSettledStake} format="currency" subtitle="Settled" />
                      <StatCard 
                        label="ROI" 
                        value={settledROI} 
                        format="percent" 
                        subtitle={
                          settledROI !== null
                            ? settledROI > 0.15
                              ? "High Efficiency"
                              : settledROI > 0
                              ? "Drifting"
                              : "Leaking"
                            : undefined
                        }
                        className={
                          settledROI !== null
                            ? settledROI > 0.15
                              ? "text-[#4A7C59]"
                              : settledROI > 0
                              ? "text-[#C4A35A]"
                              : "text-[#B85C38]"
                            : ""
                        }
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* Fun Metrics Row */}
                <Card>
                  <CardHeader className="pb-2">
                    <h3 className="font-semibold text-sm">Fun Metrics</h3>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      {/* Biggest Win */}
                      <div className="rounded-lg bg-muted border border-border p-3">
                        <p className="text-xs text-muted-foreground">Biggest Win</p>
                        <p className="text-lg font-bold text-foreground">
                          {biggestWin ? `+${formatCurrency(biggestWin.real_profit || 0)}` : "—"}
                        </p>
                        {biggestWin && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {biggestWin.event.length > 20 
                              ? `${biggestWin.event.substring(0, 20)}...` 
                              : biggestWin.event} @ {formatOdds(biggestWin.odds_american)}
                          </p>
                        )}
                      </div>

                      {/* Win Rate */}
                      <div className="rounded-lg bg-muted border border-border p-3">
                        <p className="text-xs text-muted-foreground">Win Rate</p>
                        <p className="text-lg font-bold text-foreground">
                          {actualWinRate !== null ? `${actualWinRate.toFixed(1)}%` : "—"}
                        </p>
                        {actualWinRate !== null && expectedWinRate !== null && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            Exp: {expectedWinRate.toFixed(1)}% ({actualWinRate > expectedWinRate ? "Running Hot" : "Running Cold"})
                          </p>
                        )}
                      </div>

                      {/* Profit Factor */}
                      <div className="rounded-lg bg-muted border border-border p-3">
                        <p className="text-xs text-muted-foreground">Profit Factor</p>
                        <p className="text-lg font-bold text-foreground">
                          {profitFactor !== null ? `${profitFactor.toFixed(2)} PF` : "—"}
                        </p>
                        {profitFactor !== null && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            ${profitFactor.toFixed(2)} earned per $1 lost
                          </p>
                        )}
                      </div>

                      {/* Bonus Efficiency */}
                      <div className="rounded-lg bg-muted border border-border p-3">
                        <p className="text-xs text-muted-foreground">Bonus Efficiency</p>
                        <p className="text-lg font-bold text-foreground">
                          {bonusEfficiency !== null ? `${bonusEfficiency.toFixed(0)}% Conversion` : "—"}
                        </p>
                        {bonusEfficiency !== null && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            +{formatCurrency(bonusReturns)} washed from {formatCurrency(bonusStaked)}
                          </p>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Charts Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* EV by Sportsbook */}
                  <Card>
                    <CardHeader className="pb-2">
                      <h3 className="font-semibold text-sm">EV by Sportsbook</h3>
                    </CardHeader>
                    <CardContent>
                      {sportsbookChartData.length > 0 ? (
                        <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={sportsbookChartData} layout="vertical">
                            <XAxis type="number" tickFormatter={(v) => `$${v}`} fontSize={10} />
                            <YAxis type="category" dataKey="name" width={60} fontSize={10} />
                            <Tooltip formatter={(value: number) => formatCurrency(value)} />
                            <Bar dataKey="ev" radius={[0, 4, 4, 0]}>
                              {sportsbookChartData.map((entry, index) => (
                                <Cell key={index} fill={entry.color} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      ) : (
                        <EmptyChart message="No data yet" />
                      )}
                    </CardContent>
                  </Card>

                  {/* Profit by Sportsbook */}
                  <Card>
                    <CardHeader className="pb-2">
                      <h3 className="font-semibold text-sm">Profit by Sportsbook</h3>
                    </CardHeader>
                    <CardContent>
                      {sportsbookChartData.length > 0 ? (
                        <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={sportsbookChartData} layout="vertical">
                            <XAxis type="number" tickFormatter={(v) => `$${v}`} fontSize={10} />
                            <YAxis type="category" dataKey="name" width={60} fontSize={10} />
                            <Tooltip formatter={(value: number) => formatCurrency(value)} />
                            <Bar dataKey="profit" radius={[0, 4, 4, 0]}>
                              {sportsbookChartData.map((entry, index) => (
                                <Cell key={index} fill={entry.profit >= 0 ? "#4A7C59" : "#B85C38"} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      ) : (
                        <EmptyChart message="No data yet" />
                      )}
                    </CardContent>
                  </Card>

                  {/* EV by Sport */}
                  <Card>
                    <CardHeader className="pb-2">
                      <h3 className="font-semibold text-sm">EV by Sport</h3>
                    </CardHeader>
                    <CardContent>
                      {sportChartData.length > 0 ? (
                        <ResponsiveContainer width="100%" height={220}>
                          <PieChart>
                            <Pie 
                              data={sportChartData} 
                              dataKey="value" 
                              nameKey="name" 
                              cx="50%" 
                              cy="45%" 
                              outerRadius={55} 
                              label={({ payload, percent }) => {
                                // Access name from payload (the original data entry)
                                const name = payload?.name || "";
                                return `${name} ${(percent * 100).toFixed(0)}%`;
                              }} 
                              labelLine={false} 
                              fontSize={10}
                            >
                              {sportChartData.map((entry, index) => (
                                <Cell key={index} fill={entry.color} name={entry.name} />
                              ))}
                            </Pie>
                            <Tooltip formatter={(value: number) => formatCurrency(value)} />
                            <Legend 
                              payload={sportChartData.map((entry) => ({
                                value: entry.name,
                                type: "square" as const,
                                color: entry.color,
                              }))}
                              wrapperStyle={{ fontSize: '10px', paddingTop: '8px' }}
                              layout="horizontal"
                              align="center"
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      ) : (
                        <EmptyChart message="No data yet" />
                      )}
                    </CardContent>
                  </Card>

                  {/* Bets by Promo Type */}
                  <Card>
                    <CardHeader className="pb-2">
                      <h3 className="font-semibold text-sm">Bets by Promo Type</h3>
                    </CardHeader>
                    <CardContent>
                      {promoTypeData.length > 0 ? (
                        <ResponsiveContainer width="100%" height={220}>
                          <PieChart>
                            <Pie 
                              data={promoTypeData} 
                              dataKey="value" 
                              nameKey="name" 
                              cx="50%" 
                              cy="45%" 
                              outerRadius={55} 
                              label={({ payload }) => {
                                const name = payload?.name || "";
                                const value = payload?.value || 0;
                                return `${name}: ${value}`;
                              }} 
                              labelLine={false} 
                              fontSize={10}
                            >
                              {promoTypeData.map((entry, index) => (
                                <Cell key={index} fill={entry.color} name={entry.name} />
                              ))}
                            </Pie>
                            <Tooltip />
                            <Legend 
                              payload={promoTypeData.map((entry) => ({
                                value: entry.name,
                                type: "square" as const,
                                color: entry.color,
                              }))}
                              wrapperStyle={{ fontSize: '10px', paddingTop: '8px' }}
                              layout="horizontal"
                              align="center"
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      ) : (
                        <EmptyChart message="No data yet" />
                      )}
                    </CardContent>
                  </Card>
                </div>

                {/* Per-Sportsbook Balances */}
                <Card>
                  <CardHeader className="pb-2">
                    <h3 className="font-semibold text-sm">Sportsbook Balances</h3>
                    <p className="text-xs text-muted-foreground">Add deposits/withdrawals on the Settings page</p>
                  </CardHeader>
                  <CardContent>
                    {balances && balances.length > 0 ? (
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
                            {/* Totals row */}
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
    if (colorize) colorClass = value >= 1 ? "text-[#4A7C59]" : value < 0.8 ? "text-[#B85C38]" : "text-[#8B7355]";
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

