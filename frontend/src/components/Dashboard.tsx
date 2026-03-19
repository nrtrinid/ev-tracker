"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSummary, useBets, useBackendReadiness, useBalances } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";
import { TopKpiCards } from "@/components/TopKpiCards";

export function Dashboard() {
  const { data: summary, isLoading: summaryLoading } = useSummary();
  const { data: bets, isLoading: betsLoading } = useBets();
  const { data: balances, isLoading: balancesLoading } = useBalances();
  const { data: readiness } = useBackendReadiness();

  const isLoading = summaryLoading || betsLoading || balancesLoading;

  if (isLoading || !summary) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardContent className="p-4 flex flex-col items-center justify-center">
              <div className="flex items-center gap-1.5 mb-1">
                <Skeleton className="h-3.5 w-3.5 rounded" />
                <Skeleton className="h-3 w-16" />
              </div>
              <Skeleton className="h-7 w-20" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const totalBalance =
    balances && balances.length > 0 ? balances.reduce((sum, b) => sum + (b.balance || 0), 0) : null;

  // Expected Profit should be settled-only EV (apples-to-apples with Net Profit)
  const settledEV = (bets || []).filter((b) => b.result !== "pending").reduce((sum, b) => sum + b.ev_total, 0);

  // Beat Close / Avg CLV (standard bets only)
  const standardBets = (bets || []).filter((b) => b.promo_type === "standard");
  const clvBets = standardBets.filter((b) => b.clv_ev_percent !== null);
  const beatCloseCount = clvBets.filter((b) => b.beat_close === true).length;
  const beatClosePct = clvBets.length > 0 ? (beatCloseCount / clvBets.length) * 100 : null;
  const avgCLV =
    clvBets.length > 0
      ? clvBets.reduce((sum, b) => sum + (b.clv_ev_percent ?? 0), 0) / clvBets.length
      : null;
  const showDegradedHint = !!readiness && (readiness.status !== "ready" || !readiness.checks.scheduler_freshness);
  const degradedLabel = readiness?.status === "unreachable"
    ? "Some data is temporarily unavailable"
    : "Recent bet results may still be updating";

  return (
    <>
      <TopKpiCards
        href="/analytics"
        netProfit={summary.total_real_profit}
        expectedProfit={settledEV}
        totalBalance={totalBalance}
        beatClose={{ beatClosePct, avgClvPct: avgCLV }}
      />
      {showDegradedHint && (
        <div className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-[#B85C38]/30 bg-[#B85C38]/10 px-2.5 py-1.5 text-xs text-[#8B3D20]">
          <AlertTriangle className="h-3.5 w-3.5" />
          {degradedLabel}
        </div>
      )}
    </>
  );
}
