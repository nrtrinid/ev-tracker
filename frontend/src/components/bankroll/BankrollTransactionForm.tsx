"use client";

import { FormEvent, useMemo, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCreateTransaction } from "@/lib/hooks";
import { SPORTSBOOKS } from "@/lib/types";
import type { Balance, TransactionCreate, TransactionType } from "@/lib/types";
import { cn, formatCurrency } from "@/lib/utils";

export type BankrollFormMode = "deposit" | "withdrawal" | "adjustment";

const MODE_COPY: Record<BankrollFormMode, {
  title: string;
  amountLabel: string;
  amountPlaceholder: string;
  submitLabel: string;
  successLabel: string;
}> = {
  deposit: {
    title: "Log Deposit",
    amountLabel: "Amount",
    amountPlaceholder: "100.00",
    submitLabel: "Log Deposit",
    successLabel: "Deposit logged",
  },
  withdrawal: {
    title: "Log Withdrawal",
    amountLabel: "Amount",
    amountPlaceholder: "50.00",
    submitLabel: "Log Withdrawal",
    successLabel: "Withdrawal logged",
  },
  adjustment: {
    title: "Adjust Balance",
    amountLabel: "Set tracked balance to",
    amountPlaceholder: "842.17",
    submitLabel: "Adjust Balance",
    successLabel: "Tracked balance adjusted",
  },
};

function parseAmount(value: string): number | null {
  if (!value.trim()) return null;
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : null;
}

export function BankrollTransactionForm({
  mode,
  sportsbook,
  balances,
  onBack,
  onSuccess,
}: {
  mode: BankrollFormMode;
  sportsbook: string | null;
  balances: Balance[];
  onBack: () => void;
  onSuccess: (sportsbook: string) => void;
}) {
  const [selectedSportsbook, setSelectedSportsbook] = useState(sportsbook ?? "");
  const [amountInput, setAmountInput] = useState("");
  const [notes, setNotes] = useState("");
  const createTransaction = useCreateTransaction();
  const copy = MODE_COPY[mode];

  const currentBalance = useMemo(() => {
    return balances.find((balance) => balance.sportsbook === selectedSportsbook)?.balance ?? 0;
  }, [balances, selectedSportsbook]);

  const parsedAmount = parseAmount(amountInput);
  const adjustmentDelta =
    mode === "adjustment" && parsedAmount !== null
      ? Number((parsedAmount - currentBalance).toFixed(2))
      : null;

  const validationError = useMemo(() => {
    if (!selectedSportsbook) return "Choose a sportsbook.";
    if (parsedAmount === null) return "Enter an amount.";
    if (mode !== "adjustment" && parsedAmount <= 0) return "Amount must be positive.";
    if (mode === "withdrawal" && parsedAmount > currentBalance) {
      return "Withdrawal would make the tracked balance negative.";
    }
    if (mode === "adjustment") {
      if (parsedAmount < 0) return "Tracked balance cannot be negative.";
      if (adjustmentDelta === 0) return "Enter a different tracked balance.";
      if (adjustmentDelta !== null && currentBalance + adjustmentDelta < 0) {
        return "Adjustment would make the tracked balance negative.";
      }
    }
    return null;
  }, [adjustmentDelta, currentBalance, mode, parsedAmount, selectedSportsbook]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (validationError || parsedAmount === null || !selectedSportsbook) return;

    const type: TransactionType = mode === "adjustment" ? "adjustment" : mode;
    const amount = mode === "adjustment" ? adjustmentDelta : parsedAmount;
    if (amount === null) return;

    const payload: TransactionCreate = {
      sportsbook: selectedSportsbook,
      type,
      amount,
      notes: notes.trim() || undefined,
    };

    try {
      await createTransaction.mutateAsync(payload);
      toast.success(copy.successLabel);
      setAmountInput("");
      setNotes("");
      onSuccess(selectedSportsbook);
    } catch (error) {
      toast.error("Could not log bankroll activity", {
        description: error instanceof Error ? error.message : "Try again.",
      });
    }
  };

  return (
    <form className="space-y-5 px-4 pb-5" onSubmit={handleSubmit}>
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>

      <section className="space-y-4 rounded-md border border-border/60 bg-background/45 px-4 py-4">
        <div>
          <h3 className="text-base font-semibold text-foreground">{copy.title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Current tracked balance: <span className="font-mono font-semibold text-foreground">{formatCurrency(currentBalance)}</span>
          </p>
        </div>

        {!sportsbook ? (
          <div>
            <label className="mb-2 block text-sm font-medium text-muted-foreground">Sportsbook</label>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {SPORTSBOOKS.map((book) => (
                <button
                  key={book}
                  type="button"
                  onClick={() => setSelectedSportsbook(book)}
                  className={cn(
                    "shrink-0 rounded-md border px-3 py-1.5 text-xs font-semibold transition-colors",
                    selectedSportsbook === book
                      ? "border-primary/50 bg-primary/15 text-foreground"
                      : "border-border bg-background text-muted-foreground hover:text-foreground",
                  )}
                >
                  {book}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div>
          <label htmlFor="bankroll-amount" className="mb-1.5 block text-sm font-medium text-muted-foreground">
            {copy.amountLabel}
          </label>
          <Input
            id="bankroll-amount"
            type="number"
            inputMode="decimal"
            min={mode === "adjustment" ? "0" : "0.01"}
            step="0.01"
            placeholder={copy.amountPlaceholder}
            value={amountInput}
            onChange={(event) => setAmountInput(event.target.value)}
            className="h-11"
          />
          {mode === "adjustment" && adjustmentDelta !== null && adjustmentDelta !== 0 ? (
            <p className="mt-1.5 text-xs text-muted-foreground">
              Adjustment delta:{" "}
              <span className={cn("font-mono font-semibold", adjustmentDelta >= 0 ? "text-color-profit-fg" : "text-color-loss-fg")}>
                {adjustmentDelta >= 0 ? "+" : ""}
                {formatCurrency(adjustmentDelta)}
              </span>
            </p>
          ) : null}
        </div>

        <div>
          <label htmlFor="bankroll-notes" className="mb-1.5 block text-sm font-medium text-muted-foreground">
            Note
          </label>
          <Input
            id="bankroll-notes"
            type="text"
            placeholder={mode === "adjustment" ? "Correction, promo credit, manual check" : "Optional"}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="h-11"
          />
        </div>

        {validationError ? (
          <p className="rounded-md border border-color-loss/30 bg-color-loss-subtle px-3 py-2 text-xs text-color-loss-fg">
            {validationError}
          </p>
        ) : null}
      </section>

      <div className="flex gap-2">
        <Button type="button" variant="outline" className="flex-1" onClick={onBack}>
          Cancel
        </Button>
        <Button type="submit" className="flex-1" disabled={!!validationError || createTransaction.isPending}>
          {createTransaction.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : copy.submitLabel}
        </Button>
      </div>
    </form>
  );
}
