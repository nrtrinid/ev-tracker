"use client";

import { Card, CardContent } from "@/components/ui/card";
import { useSummary, useBets } from "@/lib/hooks";
import { formatCurrency, cn } from "@/lib/utils";
import { TrendingUp, DollarSign, Activity, Clock } from "lucide-react";
import Link from "next/link";

export function Dashboard() {
  const { data: summary, isLoading: summaryLoading } = useSummary();
  const { data: bets, isLoading: betsLoading } = useBets();

  const isLoading = summaryLoading || betsLoading;

  if (isLoading || !summary) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <div className="h-4 w-16 animate-pulse bg-muted rounded mb-2" />
              <div className="h-8 w-24 animate-pulse bg-muted rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  // Calculate pending EV and EV conversion
  const settledBets = bets?.filter(b => b.result !== "pending") || [];
  const pendingBets = bets?.filter(b => b.result === "pending") || [];
  const pendingEV = pendingBets.reduce((sum, b) => sum + b.ev_total, 0);
  const settledEV = settledBets.reduce((sum, b) => sum + b.ev_total, 0);
  const evConversion = settledEV > 0 ? (summary.total_real_profit / settledEV) : null;

  return (
    <Link href="/analytics" className="block">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 group">
        {/* Real Profit - The bottom line */}
        <Card className="card-hover">
          <CardContent className="p-4 flex flex-col items-center justify-center">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <DollarSign className="h-3.5 w-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">Profit</span>
            </div>
            <p className={cn(
              "text-xl sm:text-2xl font-bold font-mono tracking-tight",
              summary.total_real_profit >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]"
            )}>
              {summary.total_real_profit >= 0 ? "+" : ""}{formatCurrency(summary.total_real_profit)}
            </p>
          </CardContent>
        </Card>

        {/* Total EV - Process metric */}
        <Card className="card-hover">
          <CardContent className="p-4 flex flex-col items-center justify-center">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <TrendingUp className="h-3.5 w-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">Total EV</span>
            </div>
            <p className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-[#C4A35A]">
              +{formatCurrency(summary.total_ev)}
            </p>
          </CardContent>
        </Card>

        {/* EV Conversion - Variance indicator */}
        <Card className="card-hover">
          <CardContent className="p-4 flex flex-col items-center justify-center">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <Activity className="h-3.5 w-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">Conversion</span>
            </div>
            <p className={cn(
              "text-xl sm:text-2xl font-bold font-mono tracking-tight",
              evConversion === null ? "text-muted-foreground" :
              evConversion >= 1.2 ? "text-[#4A7C59]" :
              evConversion >= 0.8 ? "text-foreground" :
              "text-[#B85C38]"
            )}>
              {evConversion !== null ? `${(evConversion * 100).toFixed(0)}%` : "—"}
            </p>
          </CardContent>
        </Card>

        {/* Pending EV - What's in play */}
        <Card className="card-hover">
          <CardContent className="p-4 flex flex-col items-center justify-center">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <Clock className="h-3.5 w-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">Pending</span>
            </div>
            <p className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-[#C4A35A]">
              +{formatCurrency(pendingEV)}
            </p>
            <p className="text-[10px] text-muted-foreground">
              {pendingBets.length} bet{pendingBets.length !== 1 ? "s" : ""}
            </p>
          </CardContent>
        </Card>
      </div>
    </Link>
  );
}
