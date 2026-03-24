"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Lock } from "lucide-react";
import { toast } from "sonner";

import { JourneyCoach } from "@/components/JourneyCoach";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useBalances } from "@/lib/hooks";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useKellySettings } from "@/lib/kelly-context";
import {
  buildParlayEventSummary,
  buildParlayPreview,
  buildParlaySportLabel,
  getParlayRecommendedStake,
} from "@/lib/parlay-utils";
import type { ParlayCartLeg, ScannedBetData } from "@/lib/types";
import { formatCurrency, formatOdds } from "@/lib/utils";

function cloneCartLegs(legs: ParlayCartLeg[]) {
  return legs.map((leg) => ({
    ...leg,
    correlationTags: [...leg.correlationTags],
    selectionMeta:
      leg.selectionMeta && typeof leg.selectionMeta === "object"
        ? { ...leg.selectionMeta }
        : leg.selectionMeta,
  }));
}

function formatPercent(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return "Unavailable";
  }
  const rounded = value >= 0 ? `+${value.toFixed(1)}` : value.toFixed(1);
  return `${rounded}%`;
}

function buildParlayLogInitialValues(cart: ParlayCartLeg[], stake: number | null): ScannedBetData | undefined {
  const preview = buildParlayPreview(cart, stake ?? Number.NaN);
  if (!preview) {
    return undefined;
  }

  return {
    surface: "parlay",
    sportsbook: preview.sportsbook ?? cart[0]?.sportsbook ?? "",
    sport: buildParlaySportLabel(cart),
    event: buildParlayEventSummary(cart, preview.sportsbook),
    market: "Parlay",
    odds_american: preview.combinedAmericanOdds,
    promo_type: "standard",
    true_prob_at_entry: preview.estimatedTrueProbability ?? undefined,
    selection_meta: {
      type: "parlay",
      sportsbook: preview.sportsbook,
      legs: cloneCartLegs(cart),
      warnings: preview.warnings,
      pricingPreview: preview,
    },
    stealth_kelly_stake: stake ?? undefined,
  };
}

