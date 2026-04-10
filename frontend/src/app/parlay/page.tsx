"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, BookOpen, Layers, Lock, Minus, TrendingUp } from "lucide-react";
import { toast } from "sonner";

import { JourneyCoach } from "@/components/JourneyCoach";
import { LogBetDrawer } from "@/components/LogBetDrawer";
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
import { cn, formatCurrency, formatOdds } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

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
  if (value == null || Number.isNaN(value)) return null;
  const rounded = value >= 0 ? `+${value.toFixed(1)}` : value.toFixed(1);
  return `${rounded}%`;
}

function buildParlayLogInitialValues(cart: ParlayCartLeg[], stake: number | null): ScannedBetData | undefined {
  const preview = buildParlayPreview(cart, stake ?? Number.NaN);
  if (!preview || preview.slipMode === "pickem_notes" || preview.combinedAmericanOdds == null) {
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

// ── Stat tile ─────────────────────────────────────────────────────────────────

function StatTile({
  label,
  value,
  valueClass,
  mono,
  animationDelay = 0,
}: {
  label: string;
  value: string;
  valueClass?: string;
  mono?: boolean;
  animationDelay?: number;
}) {
  return (
    <div
      className="rounded border border-border/60 bg-card px-3 py-2.5 animate-slide-up"
      style={{ animationDelay: `${animationDelay}ms`, animationFillMode: "both" }}
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-xl font-semibold leading-none",
          mono && "font-mono",
          valueClass ?? "text-foreground",
        )}
      >
        {value}
      </p>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ParlayPage() {
  const { cart, cartStakeInput, removeCartLeg, clearCart, setCartStakeInput } =
    useBettingPlatformStore();
  const { data: balances } = useBalances();
  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loggingInitialValues, setLoggingInitialValues] = useState<ScannedBetData | undefined>(undefined);
  const lastAutoFilledStakeRef = useRef<string | null>(null);
  const lastAutoFillKeyRef = useRef<string | null>(null);

  const parsedStake = Number.parseFloat(cartStakeInput);
  const computedBankroll = useMemo(() => {
    if (!balances || balances.length === 0) return 0;
    return balances.reduce((sum, b) => sum + (b.balance || 0), 0);
  }, [balances]);
  const bankroll = useComputedBankroll ? computedBankroll : bankrollOverride;

  const preview = useMemo(
    () => buildParlayPreview(cart, parsedStake, { bankroll, kellyMultiplier }),
    [bankroll, cart, kellyMultiplier, parsedStake],
  );
  const recommendedStake = useMemo(() => getParlayRecommendedStake(preview), [preview]);
  const autoFillKey = useMemo(
    () => `${cart.map((l) => l.id).join("|")}::${bankroll ?? "none"}::${kellyMultiplier ?? "none"}`,
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
    if (!keyChanged && !followsAutoFill) return;
    lastAutoFilledStakeRef.current = nextStakeInput;
    lastAutoFillKeyRef.current = autoFillKey;
    if (cartStakeInput !== nextStakeInput) setCartStakeInput(nextStakeInput);
  }, [autoFillKey, cart.length, cartStakeInput, parsedStake, recommendedStake, setCartStakeInput]);

  async function handleOpenLogDrawer() {
    if (!preview || preview.slipMode === "pickem_notes") {
      toast.error("Pick'em slips are for local notes only. Log entries in your Pick'em app.");
      return;
    }
    if (preview.stake == null || preview.stake <= 0) {
      toast.error("Enter a valid stake before logging this parlay.");
      return;
    }
    setLoggingInitialValues(buildParlayLogInitialValues(cart, preview.stake));
    setDrawerOpen(true);
  }

  const hasCart = cart.length > 0;
  const isPickEmNotesSlip = preview?.slipMode === "pickem_notes";
  const canOpenLogDrawer =
    hasCart &&
    preview != null &&
    preview.slipMode !== "pickem_notes" &&
    preview.stake != null &&
    preview.stake > 0;

  const evFormatted = formatPercent(preview?.estimatedEvPercent);
  const evPositive =
    preview?.estimateAvailable && preview.estimatedEvPercent != null && preview.estimatedEvPercent > 0;
  const evNegative =
    preview?.estimateAvailable && preview.estimatedEvPercent != null && preview.estimatedEvPercent < 0;

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-2xl space-y-4 px-4 py-4 pb-28">

        {/* ── Journey coach ─────────────────────────────────────────── */}
        <JourneyCoach route="parlay" />

        {/* ── Page header ───────────────────────────────────────────── */}
        <div
          className="animate-slide-up"
          style={{ animationDelay: "0ms", animationFillMode: "both" }}
        >
          <div className="flex items-baseline justify-between gap-2">
            <h1 className="text-sm font-semibold text-foreground">Parlay Builder</h1>
            {lockedSportsbook && !isPickEmNotesSlip && (
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                {lockedSportsbook}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {isPickEmNotesSlip
              ? "Pick'em slip — local notes only. Pricing handled in your Pick'em app."
              : "Add legs from Markets, review pricing and EV, then log when you place it."}
          </p>
        </div>

        {/* ── Active slip panel ─────────────────────────────────────── */}
        <div
          className="rounded-lg border border-border bg-card overflow-hidden animate-slide-up"
          style={{ animationDelay: "40ms", animationFillMode: "both" }}
        >
          {/* Section label bar */}
          <div className="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Active Slip
              </span>
            </div>
            {lockedSportsbook && !isPickEmNotesSlip && (
              <span className="rounded border border-border/60 bg-background/60 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                Locked · {lockedSportsbook}
              </span>
            )}
            {!lockedSportsbook && !isPickEmNotesSlip && (
              <span className="text-[10px] text-muted-foreground/60">No sportsbook locked yet</span>
            )}
          </div>

          <div className="p-4 space-y-4">
            {/* Pick'em notice */}
            {isPickEmNotesSlip && (
              <div className="rounded border border-border/60 bg-muted/30 px-3 py-2.5 text-xs text-muted-foreground animate-fade-in">
                Combined odds, payout, and EV are hidden for Pick&apos;em slips — your app sets the real price and payout.
              </div>
            )}

            {/* Stat tiles */}
            <div
              className={cn(
                "grid gap-2",
                isPickEmNotesSlip ? "grid-cols-1 max-w-[140px]" : "grid-cols-2 sm:grid-cols-4",
              )}
            >
              <StatTile
                label="Legs"
                value={String(preview?.legCount ?? 0)}
                animationDelay={60}
              />
              {!isPickEmNotesSlip && (
                <>
                  <StatTile
                    label="Odds"
                    value={preview?.combinedAmericanOdds != null ? formatOdds(preview.combinedAmericanOdds) : "—"}
                    mono
                    animationDelay={80}
                  />
                  <StatTile
                    label="Payout"
                    value={preview?.totalPayout != null ? formatCurrency(preview.totalPayout) : "—"}
                    mono
                    animationDelay={100}
                  />
                  <StatTile
                    label="Profit"
                    value={preview?.profit != null ? formatCurrency(preview.profit) : "—"}
                    mono
                    valueClass="text-profit"
                    animationDelay={120}
                  />
                </>
              )}
            </div>

            {/* Stake input */}
            <div
              className="rounded border border-border/60 bg-background/60 px-3 py-3 space-y-2 animate-slide-up"
              style={{ animationDelay: "140ms", animationFillMode: "both" }}
            >
              <div className="flex items-center justify-between gap-2">
                <label
                  htmlFor="parlay-stake"
                  className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground"
                >
                  Stake
                </label>
                {recommendedStake != null && (
                  <button
                    type="button"
                    onClick={() => setCartStakeInput(recommendedStake.toFixed(2))}
                    className="text-[10px] text-primary hover:text-primary/80 transition-colors underline underline-offset-2"
                  >
                    Suggested {formatCurrency(recommendedStake)}
                  </button>
                )}
              </div>
              <Input
                id="parlay-stake"
                type="number"
                min="0"
                step="0.01"
                value={cartStakeInput}
                onChange={(e) => setCartStakeInput(e.target.value)}
                placeholder="10.00"
                className="h-9 font-mono text-sm"
              />
            </div>

            {/* Fair odds + EV row */}
            {!isPickEmNotesSlip && (
              <div
                className="grid grid-cols-2 gap-2 animate-slide-up"
                style={{ animationDelay: "160ms", animationFillMode: "both" }}
              >
                {/* Fair odds */}
                <div className="rounded border border-border/60 bg-background/60 px-3 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    Fair Odds
                  </p>
                  <p className="mt-1 font-mono text-base font-semibold text-foreground">
                    {preview?.estimateAvailable && preview.estimatedFairAmericanOdds != null
                      ? formatOdds(preview.estimatedFairAmericanOdds)
                      : "—"}
                  </p>
                  <p className="mt-1 text-[10px] text-muted-foreground leading-snug">
                    {preview?.estimateAvailable
                      ? "Independence estimate"
                      : preview?.estimateUnavailableReason === "Correlation warning"
                        ? "Suppressed — correlated legs"
                        : preview?.estimateUnavailableReason === "Missing reference price"
                          ? "Missing reference price"
                          : "Add legs to estimate"}
                  </p>
                </div>

                {/* EV */}
                <div
                  className={cn(
                    "rounded border px-3 py-2.5 transition-colors",
                    evPositive
                      ? "border-profit/25 bg-profit/6"
                      : evNegative
                        ? "border-loss/25 bg-loss/6"
                        : "border-border/60 bg-background/60",
                  )}
                >
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    Est. EV
                  </p>
                  <p
                    className={cn(
                      "mt-1 font-mono text-base font-semibold",
                      evPositive ? "text-profit" : evNegative ? "text-loss" : "text-foreground",
                    )}
                  >
                    {preview?.estimateAvailable && evFormatted != null ? evFormatted : "—"}
                  </p>
                  <p className="mt-1 text-[10px] text-muted-foreground leading-snug">
                    {preview?.estimateAvailable
                      ? `${preview.legCount} leg${preview.legCount === 1 ? "" : "s"} · uncorrelated`
                      : "Estimate unavailable"}
                  </p>
                </div>
              </div>
            )}

            {/* Correlation warnings */}
            {(preview?.warnings.length ?? 0) > 0 && (
              <div
                className="rounded border border-loss/25 bg-loss/6 overflow-hidden animate-slide-up"
                style={{ animationDelay: "180ms", animationFillMode: "both" }}
              >
                <div className="flex items-center gap-2 border-b border-loss/15 px-3 py-2">
                  <AlertTriangle className="h-3.5 w-3.5 text-loss" />
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-loss">
                    Correlation warnings
                  </p>
                </div>
                <div className="divide-y divide-loss/10">
                  {preview!.warnings.map((warning) => (
                    <div
                      key={`${warning.code}-${warning.relatedLegIds.join("-")}`}
                      className="px-3 py-2.5"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">{warning.title}</p>
                        <span className="shrink-0 rounded border border-loss/25 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-loss">
                          {warning.severity}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">{warning.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* CTA row */}
            <div
              className="space-y-2 animate-slide-up"
              style={{ animationDelay: "200ms", animationFillMode: "both" }}
            >
              <button
                type="button"
                onClick={handleOpenLogDrawer}
                disabled={!canOpenLogDrawer}
                className={cn(
                  "w-full h-10 rounded flex items-center justify-center gap-2 text-sm font-semibold transition-all duration-150 active:scale-[0.98]",
                  canOpenLogDrawer
                    ? "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
                    : "bg-muted/60 text-muted-foreground cursor-not-allowed",
                )}
              >
                <Lock className="h-3.5 w-3.5" />
                Review &amp; Log Parlay
              </button>

              {hasCart && (
                <button
                  type="button"
                  onClick={clearCart}
                  className="w-full h-8 rounded border border-border/60 bg-transparent text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 hover:border-border transition-all duration-150 active:scale-[0.98]"
                >
                  Clear slip
                </button>
              )}

              {isPickEmNotesSlip && (
                <p className="text-[11px] text-muted-foreground text-center">
                  Review &amp; Log is for priced parlays only. Track Pick&apos;em entries in your app.
                </p>
              )}
            </div>
          </div>
        </div>

        {/* ── Slip legs ─────────────────────────────────────────────── */}
        <div
          className="rounded-lg border border-border bg-card overflow-hidden animate-slide-up"
          style={{ animationDelay: "80ms", animationFillMode: "both" }}
        >
          {/* Section label bar */}
          <div className="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Slip Legs
              </span>
            </div>
            {cart.length > 0 && (
              <span className="rounded-full border border-border/60 bg-background/60 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                {cart.length}
              </span>
            )}
          </div>

          {cart.length === 0 ? (
            <EmptySlip />
          ) : (
            <div className="divide-y divide-border/50">
              {cart.map((leg, index) => (
                <LegRow
                  key={leg.id}
                  leg={leg}
                  index={index}
                  isPickEmNotesSlip={isPickEmNotesSlip}
                  onRemove={() => removeCartLeg(leg.id)}
                />
              ))}
            </div>
          )}

          {cart.length > 0 && (
            <div className="border-t border-border/40 px-4 py-2">
              <p className="text-[10px] text-muted-foreground/60">
                Same-event legs trigger correlation warnings and suppress fair-odds estimates.
              </p>
            </div>
          )}
        </div>

        {/* ── EV context note ───────────────────────────────────────── */}
        {hasCart && !isPickEmNotesSlip && preview?.estimateAvailable && (
          <div
            className="flex items-start gap-2.5 rounded border border-border/40 bg-card/60 px-3 py-2.5 animate-fade-in"
          >
            <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              EV estimate uses an independence assumption across legs. Correlated legs (same game, same player) will suppress this estimate.
            </p>
          </div>
        )}
      </div>

      <LogBetDrawer
        open={drawerOpen}
        onOpenChange={(open) => {
          setDrawerOpen(open);
          if (!open) setLoggingInitialValues(undefined);
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

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptySlip() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center animate-fade-in">
      <div className="rounded-full border border-border/60 bg-muted/30 p-3">
        <Layers className="h-5 w-5 text-muted-foreground/50" />
      </div>
      <p className="text-sm font-medium text-foreground">No legs yet</p>
      <p className="text-xs text-muted-foreground max-w-[22rem]">
        Browse Markets and tap the + button on any line to add it here.
      </p>
    </div>
  );
}

// ── Leg row ───────────────────────────────────────────────────────────────────

function LegRow({
  leg,
  index,
  isPickEmNotesSlip,
  onRemove,
}: {
  leg: ParlayCartLeg;
  index: number;
  isPickEmNotesSlip: boolean;
  onRemove: () => void;
}) {
  return (
    <div
      className="flex items-start gap-3 px-4 py-3 animate-slide-up"
      style={{ animationDelay: `${index * 40}ms`, animationFillMode: "both" }}
    >
      {/* Leg number */}
      <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border/60 bg-background/60">
        <span className="text-[9px] font-semibold text-muted-foreground">{index + 1}</span>
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-semibold text-foreground leading-snug">{leg.display}</p>
        <p className="text-[11px] text-muted-foreground">
          {leg.surface === "player_props" ? "Player Props" : "Game Lines"} · {leg.sportsbook}
        </p>
        <p className="text-[11px] text-muted-foreground truncate">{leg.event}</p>

        {isPickEmNotesSlip ? (
          <p className="text-[11px] text-muted-foreground">
            Best line:{" "}
            <span className="font-mono text-foreground">{formatOdds(leg.oddsAmerican)}</span>
            {leg.referenceOddsAmerican != null && (
              <span className="text-muted-foreground">
                {" "}· fair {formatOdds(leg.referenceOddsAmerican)}
              </span>
            )}
          </p>
        ) : (
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs font-semibold text-foreground">
              {formatOdds(leg.oddsAmerican)}
            </span>
            <span className="text-[11px] text-muted-foreground">
              Fair:{" "}
              <span className="font-mono">
                {leg.referenceOddsAmerican != null
                  ? formatOdds(leg.referenceOddsAmerican)
                  : "—"}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Remove */}
      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove leg"
        className="mt-0.5 shrink-0 rounded p-1 text-muted-foreground/50 hover:text-foreground hover:bg-muted/50 transition-colors active:scale-90"
      >
        <Minus className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
