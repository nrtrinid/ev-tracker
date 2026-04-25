"use client";

import { useEffect, useMemo, useState } from "react";

import {
  BankrollTransactionForm,
  type BankrollFormMode,
} from "@/components/bankroll/BankrollTransactionForm";
import { BankrollSummaryView } from "@/components/bankroll/BankrollSummaryView";
import { SportsbookDetailView } from "@/components/bankroll/SportsbookDetailView";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useBalances, useTransactions } from "@/lib/hooks";
import type { Balance, Transaction } from "@/lib/types";

type DrawerView =
  | { name: "summary" }
  | { name: "book"; sportsbook: string }
  | { name: "form"; mode: BankrollFormMode; sportsbook: string | null; returnTo: "summary" | "book" };

const EMPTY_BALANCES: Balance[] = [];
const EMPTY_TRANSACTIONS: Transaction[] = [];

function getViewTitle(view: DrawerView): string {
  if (view.name === "summary") return "Bankroll";
  if (view.name === "book") return view.sportsbook;
  if (view.mode === "deposit") return "Log Deposit";
  if (view.mode === "withdrawal") return "Log Withdrawal";
  return "Adjust Balance";
}

function getViewDescription(view: DrawerView): string {
  if (view.name === "summary") return "Tracked balances and recent activity across sportsbooks.";
  if (view.name === "book") return "Review this book's tracked balance and manual bankroll logs.";
  if (view.mode === "adjustment") return "Set the tracked balance after checking the sportsbook account.";
  return "Log bankroll activity for tracking only.";
}

export function BankrollDrawer({
  open,
  onOpenChange,
  initialSportsbook,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSportsbook: string | null;
}) {
  const [view, setView] = useState<DrawerView>({ name: "summary" });
  const balancesQuery = useBalances({ enabled: open });
  const transactionsQuery = useTransactions(undefined, { enabled: open });

  const balances = balancesQuery.data ?? EMPTY_BALANCES;
  const transactions = transactionsQuery.data ?? EMPTY_TRANSACTIONS;

  useEffect(() => {
    if (!open) return;
    setView(initialSportsbook ? { name: "book", sportsbook: initialSportsbook } : { name: "summary" });
  }, [initialSportsbook, open]);

  const balancesByBook = useMemo(() => {
    return new Map(balances.map((balance) => [balance.sportsbook, balance] as const));
  }, [balances]);

  const selectedSportsbook = view.name === "book" ? view.sportsbook : view.name === "form" ? view.sportsbook : null;
  const selectedBalance: Balance | null = selectedSportsbook ? balancesByBook.get(selectedSportsbook) ?? null : null;
  const selectedTransactions: Transaction[] = selectedSportsbook
    ? transactions.filter((tx) => tx.sportsbook === selectedSportsbook)
    : [];

  const isLoading = balancesQuery.isLoading || transactionsQuery.isLoading;
  const error = (balancesQuery.error ?? transactionsQuery.error) as Error | null;

  const handleRetry = () => {
    void balancesQuery.refetch();
    void transactionsQuery.refetch();
  };

  const handleFormBack = () => {
    if (view.name !== "form") {
      setView({ name: "summary" });
      return;
    }
    if (view.returnTo === "book" && view.sportsbook) {
      setView({ name: "book", sportsbook: view.sportsbook });
      return;
    }
    setView({ name: "summary" });
  };

  const handleFormSuccess = (sportsbook: string) => {
    setView({ name: "book", sportsbook });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        data-testid="bankroll-details-sheet"
        className="mx-auto flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden p-0"
      >
        <SheetHeader className="border-b border-border/60 px-4 pb-3 pr-12 pt-4">
          <SheetTitle className="text-left text-base">{getViewTitle(view)}</SheetTitle>
          <SheetDescription className="text-left text-xs">
            {getViewDescription(view)}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto pt-4">
          {view.name === "summary" ? (
            <BankrollSummaryView
              balances={balances}
              transactions={transactions}
              isLoading={isLoading}
              error={error}
              onRetry={handleRetry}
              onSelectBook={(sportsbook) => setView({ name: "book", sportsbook })}
              onLogDeposit={() => setView({ name: "form", mode: "deposit", sportsbook: null, returnTo: "summary" })}
            />
          ) : null}

          {view.name === "book" ? (
            <SportsbookDetailView
              sportsbook={view.sportsbook}
              balance={selectedBalance}
              transactions={selectedTransactions}
              onBack={() => setView({ name: "summary" })}
              onAction={(mode) => setView({ name: "form", mode, sportsbook: view.sportsbook, returnTo: "book" })}
            />
          ) : null}

          {view.name === "form" ? (
            <BankrollTransactionForm
              mode={view.mode}
              sportsbook={view.sportsbook}
              balances={balances}
              onBack={handleFormBack}
              onSuccess={handleFormSuccess}
            />
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}
