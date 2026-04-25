"use client";

import { ArrowDownCircle, ArrowLeft, ArrowUpCircle, SlidersHorizontal } from "lucide-react";

import { RecentBankrollActivity } from "@/components/bankroll/RecentBankrollActivity";
import { Button } from "@/components/ui/button";
import { SPORTSBOOK_BADGE_COLORS, sportsbookAbbrev } from "@/lib/sportsbook-config";
import { cn, formatCurrency } from "@/lib/utils";
import type { Balance, Transaction } from "@/lib/types";

type BankrollAction = "deposit" | "withdrawal" | "adjustment";

export function SportsbookDetailView({
  sportsbook,
  balance,
  transactions,
  onBack,
  onAction,
}: {
  sportsbook: string;
  balance: Balance | null;
  transactions: Transaction[];
  onBack: () => void;
  onAction: (action: BankrollAction) => void;
}) {
  const currentBalance = balance?.balance ?? 0;
  const pending = balance?.pending ?? 0;

  return (
    <div className="space-y-5 px-4 pb-5">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>

      <section className="rounded-md border border-border/60 bg-background/45 px-4 py-4">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "flex h-9 w-9 items-center justify-center rounded-md text-[11px] font-bold text-white",
              SPORTSBOOK_BADGE_COLORS[sportsbook] ?? "bg-foreground",
            )}
            aria-hidden="true"
          >
            {sportsbookAbbrev(sportsbook)}
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-foreground">{sportsbook}</h3>
            <p className="text-xs text-muted-foreground">Tracked balance</p>
          </div>
        </div>
        <p
          className={cn(
            "mt-4 font-mono text-3xl font-bold tracking-tight tabular-nums",
            currentBalance < 0 ? "text-color-loss-fg" : "text-foreground",
          )}
        >
          {formatCurrency(currentBalance)}
        </p>
        {pending > 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">{formatCurrency(pending)} open cash stake</p>
        ) : null}
      </section>

      <section className="grid grid-cols-3 gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-11 flex-col gap-1 px-1 text-[11px]"
          onClick={() => onAction("deposit")}
        >
          <ArrowDownCircle className="h-4 w-4" />
          Log Deposit
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-11 flex-col gap-1 px-1 text-[11px]"
          onClick={() => onAction("withdrawal")}
        >
          <ArrowUpCircle className="h-4 w-4" />
          Log Withdrawal
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-11 flex-col gap-1 px-1 text-[11px]"
          onClick={() => onAction("adjustment")}
        >
          <SlidersHorizontal className="h-4 w-4" />
          Adjust Balance
        </Button>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-foreground">Recent activity</h3>
        <RecentBankrollActivity
          transactions={transactions.slice(0, 8)}
          emptyLabel={`No bankroll activity for ${sportsbook} yet.`}
        />
      </section>
    </div>
  );
}
