"use client";

import { useMemo, useState } from "react";

import { JourneyCoach } from "@/components/JourneyCoach";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { buildParlayPreview } from "@/lib/parlay-utils";
import { formatCurrency, formatOdds } from "@/lib/utils";

export default function ParlayPage() {
  const { cart, removeCartLeg, clearCart } = useBettingPlatformStore();
  const [stakeInput, setStakeInput] = useState("10");

  const preview = useMemo(() => {
    const parsedStake = Number.parseFloat(stakeInput);
    return buildParlayPreview(cart, parsedStake);
  }, [cart, stakeInput]);

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-2xl space-y-4 px-4 py-6 pb-24">
        <JourneyCoach route="parlay" />

        <div>
          <h1 className="text-2xl font-semibold">Parlay Builder</h1>
          <p className="text-sm text-muted-foreground">
            Build a browser-local cart from straight bets and player props. Same-event combinations stay blocked for now.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold">Preview</h2>
                <p className="text-xs text-muted-foreground">
                  Quick pricing preview from the legs currently in your cart.
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Stake</label>
              <Input
                type="number"
                min="0"
                step="0.01"
                value={stakeInput}
                onChange={(event) => setStakeInput(event.target.value)}
                placeholder="10.00"
              />
            </div>

            {preview ? (
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Legs</p>
                  <p className="mt-1 text-lg font-semibold">{preview.legCount}</p>
                </div>
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Combined odds</p>
                  <p className="mt-1 text-lg font-semibold">{formatOdds(preview.combinedAmericanOdds)}</p>
                </div>
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Total payout</p>
                  <p className="mt-1 text-lg font-semibold">{formatCurrency(preview.totalPayout)}</p>
                </div>
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Net profit</p>
                  <p className="mt-1 text-lg font-semibold text-[#2E5D39]">
                    {formatCurrency(preview.profit)}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Add at least one leg and enter a valid stake to see the combined payout preview.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold">Cart</h2>
                <p className="text-xs text-muted-foreground">
                  Cross-surface legs persist locally in this browser.
                </p>
              </div>
              {cart.length > 0 && (
                <Button variant="outline" size="sm" onClick={clearCart}>
                  Clear
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {cart.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Add legs from the scanner to start building a cross-surface parlay cart.
              </p>
            ) : (
              cart.map((leg) => (
                <div
                  key={leg.id}
                  className="flex items-start justify-between rounded-lg border border-border bg-background px-3 py-3"
                >
                  <div className="space-y-1">
                    <p className="text-sm font-semibold">{leg.display}</p>
                    <p className="text-xs text-muted-foreground">
                      {leg.surface === "player_props" ? "Player Props" : "Straight Bets"} | {leg.sportsbook}
                    </p>
                    <p className="text-xs text-muted-foreground">{leg.event}</p>
                    <p className="text-xs font-mono text-foreground">{formatOdds(leg.oddsAmerican)}</p>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => removeCartLeg(leg.id)}>
                    Remove
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