export default function ParlayPage() {
  const {
    cart,
    cartStakeInput,
    removeCartLeg,
    clearCart,
    setCartStakeInput,
  } = useBettingPlatformStore();
  const { data: balances } = useBalances();
  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loggingInitialValues, setLoggingInitialValues] = useState<ScannedBetData | undefined>(undefined);
  const lastAutoFilledStakeRef = useRef<string | null>(null);
  const lastAutoFillKeyRef = useRef<string | null>(null);

  const parsedStake = Number.parseFloat(cartStakeInput);
  const computedBankroll = useMemo(() => {
    if (!balances || balances.length === 0) return 0;
    return balances.reduce((sum, balance) => sum + (balance.balance || 0), 0);
  }, [balances]);
  const bankroll = useComputedBankroll ? computedBankroll : bankrollOverride;
  const preview = useMemo(
    () => buildParlayPreview(cart, parsedStake, { bankroll, kellyMultiplier }),
    [bankroll, cart, kellyMultiplier, parsedStake],
  );
  const recommendedStake = useMemo(() => getParlayRecommendedStake(preview), [preview]);
  const autoFillKey = useMemo(
    () => `${cart.map((leg) => leg.id).join("|")}::${bankroll ?? "none"}::${kellyMultiplier ?? "none"}`,
    [bankroll, cart, kellyMultiplier],
  );
  const lockedSportsbook = cart[0]?.sportsbook ?? null;

  useEffect(() => {
    if (cart.length === 0) {
      lastAutoFilledStakeRef.current = null;
      lastAutoFillKeyRef.current = null;
      return;
    }

    if (recommendedStake == null) {
      lastAutoFilledStakeRef.current = null;
      lastAutoFillKeyRef.current = autoFillKey;
      return;
    }

    const nextStakeInput = recommendedStake.toFixed(2);
    const keyChanged = lastAutoFillKeyRef.current !== autoFillKey;
    const followsAutoFill =
      cartStakeInput.trim() === "" ||
      !Number.isFinite(parsedStake) ||
      cartStakeInput === lastAutoFilledStakeRef.current;

    if (!keyChanged && !followsAutoFill) {
      return;
    }

    lastAutoFilledStakeRef.current = nextStakeInput;
    lastAutoFillKeyRef.current = autoFillKey;
    if (cartStakeInput !== nextStakeInput) {
      setCartStakeInput(nextStakeInput);
    }
  }, [autoFillKey, cart.length, cartStakeInput, parsedStake, recommendedStake, setCartStakeInput]);

  async function handleOpenLogDrawer() {
    if (!preview || preview.stake == null || preview.stake <= 0) {
      toast.error("Enter a valid stake before logging this parlay.");
      return;
    }

    setLoggingInitialValues(buildParlayLogInitialValues(cart, preview.stake));
    setDrawerOpen(true);
  }

  const hasCart = cart.length > 0;
  const canOpenLogDrawer = hasCart && preview?.stake != null && preview.stake > 0;

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-4xl space-y-4 px-4 py-6 pb-24">
        <JourneyCoach route="parlay" />

        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Parlay Builder</h1>
          <p className="text-sm text-muted-foreground">
            Build one-book parlays from straight bets and sportsbook props, review the pricing, and log the finished ticket into your tracker when you place it.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <div className="space-y-1">
              <div>
                <h2 className="font-semibold">Active Slip</h2>
                <p className="text-xs text-muted-foreground">
                  {lockedSportsbook
                    ? `Sportsbook lock: ${lockedSportsbook}`
                    : "Add the first leg from the scanner to lock this slip to a sportsbook."}
                </p>
                <p className="text-xs text-muted-foreground">
                  This builder stays local on this device until you log the parlay.
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Legs</p>
                  <p className="mt-1 text-lg font-semibold">{preview?.legCount ?? 0}</p>
                </div>
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Book odds</p>
                  <p className="mt-1 text-lg font-semibold">
                    {preview ? formatOdds(preview.combinedAmericanOdds) : "-"}
                  </p>
                </div>
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Payout</p>
                  <p className="mt-1 text-lg font-semibold">
                    {preview?.totalPayout != null ? formatCurrency(preview.totalPayout) : "-"}
                  </p>
                </div>
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <p className="text-xs text-muted-foreground">Profit</p>
                  <p className="mt-1 text-lg font-semibold text-[#2E5D39]">
                    {preview?.profit != null ? formatCurrency(preview.profit) : "-"}
                  </p>
                </div>
              </div>

              <div className="space-y-2 rounded-xl border border-border bg-background px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-xs font-medium text-muted-foreground">Stake</label>
                  {recommendedStake != null ? (
                    <p className="text-[11px] text-muted-foreground">
                      Suggested: {formatCurrency(recommendedStake)}
                    </p>
                  ) : null}
                </div>
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={cartStakeInput}
                  onChange={(event) => setCartStakeInput(event.target.value)}
                  placeholder="10.00"
                />
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-border bg-background px-4 py-3">
                <p className="text-xs text-muted-foreground">Estimated fair odds</p>
                <p className="mt-1 text-lg font-semibold">
                  {preview?.estimateAvailable && preview.estimatedFairAmericanOdds != null
                    ? formatOdds(preview.estimatedFairAmericanOdds)
                    : "Unavailable"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {preview?.estimateAvailable
                    ? "Independence estimate from leg reference prices."
                    : preview?.estimateUnavailableReason === "Correlation warning"
                    ? "Same-event or clearly correlated legs suppress the estimate."
                    : preview?.estimateUnavailableReason === "Missing reference price"
                    ? "At least one leg is missing a reference price."
                    : "Add a slip to see whether fair-odds estimation is available."}
                </p>
              </div>

              <div className="rounded-xl border border-border bg-background px-4 py-3">
                <p className="text-xs text-muted-foreground">Estimated EV</p>
                <p className="mt-1 text-lg font-semibold">
                  {preview?.estimateAvailable ? formatPercent(preview.estimatedEvPercent) : "Unavailable"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {preview?.estimateAvailable
                    ? `Based on ${preview.legCount} uncorrelated reference prices.`
                    : "The book payout still shows above; only the fair-odds estimate is hidden."}
                </p>
              </div>
            </div>

            {preview?.warnings.length ? (
              <div className="rounded-xl border border-[#B85C38]/20 bg-[#B85C38]/10 px-4 py-3">
                <div className="flex items-center gap-2 text-[#8B3D20]">
                  <AlertTriangle className="h-4 w-4" />
                  <p className="text-sm font-semibold">Correlation warnings</p>
                </div>
                <div className="mt-3 space-y-2">
                  {preview.warnings.map((warning) => (
                    <div key={`${warning.code}-${warning.relatedLegIds.join("-")}`} className="rounded-lg border border-[#B85C38]/15 bg-background/60 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-foreground">{warning.title}</p>
                        <span className="rounded-full border border-[#B85C38]/20 px-2 py-0.5 text-[11px] uppercase tracking-[0.14em] text-[#8B3D20]">
                          {warning.severity}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{warning.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <Button
                onClick={handleOpenLogDrawer}
                disabled={!canOpenLogDrawer}
              >
                <Lock className="mr-2 h-4 w-4" />
                Review & Log Parlay
              </Button>
              <Button
                variant="ghost"
                onClick={clearCart}
                disabled={!hasCart}
              >
                Clear Cart
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold">Cart Legs</h2>
                <p className="text-xs text-muted-foreground">
                  Same-event legs are allowed, but they trigger warnings and suppress fair-odds estimates.
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {cart.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Add legs from the scanner to start building a one-book parlay slip.
              </p>
            ) : (
              cart.map((leg) => (
                <div
                  key={leg.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-border bg-background px-3 py-3"
                >
                  <div className="space-y-1">
                    <p className="text-sm font-semibold">{leg.display}</p>
                    <p className="text-xs text-muted-foreground">
                      {leg.surface === "player_props" ? "Player Props" : "Straight Bets"} | {leg.sportsbook}
                    </p>
                    <p className="text-xs text-muted-foreground">{leg.event}</p>
                    <div className="flex flex-wrap gap-3 text-xs">
                      <span className="font-mono text-foreground">{formatOdds(leg.oddsAmerican)}</span>
                      <span className="text-muted-foreground">
                        Fair: {leg.referenceOddsAmerican != null ? formatOdds(leg.referenceOddsAmerican) : "Unavailable"}
                      </span>
                    </div>
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

      <LogBetDrawer
        open={drawerOpen}
        onOpenChange={(open) => {
          setDrawerOpen(open);
          if (!open) {
            setLoggingInitialValues(undefined);
          }
        }}
        initialValues={loggingInitialValues}
        onLogged={() => {
          setLoggingInitialValues(undefined);
          clearCart();
          setCartStakeInput("10.00");
        }}
      />
    </main>
  );
}
