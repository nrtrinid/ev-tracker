"use client";

import { ArrowDownCircle, ArrowUpCircle, SlidersHorizontal } from "lucide-react";

import { cn, formatCurrency } from "@/lib/utils";
import type { Transaction } from "@/lib/types";

function formatActivityDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function transactionMeta(tx: Transaction) {
  if (tx.type === "deposit") {
    return {
      label: "Deposit logged",
      Icon: ArrowDownCircle,
      amount: `+${formatCurrency(tx.amount)}`,
      className: "text-color-profit-fg",
    };
  }
  if (tx.type === "withdrawal") {
    return {
      label: "Withdrawal logged",
      Icon: ArrowUpCircle,
      amount: `-${formatCurrency(tx.amount)}`,
      className: "text-color-loss-fg",
    };
  }
  return {
    label: "Balance adjusted",
    Icon: SlidersHorizontal,
    amount: `${tx.amount >= 0 ? "+" : ""}${formatCurrency(tx.amount)}`,
    className: tx.amount >= 0 ? "text-color-profit-fg" : "text-color-loss-fg",
  };
}

export function RecentBankrollActivity({
  transactions,
  emptyLabel = "No bankroll activity yet.",
}: {
  transactions: Transaction[];
  emptyLabel?: string;
}) {
  if (transactions.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 bg-muted/10 px-3 py-5 text-center">
        <p className="text-sm text-muted-foreground">{emptyLabel}</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/50 rounded-md border border-border/60 bg-background/45">
      {transactions.map((tx) => {
        const meta = transactionMeta(tx);
        const Icon = meta.Icon;
        return (
          <div key={tx.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <Icon className={cn("h-4 w-4 shrink-0", meta.className)} />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">{meta.label}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {tx.sportsbook} - {formatActivityDate(tx.transaction_date ?? tx.created_at)}
                  {tx.notes ? ` - ${tx.notes}` : ""}
                </p>
              </div>
            </div>
            <span className={cn("shrink-0 font-mono text-sm font-semibold tabular-nums", meta.className)}>
              {meta.amount}
            </span>
          </div>
        );
      })}
    </div>
  );
}
