"use client";

import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { cn, formatCurrency } from "@/lib/utils";
import { DollarSign, TrendingUp, Target, Wallet, Info } from "lucide-react";

export type BeatCloseMeta = {
  beatClosePct?: number | null;
  avgClvPct?: number | null;
  trackedCount?: number | null;
};

type TopKpiCardsProps = {
  netProfit: number;
  expectedProfit: number;
  totalBalance?: number | null;
  beatClose?: BeatCloseMeta;
  href?: string;
};

function BeatCloseValue({
  beatClosePct,
  avgClvPct,
  trackedCount,
}: {
  beatClosePct: number | null | undefined;
  avgClvPct: number | null | undefined;
  trackedCount: number | null | undefined;
}) {
  const trackedLabel =
    trackedCount === null || trackedCount === undefined ? "of tracked" : `of ${trackedCount} tracked`;

  if (beatClosePct !== null && beatClosePct !== undefined) {
    const color =
      beatClosePct >= 55 ? "text-[#4A7C59]" : beatClosePct >= 45 ? "text-foreground" : "text-[#B85C38]";
    return (
      <>
        <p className={cn("text-xl sm:text-2xl font-bold font-mono tracking-tight", color)}>
          {beatClosePct.toFixed(0)}%
        </p>
        <p className="text-[10px] text-muted-foreground mt-0.5">{trackedLabel}</p>
      </>
    );
  }

  if (avgClvPct !== null && avgClvPct !== undefined) {
    const color =
      avgClvPct >= 1.5 ? "text-[#4A7C59]" : avgClvPct >= 0 ? "text-[#8B7355]" : "text-[#B85C38]";
    return (
      <>
        <p className={cn("text-xl sm:text-2xl font-bold font-mono tracking-tight", color)}>
          {avgClvPct >= 0 ? "+" : ""}
          {avgClvPct.toFixed(2)}%
        </p>
        <p className="text-[10px] text-muted-foreground mt-0.5">{trackedLabel}</p>
      </>
    );
  }

  return (
    <>
      <p className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-muted-foreground">Tracking…</p>
      <p className="text-[10px] text-muted-foreground mt-0.5">{trackedLabel}</p>
    </>
  );
}

function TopKpiCardsInner({ netProfit, expectedProfit, totalBalance, beatClose }: Omit<TopKpiCardsProps, "href">) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 group">
      <Card className="card-hover">
        <CardContent className="p-4 flex flex-col items-center justify-center">
          <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
            <DollarSign className="h-3.5 w-3.5" />
            <span className="text-xs font-medium uppercase tracking-wide">Profit</span>
          </div>
          <p
            className={cn(
              "text-xl sm:text-2xl font-bold font-mono tracking-tight",
              netProfit >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]",
            )}
          >
            {netProfit >= 0 ? "+" : ""}
            {formatCurrency(netProfit)}
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">settled bets</p>
        </CardContent>
      </Card>

      <Card className="card-hover">
        <CardContent className="p-4 flex flex-col items-center justify-center">
          <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
            <TrendingUp className="h-3.5 w-3.5" />
            <span className="text-xs font-medium uppercase tracking-wide">EV</span>
          </div>
          <p className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-[#C4A35A]">
            {expectedProfit >= 0 ? "+" : ""}
            {formatCurrency(expectedProfit)}
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">long-run value</p>
        </CardContent>
      </Card>

      <Card className="card-hover">
        <CardContent className="p-4 flex flex-col items-center justify-center">
          <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
            <Target className="h-3.5 w-3.5" />
            <span className="text-xs font-medium uppercase tracking-wide">Beat close</span>
            <span
              title="How often your line was better than the market close. Over time, beating the close is one of the strongest signs you’re getting good prices."
              className="inline-flex"
            >
              <Info className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" aria-label="Line Value explanation" />
            </span>
          </div>
          <BeatCloseValue
            beatClosePct={beatClose?.beatClosePct}
            avgClvPct={beatClose?.avgClvPct}
            trackedCount={beatClose?.trackedCount}
          />
        </CardContent>
      </Card>

      <Card className="card-hover">
        <CardContent className="p-4 flex flex-col items-center justify-center">
          <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
            <Wallet className="h-3.5 w-3.5" />
            <span className="text-xs font-medium uppercase tracking-wide">Bankroll</span>
          </div>
          <p
            className={cn(
              "text-xl sm:text-2xl font-bold font-mono tracking-tight",
              totalBalance === null || totalBalance === undefined
                ? "text-muted-foreground"
                : totalBalance >= 0
                  ? "text-[#4A7C59]"
                  : "text-[#B85C38]",
            )}
          >
            {totalBalance === null || totalBalance === undefined
              ? "—"
              : `${formatCurrency(totalBalance)}`}
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">across books</p>
        </CardContent>
      </Card>
    </div>
  );
}

export function TopKpiCards(props: TopKpiCardsProps) {
  const { href, ...rest } = props;
  if (href) {
    return (
      <Link href={href} className="block">
        <TopKpiCardsInner {...rest} />
      </Link>
    );
  }
  return <TopKpiCardsInner {...rest} />;
}

