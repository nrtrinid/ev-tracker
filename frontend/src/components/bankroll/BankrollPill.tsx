"use client";

import { Wallet } from "lucide-react";

import { useBankrollDrawer } from "@/components/bankroll/BankrollProvider";
import { useAuth } from "@/lib/auth-context";
import { useBalances } from "@/lib/hooks";
import { cn, formatCurrency } from "@/lib/utils";

export function BankrollPill() {
  const { user } = useAuth();
  const { openBankrollDrawer } = useBankrollDrawer();
  const { data: balances, isLoading, isError } = useBalances({ enabled: !!user });

  if (!user) return null;

  const total =
    balances && balances.length > 0
      ? balances.reduce((sum, balance) => sum + (balance.balance || 0), 0)
      : null;
  const amountLabel = isLoading || isError || total === null ? "--" : formatCurrency(total);
  const ariaAmount = total === null ? "not set" : formatCurrency(total);

  return (
    <button
      type="button"
      data-testid="bankroll-center-pill"
      onClick={() => openBankrollDrawer()}
      className={cn(
        "inline-flex h-8 max-w-[148px] items-center gap-1.5 rounded-full border border-border bg-background/70 px-2.5 text-[11px] font-semibold text-foreground shadow-sm transition-colors",
        "hover:border-primary/40 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      )}
      aria-label={`Open Bankroll Center, current bankroll ${ariaAmount}`}
    >
      <Wallet className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="hidden min-[360px]:inline text-muted-foreground">Bankroll</span>
      <span className="truncate font-mono tabular-nums">{amountLabel}</span>
    </button>
  );
}
