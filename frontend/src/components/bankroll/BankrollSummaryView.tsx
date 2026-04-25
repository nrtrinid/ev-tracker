"use client";

import { Plus } from "lucide-react";

import { RecentBankrollActivity } from "@/components/bankroll/RecentBankrollActivity";
import { SportsbookBalanceRow } from "@/components/bankroll/SportsbookBalanceRow";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency } from "@/lib/utils";
import type { Balance, Transaction } from "@/lib/types";

export function BankrollSummaryView({
  balances,
  transactions,
  isLoading,
  error,
  onRetry,
  onSelectBook,
  onLogDeposit,
}: {
  balances: Balance[];
  transactions: Transaction[];
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
  onSelectBook: (sportsbook: string) => void;
  onLogDeposit: () => void;
}) {
  const total = balances.length > 0
    ? balances.reduce((sum, balance) => sum + (balance.balance || 0), 0)
    : null;
  const atRisk = balances.reduce((sum, balance) => sum + (balance.pending || 0), 0);

  if (isLoading) {
    return (
      <div className="space-y-4 px-4 pb-5">
        <div className="rounded-md border border-border/60 bg-background/45 px-4 py-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-8 w-36" />
        </div>
        <div className="space-y-2">
          {[0, 1, 2].map((idx) => (
            <Skeleton key={idx} className="h-[58px] rounded-md" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3 px-4 pb-5">
        <div className="rounded-md border border-color-loss/30 bg-color-loss-subtle px-4 py-3">
          <p className="text-sm font-semibold text-color-loss-fg">Bankroll could not load.</p>
          <p className="mt-1 text-xs text-color-loss-fg/80">{error.message}</p>
        </div>
        <Button type="button" variant="outline" onClick={onRetry} className="w-full">
          Try Again
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5 px-4 pb-5">
      <section className="rounded-md border border-border/60 bg-background/45 px-4 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Total bankroll</p>
        <div className="mt-2 flex items-end justify-between gap-3">
          <p
            className={cn(
              "font-mono text-3xl font-bold tracking-tight tabular-nums",
              total !== null && total < 0 ? "text-color-loss-fg" : "text-foreground",
            )}
          >
            {total === null ? "--" : formatCurrency(total)}
          </p>
          {atRisk > 0 ? (
            <p className="pb-1 text-right text-xs text-muted-foreground">
              {formatCurrency(atRisk)} at risk
            </p>
          ) : null}
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-foreground">Sportsbooks</h3>
          <Button type="button" variant="ghost" size="sm" onClick={onLogDeposit} className="h-8 px-2">
            <Plus className="mr-1 h-3.5 w-3.5" />
            Log Deposit
          </Button>
        </div>
        {balances.length > 0 ? (
          <div className="space-y-2">
            {balances.map((balance) => (
              <SportsbookBalanceRow
                key={balance.sportsbook}
                balance={balance}
                onSelect={onSelectBook}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-border/60 bg-muted/10 px-4 py-8 text-center">
            <p className="text-sm font-medium text-foreground">No sportsbook balances yet</p>
            <p className="mt-1 text-xs text-muted-foreground">Log a deposit to start tracking bankroll.</p>
            <Button type="button" size="sm" className="mt-4" onClick={onLogDeposit}>
              <Plus className="mr-1.5 h-4 w-4" />
              Log Deposit
            </Button>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-foreground">Recent bankroll activity</h3>
        <RecentBankrollActivity
          transactions={transactions.slice(0, 6)}
          emptyLabel="No bankroll activity yet."
        />
      </section>
    </div>
  );
}
