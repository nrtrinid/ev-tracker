"use client";

import { ChevronRight } from "lucide-react";

import { SPORTSBOOK_BADGE_COLORS, sportsbookAbbrev } from "@/lib/sportsbook-config";
import { cn, formatCurrency } from "@/lib/utils";
import type { Balance } from "@/lib/types";

export function SportsbookBalanceRow({
  balance,
  onSelect,
}: {
  balance: Balance;
  onSelect: (sportsbook: string) => void;
}) {
  const isNegative = balance.balance < 0;

  return (
    <button
      type="button"
      onClick={() => onSelect(balance.sportsbook)}
      className="group flex w-full items-center justify-between gap-3 rounded-md border border-border/60 bg-background/45 px-3 py-3 text-left transition-colors hover:border-border hover:bg-muted/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white",
            SPORTSBOOK_BADGE_COLORS[balance.sportsbook] ?? "bg-foreground",
          )}
          aria-hidden="true"
        >
          {sportsbookAbbrev(balance.sportsbook)}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{balance.sportsbook}</p>
          <p className="text-xs text-muted-foreground">
            {balance.pending > 0 ? `${formatCurrency(balance.pending)} at risk` : "No open cash stake"}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span
          className={cn(
            "font-mono text-sm font-bold tabular-nums",
            isNegative ? "text-color-loss-fg" : "text-foreground",
          )}
        >
          {formatCurrency(balance.balance)}
        </span>
        <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
    </button>
  );
}
