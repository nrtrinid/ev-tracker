"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency } from "@/lib/utils";
import { Plus, Trash2, Wallet, ArrowDownCircle, ArrowUpCircle, Target as TargetIcon } from "lucide-react";
import {
  useTransactions,
  useCreateTransaction,
  useDeleteTransaction,
  useBalances,
  useSettings,
  useUpdateSettings,
} from "@/lib/hooks";
import { SPORTSBOOKS } from "@/lib/types";
import type { Transaction, TransactionType } from "@/lib/types";
import { useKellySettings } from "@/lib/kelly-context";

export default function SettingsPage() {
  const { data: transactions } = useTransactions();
  const { data: balances } = useBalances();
  const { data: settings, isLoading: settingsLoading } = useSettings();
  const {
    useComputedBankroll,
    bankrollOverride,
    kellyMultiplier,
    setUseComputedBankroll,
    setBankrollOverride,
    setKellyMultiplier,
  } = useKellySettings();
  const createTransaction = useCreateTransaction();
  const deleteTransaction = useDeleteTransaction();
  const updateSettings = useUpdateSettings();

  // Transaction form state
  const [showTxForm, setShowTxForm] = useState(false);
  const [txType, setTxType] = useState<TransactionType>("deposit");
  const [txSportsbook, setTxSportsbook] = useState("");
  const [txAmount, setTxAmount] = useState("");
  const [txNotes, setTxNotes] = useState("");


  // Settings form state
  const [kFactor, setKFactor] = useState<string>("");

  const handleUpdateKFactor = async () => {
    const value = parseFloat(kFactor);
    if (isNaN(value) || value <= 0 || value > 1) {
      alert("K-factor must be between 0 and 1");
      return;
    }
    await updateSettings.mutateAsync({ k_factor: value });
    setKFactor("");
  };

  const handleAddTransaction = async () => {
    const amount = parseFloat(txAmount);
    if (!txSportsbook || !Number.isFinite(amount) || amount <= 0) {
      return;
    }

    await createTransaction.mutateAsync({
      sportsbook: txSportsbook,
      type: txType,
      amount,
      notes: txNotes.trim() || undefined,
    });

    setTxAmount("");
    setTxNotes("");
    setShowTxForm(false);
  };

  const handleDeleteTransaction = async (tx: Transaction) => {
    await deleteTransaction.mutateAsync(tx.id);
  };

  const computedBankroll = (balances || []).reduce((sum, b) => sum + (b.balance || 0), 0);

  const safeNumber = (value: number | null | undefined, fallback: number) =>
    typeof value === "number" && Number.isFinite(value) ? value : fallback;

  const baselineK = safeNumber(settings?.k_factor, 0.78);
  const observedK =
    typeof settings?.k_factor_observed === "number" && Number.isFinite(settings.k_factor_observed)
      ? settings.k_factor_observed
      : null;
  const blendWeight = safeNumber(settings?.k_factor_weight, 0);
  const effectiveK = safeNumber(settings?.k_factor_effective, baselineK);
  const settledBonusStake = safeNumber(settings?.k_factor_bonus_stake_settled, 0);
  const minStakeForBlend = safeNumber(settings?.k_factor_min_stake, 0);

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-2xl">
        {settingsLoading ? (
          <>
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-4 w-4 rounded" />
                  <Skeleton className="h-5 w-48" />
                </div>
                <Skeleton className="h-4 w-64 mt-1" />
              </CardHeader>
              <CardContent>
                <div className="flex gap-2">
                  <Skeleton className="h-10 flex-1" />
                  <Skeleton className="h-10 w-20" />
                </div>
              </CardContent>
            </Card>

            {/* Transactions Section Skeleton */}
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-4 w-4 rounded" />
                    <Skeleton className="h-5 w-40" />
                  </div>
                  <Skeleton className="h-8 w-16" />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <Skeleton className="h-4 w-32 mb-2" />
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="flex items-center justify-between p-2 rounded border">
                        <div className="flex items-center gap-3">
                          <Skeleton className="h-4 w-4 rounded-full" />
                          <div>
                            <Skeleton className="h-4 w-24 mb-1" />
                            <Skeleton className="h-3 w-32" />
                          </div>
                        </div>
                        <Skeleton className="h-4 w-16" />
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </>
        ) : (
          <>
            {/* K-Factor Setting */}
            <Card>
              <CardHeader className="pb-2">
                <h2 className="font-semibold flex items-center gap-2">
                  <TargetIcon className="h-4 w-4" />
                  Bonus Retention (K-Factor)
                </h2>
                <p className="text-sm text-muted-foreground">
                  How much of a bonus-bet token is expected to convert to real cash. Used for promo EV estimates in the Scanner and when logging bonus bets.
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Mode toggle */}
                <div>
                  <p className="text-sm font-medium mb-2">Mode</p>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={(!settings?.k_factor_mode || settings.k_factor_mode === "baseline") ? "default" : "outline"}
                      onClick={() => updateSettings.mutate({ k_factor_mode: "baseline" })}
                      disabled={updateSettings.isPending}
                    >
                      Baseline
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={settings?.k_factor_mode === "auto" ? "default" : "outline"}
                      onClick={() => updateSettings.mutate({ k_factor_mode: "auto" })}
                      disabled={updateSettings.isPending}
                    >
                      Auto (learn from results)
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1.5">
                    {settings?.k_factor_mode === "auto"
                      ? "Blends your observed retention with the baseline once you have enough sample."
                      : "Always uses the baseline k-factor below."}
                  </p>
                </div>

                {/* Baseline input */}
                <div>
                  <p className="text-sm font-medium mb-1.5">Baseline k-factor</p>
                  <div className="flex gap-2">
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      placeholder="0.78"
                      value={kFactor}
                      onChange={(e) => setKFactor(e.target.value)}
                      className="flex-1"
                    />
                    <Button onClick={handleUpdateKFactor} disabled={!kFactor || updateSettings.isPending}>
                      Update
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Current baseline: <span className="font-mono font-semibold">{baselineK}</span>
                  </p>
                </div>

                {/* Derived k panel */}
                {settings && (
                  <div className="rounded-lg bg-muted p-3 space-y-2">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Your Retention Stats</p>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <p className="text-xs text-muted-foreground">Baseline</p>
                        <p className="font-mono font-semibold">{(baselineK * 100).toFixed(0)}%</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Observed</p>
                        <p className="font-mono font-semibold">
                          {observedK !== null ? (observedK * 100).toFixed(1) + "%" : "—"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Blend weight</p>
                        <p className="font-mono font-semibold">{(blendWeight * 100).toFixed(0)}%</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Effective k</p>
                        <p className="font-mono font-semibold">{(effectiveK * 100).toFixed(1)}%</p>
                      </div>
                      <div className="col-span-2">
                        <span className="text-xs text-muted-foreground">
                          Sample: <span className="font-mono font-semibold">{formatCurrency(settledBonusStake)}</span> in settled bonus-bet stake.
                          {settings?.k_factor_mode === "auto" && blendWeight < 1 && minStakeForBlend > 0 && (
                            <>
                              {" "}
                              Reach {formatCurrency(minStakeForBlend)} in settled bonus-bet stake to start blending.
                            </>
                          )}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Kelly Sizing */}
            <Card>
              <CardHeader className="pb-2">
                <h2 className="font-semibold flex items-center gap-2">
                  <TargetIcon className="h-4 w-4" />
                  Kelly Sizing
                </h2>
                <p className="text-sm text-muted-foreground">
                  Used to compute the “Rec Bet” amount shown in the Scanner.
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Kelly Multiplier */}
                <div>
                  <label className="text-sm text-muted-foreground mb-2 block">
                    Kelly Multiplier
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { v: 0.1, label: "0.10×" },
                      { v: 0.25, label: "0.25× (Quarter)" },
                      { v: 0.5, label: "0.50× (Half)" },
                      { v: 1.0, label: "1.00× (Full)" },
                    ].map((opt) => (
                      <Button
                        key={opt.v}
                        type="button"
                        size="sm"
                        variant={kellyMultiplier === opt.v ? "default" : "outline"}
                        onClick={() => setKellyMultiplier(opt.v)}
                      >
                        {opt.label}
                      </Button>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground mt-2">
                    Current: <span className="font-mono">{kellyMultiplier.toFixed(2)}×</span>
                  </p>
                </div>

                {/* Bankroll source */}
                <div className="pt-2 border-t">
                  <label className="text-sm text-muted-foreground mb-2 block">
                    Bankroll for sizing
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={useComputedBankroll ? "default" : "outline"}
                      onClick={() => setUseComputedBankroll(true)}
                    >
                      Use computed bankroll
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={!useComputedBankroll ? "default" : "outline"}
                      onClick={() => setUseComputedBankroll(false)}
                    >
                      Override bankroll
                    </Button>
                  </div>

                  <div className="mt-3 space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Computed bankroll</span>
                      <span className="font-mono font-semibold">{formatCurrency(computedBankroll)}</span>
                    </div>
                    {!useComputedBankroll && (
                      <div>
                        <label className="text-sm text-muted-foreground mb-1 block">
                          Override amount
                        </label>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          value={Number.isFinite(bankrollOverride) ? bankrollOverride : 0}
                          onChange={(e) => setBankrollOverride(parseFloat(e.target.value) || 0)}
                        />
                      </div>
                    )}
                    <p className="text-xs text-muted-foreground">
                      Active bankroll:{" "}
                      <span className="font-mono font-semibold">
                        {formatCurrency(useComputedBankroll ? computedBankroll : bankrollOverride)}
                      </span>
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Transactions Section */}
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold flex items-center gap-2">
                    <Wallet className="h-4 w-4" />
                    Deposits & Withdrawals
                  </h2>
                  <Button
                    size="sm"
                    variant={showTxForm ? "secondary" : "default"}
                    onClick={() => setShowTxForm(!showTxForm)}
                  >
                    {showTxForm ? "Cancel" : <><Plus className="h-4 w-4 mr-1" /> Add</>}
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Add Transaction Form */}
                {showTxForm && (
                  <div className="p-4 border rounded-lg bg-muted/30 space-y-3">
                    {/* Type Toggle */}
                    <div className="flex gap-2">
                      <Button
                        variant={txType === "deposit" ? "default" : "outline"}
                        size="sm"
                        onClick={() => setTxType("deposit")}
                        className="flex-1"
                      >
                        <ArrowDownCircle className="h-4 w-4 mr-1" />
                        Deposit
                      </Button>
                      <Button
                        variant={txType === "withdrawal" ? "default" : "outline"}
                        size="sm"
                        onClick={() => setTxType("withdrawal")}
                        className="flex-1"
                      >
                        <ArrowUpCircle className="h-4 w-4 mr-1" />
                        Withdrawal
                      </Button>
                    </div>

                    {/* Sportsbook */}
                    <div>
                      <label className="text-sm text-muted-foreground mb-1 block">Sportsbook</label>
                      <div className="flex flex-wrap gap-2">
                        {SPORTSBOOKS.map((book) => (
                          <Button
                            key={book}
                            variant={txSportsbook === book ? "default" : "outline"}
                            size="sm"
                            onClick={() => setTxSportsbook(book)}
                          >
                            {book}
                          </Button>
                        ))}
                      </div>
                    </div>

                    {/* Amount */}
                    <div>
                      <label className="text-sm text-muted-foreground mb-1 block">Amount</label>
                      <Input
                        type="number"
                        step="0.01"
                        min="0"
                        placeholder="100.00"
                        value={txAmount}
                        onChange={(e) => setTxAmount(e.target.value)}
                      />
                    </div>

                    {/* Notes */}
                    <div>
                      <label className="text-sm text-muted-foreground mb-1 block">Notes (optional)</label>
                      <Input
                        type="text"
                        placeholder="Initial deposit, promo credit, etc."
                        value={txNotes}
                        onChange={(e) => setTxNotes(e.target.value)}
                      />
                    </div>

                    {/* Submit */}
                    <Button
                      onClick={handleAddTransaction}
                      disabled={!txSportsbook || !txAmount || createTransaction.isPending}
                      className="w-full"
                    >
                      {createTransaction.isPending ? "Saving..." : `Add ${txType === "deposit" ? "Deposit" : "Withdrawal"}`}
                    </Button>
                  </div>
                )}

                {/* Recent Transactions */}
                <div>
                  <h3 className="text-sm font-medium mb-2">Recent Transactions</h3>
                  {transactions && transactions.length > 0 ? (
                    <div className="space-y-2 max-h-[400px] overflow-y-auto">
                      {transactions.slice(0, 20).map((tx) => (
                        <div
                          key={tx.id}
                          className="flex items-center justify-between p-2 rounded border bg-background hover:bg-muted/50"
                        >
                          <div className="flex items-center gap-3">
                            {tx.type === "deposit" ? (
                              <ArrowDownCircle className="h-4 w-4 text-green-600" />
                            ) : (
                              <ArrowUpCircle className="h-4 w-4 text-red-600" />
                            )}
                            <div>
                              <p className="text-sm font-medium">{tx.sportsbook}</p>
                              <p className="text-xs text-muted-foreground">
                                {new Date(tx.created_at).toLocaleDateString()}
                                {tx.notes && ` • ${tx.notes}`}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className={cn(
                              "text-sm font-semibold",
                              tx.type === "deposit" ? "text-green-600" : "text-red-600"
                            )}>
                              {tx.type === "deposit" ? "+" : "-"}{formatCurrency(tx.amount)}
                            </span>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDeleteTransaction(tx)}
                              className="h-7 w-7 p-0 text-muted-foreground hover:text-red-600"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground text-center py-4">
                      No transactions yet. Add a deposit to get started.
                    </p>
                  )}
                </div>

                {/* Quick Balance Summary */}
                {balances && balances.length > 0 && (
                  <div className="pt-4 border-t">
                    <h3 className="text-sm font-medium mb-2">Balance Summary</h3>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      {balances.map((b) => (
                        <div key={b.sportsbook} className="flex justify-between p-2 rounded bg-muted">
                          <span>{b.sportsbook}</span>
                          <span className={cn("font-medium", b.balance >= 0 ? "text-green-600" : "text-red-600")}>
                            {formatCurrency(b.balance)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </main>
  );
}
