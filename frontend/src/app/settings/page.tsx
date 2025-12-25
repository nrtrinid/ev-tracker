"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn, formatCurrency } from "@/lib/utils";
import { Plus, Trash2, Wallet, ArrowDownCircle, ArrowUpCircle, Target as TargetIcon } from "lucide-react";
import { useTransactions, useCreateTransaction, useDeleteTransaction, useBalances, useSettings, useUpdateSettings } from "@/lib/hooks";
import { SPORTSBOOKS } from "@/lib/types";
import type { TransactionType } from "@/lib/types";

export default function SettingsPage() {
  const { data: transactions, isLoading: txLoading } = useTransactions();
  const { data: balances } = useBalances();
  const { data: settings, isLoading: settingsLoading } = useSettings();
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

  const handleAddTransaction = async () => {
    if (!txSportsbook || !txAmount || parseFloat(txAmount) <= 0) return;

    await createTransaction.mutateAsync({
      sportsbook: txSportsbook,
      type: txType,
      amount: parseFloat(txAmount),
      notes: txNotes || undefined,
    });

    // Reset form
    setTxSportsbook("");
    setTxAmount("");
    setTxNotes("");
    setShowTxForm(false);
  };

  const handleDeleteTransaction = async (id: string) => {
    if (confirm("Delete this transaction?")) {
      await deleteTransaction.mutateAsync(id);
    }
  };

  const handleUpdateKFactor = async () => {
    const value = parseFloat(kFactor);
    if (isNaN(value) || value <= 0 || value > 1) {
      alert("K-factor must be between 0 and 1");
      return;
    }
    await updateSettings.mutateAsync({ k_factor: value });
    setKFactor("");
  };

  const isLoading = txLoading || settingsLoading;

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-2xl">
        {isLoading ? (
          <div className="text-center py-12 text-muted-foreground">Loading...</div>
        ) : (
          <>
            {/* K-Factor Setting */}
            <Card>
              <CardHeader className="pb-2">
                <h2 className="font-semibold flex items-center gap-2">
                  <TargetIcon className="h-4 w-4" />
                  K-Factor (Bonus Bet Retention)
                </h2>
                <p className="text-sm text-muted-foreground">
                  Current: <strong>{settings?.k_factor || 0.78}</strong> — Used for No-Sweat and bonus bet calculations
                </p>
              </CardHeader>
              <CardContent>
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
                              onClick={() => handleDeleteTransaction(tx.id)}
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

function Target(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  );
}
