"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";
import { 
  TrendingUp, 
  TrendingDown, 
  Trophy, 
  Target, 
  DollarSign,
  BarChart3,
  PieChart as PieChartIcon,
  Activity
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

  // Calculate additional metrics from bets
  const settledBets = bets?.filter(b => b.result !== "pending") || [];
  const pendingBets = bets?.filter(b => b.result === "pending") || [];
  
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
  
  // EV Conversion (Real Profit / Settled EV)
  const evConversion = settledEV > 0 ? ((summary?.total_real_profit || 0) / settledEV) : null;
  
  // ROI based on settled cash
  const settledROI = totalSettledStake > 0 ? ((summary?.total_real_profit || 0) / totalSettledStake) : null;
  
  // Expected win % (based on average implied probability of bets taken)
  const totalImpliedProb = settledBets.reduce((sum, b) => sum + (1 / b.odds_decimal), 0);
  const expectedWinRate = settledBets.length > 0 ? (totalImpliedProb / settledBets.length) : null;

  // Prepare chart data
  const sportsbookChartData = summary 
    ? Object.entries(summary.ev_by_sportsbook)
        .map(([name, ev]) => ({
          name: name.replace("ESPN Bet", "ESPN").replace("Hard Rock", "HR"),
          ev: ev,
          profit: summary.profit_by_sportsbook[name] || 0,
          color: SPORTSBOOK_COLORS[name] || "#888",
        }))
        .sort((a, b) => b.ev - a.ev)
    : [];

  const sportChartData = summary
    ? Object.entries(summary.ev_by_sport)
        .map(([name, ev], i) => ({
          name,
          value: ev,
          color: CHART_COLORS[i % CHART_COLORS.length],
        }))
        .sort((a, b) => b.value - a.value)
    : [];

  // Bets by promo type
  const promoTypeData = bets
    ? Object.entries(
        bets.reduce((acc, bet) => {
          const label = formatPromoType(bet.promo_type);
          acc[label] = (acc[label] || 0) + 1;
          return acc;
        }, {} as Record<string, number>)
      ).map(([name, value], i) => ({
        name,
        value,
        color: CHART_COLORS[i % CHART_COLORS.length],
      }))
    : [];

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
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-4xl">
        {isLoading ? (
          <div className="text-center py-12 text-muted-foreground">
            <Activity className="h-8 w-8 mx-auto mb-2 animate-pulse text-[#C4A35A]" />
            <p>Loading analytics...</p>
          </div>
        ) : (
          <>
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
                  <p className={cn("text-xl sm:text-2xl font-bold font-mono leading-tight", (summary?.total_real_profit || 0) >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
                    {(summary?.total_real_profit || 0) >= 0 ? "+" : ""}{formatCurrency(summary?.total_real_profit || 0)}
                  </p>
                </CardContent>
              </Card>
              <Card className="card-hover">
                <CardContent className="pt-4 pb-3 flex flex-col items-center justify-center">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Total EV</p>
                  <p className="text-xl sm:text-2xl font-bold font-mono text-[#C4A35A] leading-tight">
                    +{formatCurrency(summary?.total_ev || 0)}
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
                  <p className="text-xs text-muted-foreground">
                    {evConversion !== null && evConversion >= 1.1 ? "running hot" : 
                     evConversion !== null && evConversion <= 0.9 ? "running cold" : 
                     evConversion !== null ? "on track" : ""}
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
                  <ResponsiveContainer width="100%" height={250}>
                    <ComposedChart data={cumulativeData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis 
                        dataKey="date" 
                        fontSize={10} 
                        angle={-45} 
                        textAnchor="end" 
                        height={60}
                        interval="preserveStartEnd"
                        stroke="hsl(var(--muted-foreground))"
                      />
                      <YAxis tickFormatter={(v) => `$${v}`} fontSize={11} stroke="hsl(var(--muted-foreground))" />
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
                      <StatCard label="ROI" value={settledROI} format="percent" colorize />
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
                        <ResponsiveContainer width="100%" height={200}>
                          <PieChart>
                            <Pie data={sportChartData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={60} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false} fontSize={10}>
                              {sportChartData.map((entry, index) => (
                                <Cell key={index} fill={entry.color} />
                              ))}
                            </Pie>
                            <Tooltip formatter={(value: number) => formatCurrency(value)} />
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
                        <ResponsiveContainer width="100%" height={200}>
                          <PieChart>
                            <Pie data={promoTypeData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={60} label={({ name, value }) => `${name}: ${value}`} labelLine={false} fontSize={10}>
                              {promoTypeData.map((entry, index) => (
                                <Cell key={index} fill={entry.color} />
                              ))}
                            </Pie>
                            <Tooltip />
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
