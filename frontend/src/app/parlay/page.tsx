"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Copy, Loader2, Lock, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { JourneyCoach } from "@/components/JourneyCoach";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  useCreateParlaySlip,
  useDeleteParlaySlip,
  useLogParlaySlip,
  useParlaySlips,
  useUpdateParlaySlip,
} from "@/lib/hooks";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import {
  buildParlayEventSummary,
  buildParlayPreview,
  buildParlaySportLabel,
} from "@/lib/parlay-utils";
import type { BetCreate, ParlayCartLeg, ParlaySlip, ScannedBetData } from "@/lib/types";
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

function formatSlipUpdatedAt(value: string) {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
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
    activeParlaySlipId,
    removeCartLeg,
    clearCart,
    replaceCart,
    setCartStakeInput,
    setActiveParlaySlipId,
  } = useBettingPlatformStore();
  const { data: savedSlips = [], isLoading: savedSlipsLoading } = useParlaySlips();
  const createParlaySlip = useCreateParlaySlip();
  const updateParlaySlip = useUpdateParlaySlip();
  const deleteParlaySlip = useDeleteParlaySlip();
  const logParlaySlip = useLogParlaySlip();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loggingInitialValues, setLoggingInitialValues] = useState<ScannedBetData | undefined>(undefined);

  const parsedStake = Number.parseFloat(cartStakeInput);
  const preview = useMemo(() => buildParlayPreview(cart, parsedStake), [cart, parsedStake]);
  const lockedSportsbook = cart[0]?.sportsbook ?? null;
  const activeSlip = savedSlips.find((slip) => slip.id === activeParlaySlipId) ?? null;
  const saveActionLabel = activeSlip
    ? activeSlip.logged_bet_id
      ? "Save As New Draft"
      : "Update Draft"
    : "Save Draft";
  const isSaving = createParlaySlip.isPending || updateParlaySlip.isPending;
  const isDeleting = deleteParlaySlip.isPending;
  const isLogging = logParlaySlip.isPending;

  async function saveCurrentSlip(options?: { silent?: boolean; overrideStake?: number }) {
    const stakeForSave = options?.overrideStake ?? parsedStake;
    const previewForSave = buildParlayPreview(cart, stakeForSave);

    if (!previewForSave || !lockedSportsbook) {
      if (!options?.silent) {
        toast.error("Add at least one leg before saving a draft.");
      }
      return null;
    }

    const payload = {
      sportsbook: lockedSportsbook,
      stake: previewForSave.stake,
      legs: cloneCartLegs(cart),
      warnings: previewForSave.warnings,
      pricingPreview: previewForSave,
    };

    try {
      const shouldCreateNew = !activeSlip || activeSlip.logged_bet_id != null;
      const savedSlip = shouldCreateNew
        ? await createParlaySlip.mutateAsync(payload)
        : await updateParlaySlip.mutateAsync({
            id: activeSlip.id,
            data: payload,
          });

      setActiveParlaySlipId(savedSlip.id);
      if (!options?.silent) {
        toast.success(shouldCreateNew ? "Draft saved." : "Draft updated.");
      }
      return savedSlip;
    } catch (error) {
      if (!options?.silent) {
        toast.error(error instanceof Error ? error.message : "Failed to save draft.");
      }
      return null;
    }
  }

  async function handleSaveDraft() {
    await saveCurrentSlip();
  }

  async function handleOpenLogDrawer() {
    if (!preview || preview.stake == null || preview.stake <= 0) {
      toast.error("Enter a valid stake before logging this parlay.");
      return;
    }

    setLoggingInitialValues(buildParlayLogInitialValues(cart, preview.stake));
    setDrawerOpen(true);
  }

  async function handleSubmitLoggedParlay(payload: BetCreate) {
    const savedSlip = await saveCurrentSlip({
      silent: true,
      overrideStake: payload.stake,
    });

    if (!savedSlip) {
      throw new Error("Unable to save this parlay before logging it.");
    }

    await logParlaySlip.mutateAsync({
      id: savedSlip.id,
      data: {
        sport: payload.sport,
        event: payload.event,
        promo_type: payload.promo_type,
        odds_american: payload.odds_american,
        stake: payload.stake,
        boost_percent: payload.boost_percent,
        winnings_cap: payload.winnings_cap,
        notes: payload.notes,
        event_date: payload.event_date,
        opposing_odds: payload.opposing_odds,
        payout_override: payload.payout_override,
      },
    });
    setActiveParlaySlipId(savedSlip.id);
  }

  function handleLoadSlip(slip: ParlaySlip) {
    replaceCart(cloneCartLegs(slip.legs), {
      stakeInput: slip.stake != null ? slip.stake.toFixed(2) : "",
      activeParlaySlipId: slip.logged_bet_id ? null : slip.id,
    });
    toast.success(slip.logged_bet_id ? "Logged slip copied into the builder." : "Draft loaded into the builder.");
  }

  function handleDuplicateSlip(slip: ParlaySlip) {
    replaceCart(cloneCartLegs(slip.legs), {
      stakeInput: slip.stake != null ? slip.stake.toFixed(2) : "",
      activeParlaySlipId: null,
    });
    toast.success("Slip copied into a new local draft.");
  }

  async function handleDeleteSlip(slip: ParlaySlip) {
    try {
      await deleteParlaySlip.mutateAsync(slip.id);
      if (activeParlaySlipId === slip.id) {
        setActiveParlaySlipId(null);
      }
      toast.success("Draft deleted.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to delete draft.");
    }
  }

  const hasCart = cart.length > 0;

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-4xl space-y-4 px-4 py-6 pb-24">
        <JourneyCoach route="parlay" />

        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Parlay Builder</h1>
          <p className="text-sm text-muted-foreground">
            Build one-book parlays from straight bets and sportsbook props, save drafts across devices, and log the finished slip when you place it.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">Active Slip</h2>
                <p className="text-xs text-muted-foreground">
                  {lockedSportsbook
                    ? `Sportsbook lock: ${lockedSportsbook}`
                    : "Add the first leg from the scanner to lock this slip to a sportsbook."}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {activeSlip && !activeSlip.logged_bet_id && (
                  <span className="rounded-full border border-border bg-muted/40 px-3 py-1 text-muted-foreground">
                    Saved draft
                  </span>
                )}
                {activeSlip?.logged_bet_id && (
                  <span className="rounded-full border border-[#2E5D39]/20 bg-[#2E5D39]/10 px-3 py-1 text-[#2E5D39]">
                    Logged draft
                  </span>
                )}
                {!activeSlip && hasCart && (
                  <span className="rounded-full border border-border bg-muted/40 px-3 py-1 text-muted-foreground">
                    Local only
                  </span>
                )}
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
                <label className="text-xs font-medium text-muted-foreground">Stake</label>
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
                variant="outline"
                onClick={handleSaveDraft}
                disabled={!hasCart || isSaving || isLogging}
              >
                {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
                {saveActionLabel}
              </Button>
              <Button
                onClick={handleOpenLogDrawer}
                disabled={!hasCart || preview?.stake == null || isSaving || isLogging}
              >
                {isLogging ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Lock className="mr-2 h-4 w-4" />}
                Log Parlay
              </Button>
              <Button
                variant="ghost"
                onClick={clearCart}
                disabled={!hasCart || isSaving || isLogging}
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
                        Ref: {leg.referenceOddsAmerican != null ? formatOdds(leg.referenceOddsAmerican) : "Unavailable"}
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

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold">Saved Slips</h2>
                <p className="text-xs text-muted-foreground">
                  Drafts live on the backend so you can reopen them across devices.
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {savedSlipsLoading ? (
              <p className="text-sm text-muted-foreground">Loading saved slips...</p>
            ) : savedSlips.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No saved slips yet. Save the active cart when you want to keep a draft around.
              </p>
            ) : (
              savedSlips.map((slip) => {
                const slipPreview = slip.pricingPreview;
                const isLogged = slip.logged_bet_id != null;
                return (
                  <div key={slip.id} className="rounded-xl border border-border bg-background px-3 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-semibold">{buildParlayEventSummary(slip.legs, slip.sportsbook)}</p>
                          <span className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
                            {slip.sportsbook}
                          </span>
                          {isLogged && (
                            <span className="rounded-full border border-[#2E5D39]/20 bg-[#2E5D39]/10 px-2 py-0.5 text-[11px] text-[#2E5D39]">
                              Logged
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {slip.legs.length} legs | Updated {formatSlipUpdatedAt(slip.updated_at)}
                        </p>
                        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                          <span>Book: {slipPreview ? formatOdds(slipPreview.combinedAmericanOdds) : "-"}</span>
                          <span>Stake: {slip.stake != null ? formatCurrency(slip.stake) : "-"}</span>
                          <span>EV: {slipPreview?.estimateAvailable ? formatPercent(slipPreview.estimatedEvPercent) : "Unavailable"}</span>
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {!isLogged && (
                          <Button variant="outline" size="sm" onClick={() => handleLoadSlip(slip)}>
                            Load
                          </Button>
                        )}
                        <Button variant="outline" size="sm" onClick={() => handleDuplicateSlip(slip)}>
                          <Copy className="mr-2 h-4 w-4" />
                          Duplicate
                        </Button>
                        {!isLogged && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteSlip(slip)}
                            disabled={isDeleting}
                          >
                            {isDeleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                            Delete
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
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
        onSubmitOverride={handleSubmitLoggedParlay}
        onLogged={() => {
          setLoggingInitialValues(undefined);
        }}
      />
    </main>
  );
}
