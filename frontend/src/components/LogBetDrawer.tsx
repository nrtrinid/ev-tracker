"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SmartOddsInput, type SmartOddsInputRef } from "@/components/SmartOddsInput";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useCreateBet } from "@/lib/hooks";
import {
  SPORTSBOOKS,
  SPORTS,
  MARKETS,
  PROMO_TYPES,
  type PromoType,
} from "@/lib/types";
import {
  formatCurrency,
  americanToDecimal,
  cn,
  calculateHoldFromOdds,
} from "@/lib/utils";
import { Loader2, Plus, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";

// Smart vig defaults based on market type
const MARKET_VIG: Record<string, number> = {
  ML: 0.045,
  Spread: 0.045,
  Total: 0.045,
  Parlay: 0.12,
  Prop: 0.07,
  Futures: 0.07,
  SGP: 0.12,
};

// Sportsbook colors for selected state
const sportsbookColors: Record<string, string> = {
  DraftKings: "bg-draftkings",
  FanDuel: "bg-fanduel",
  BetMGM: "bg-betmgm",
  Caesars: "bg-caesars",
  "ESPN Bet": "bg-espnbet",
  Fanatics: "bg-fanatics",
  "Hard Rock": "bg-hardrock",
  bet365: "bg-bet365",
};

interface LogBetDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface FormState {
  sportsbook: string;
  sport: string;
  market: string;
  promo_type: PromoType;
  odds: string;
  stake: string;
  event: string;
  // Advanced fields
  opposing_odds: string;
  boost_percent: string;
  payout_override: string;
  notes: string;
}

// Get sticky values from localStorage
const getStickySportsbook = (): string => {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("ev-tracker-sportsbook") || "";
};

const getStickyPromoType = (): PromoType => {
  if (typeof window === "undefined") return "standard";
  const stored = localStorage.getItem("ev-tracker-promo-type");
  if (stored && PROMO_TYPES.some(p => p.value === stored)) {
    return stored as PromoType;
  }
  return "standard";
};

export function LogBetDrawer({ open, onOpenChange }: LogBetDrawerProps) {
  const [formState, setFormState] = useState<FormState>({
    sportsbook: "",
    sport: "",
    market: "ML",
    promo_type: "standard",
    odds: "",
    stake: "",
    event: "",
    opposing_odds: "",
    boost_percent: "",
    payout_override: "",
    notes: "",
  });
  const [showAdvanced, setShowAdvanced] = useState(false);
  
  const oddsInputRef = useRef<SmartOddsInputRef>(null);
  const opposingOddsInputRef = useRef<SmartOddsInputRef>(null);
  const createBet = useCreateBet();

  // Initialize sticky values on mount
  useEffect(() => {
    if (open) {
      setFormState(prev => ({
        ...prev,
        sportsbook: prev.sportsbook || getStickySportsbook(),
        promo_type: getStickyPromoType(),
      }));
      // Focus odds input after a short delay to let drawer animate
      setTimeout(() => {
        // Focus the actual input element inside SmartOddsInput
        const input = document.querySelector('[data-odds-input]') as HTMLInputElement;
        input?.focus();
      }, 300);
    }
  }, [open]);

  // Parse numeric values - get signed values from SmartOddsInput refs
  const oddsNum = oddsInputRef.current?.getSignedValue() || 0;
  const stakeNum = parseFloat(formState.stake) || 0;
  const opposingOddsNum = opposingOddsInputRef.current?.getSignedValue() || 0;
  const boostPercentNum = parseFloat(formState.boost_percent) || 0;
  const payoutOverrideNum = parseFloat(formState.payout_override) || 0;

  // Get smart vig default based on market
  const defaultVig = MARKET_VIG[formState.market] || 0.045;

  // Calculate actual vig if opposing odds provided
  const calculatedVig = opposingOddsNum !== 0 
    ? calculateHoldFromOdds(oddsNum, opposingOddsNum)
    : null;

  // Use calculated vig if available, otherwise smart default
  const effectiveVig = calculatedVig !== null ? calculatedVig : defaultVig;

  // Calculate EV for display
  const ev = calculateEVClient(
    oddsNum,
    stakeNum,
    formState.promo_type,
    boostPercentNum,
    payoutOverrideNum || undefined,
    effectiveVig
  );

  const updateField = (field: keyof FormState, value: string) => {
    setFormState(prev => ({ ...prev, [field]: value }));
  };

  const isValid = formState.sportsbook && formState.sport && oddsNum !== 0 && stakeNum > 0;

  const handleLogBet = async (keepOpen: boolean) => {
    if (!isValid) return;

    // Save sticky values
    localStorage.setItem("ev-tracker-sportsbook", formState.sportsbook);
    localStorage.setItem("ev-tracker-promo-type", formState.promo_type);

    // Optimistic toast for speed
    const toastId = toast.loading("Logging bet...");

    try {
      await createBet.mutateAsync({
        sportsbook: formState.sportsbook,
        sport: formState.sport,
        event: formState.event || `${formState.sport} Game`,
        market: formState.market,
        promo_type: formState.promo_type,
        odds_american: oddsNum,
        stake: stakeNum,
        boost_percent: formState.promo_type === "boost_custom" ? boostPercentNum : undefined,
        payout_override: payoutOverrideNum || undefined,
        opposing_odds: opposingOddsNum || undefined,
        notes: formState.notes || undefined,
      });

      toast.success("Bet logged!", {
        id: toastId,
        description: `${ev.evTotal >= 0 ? "+" : ""}${formatCurrency(ev.evTotal)} EV on ${formState.sportsbook}`,
      });

      if (keepOpen) {
        // Batch mode: Clear bet-specific fields, keep sportsbook/sport/market/promo
        setFormState(prev => ({
          ...prev,
          odds: "",
          stake: "",
          event: "",
          opposing_odds: "",
          boost_percent: prev.promo_type === "boost_custom" ? prev.boost_percent : "", // Keep boost if using custom
          payout_override: "",
          notes: "",
        }));
        setTimeout(() => {
          const input = document.querySelector('[data-odds-input]') as HTMLInputElement;
          input?.focus();
        }, 50);
      } else {
        // Single mode: Close drawer and reset
        onOpenChange(false);
        setFormState({
          sportsbook: formState.sportsbook,
          sport: formState.sport,
          market: formState.market,
          promo_type: formState.promo_type,
          odds: "",
          stake: "",
          event: "",
          opposing_odds: "",
          boost_percent: "",
          payout_override: "",
          notes: "",
        });
      }
    } catch (error) {
      console.error("Failed to log bet:", error);
      const errorMessage = error instanceof Error ? error.message : "Check your connection and try again";
      toast.error("Failed to log bet", {
        id: toastId,
        description: errorMessage,
      });
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="flex flex-col p-0 max-h-[90vh]">
        {/* Header */}
        <SheetHeader className="px-4 pt-4 pb-2">
          <SheetTitle className="text-left">Log Bet</SheetTitle>
        </SheetHeader>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-4 pb-32">
          {/* Sportsbook Carousel */}
          <div className="mb-4">
            <label className="text-xs font-medium text-muted-foreground mb-2 block">
              Sportsbook
            </label>
            <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
              {SPORTSBOOKS.map((book) => (
                <button
                  key={book}
                  type="button"
                  onClick={() => updateField("sportsbook", book)}
                  className={cn(
                    "flex-shrink-0 px-3 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap",
                    formState.sportsbook === book
                      ? `${sportsbookColors[book] || "bg-foreground"} text-white shadow-md scale-105`
                      : "bg-muted text-muted-foreground hover:bg-secondary"
                  )}
                >
                  {book}
                </button>
              ))}
            </div>
          </div>

          {/* Sport Carousel */}
          <div className="mb-4">
            <label className="text-xs font-medium text-muted-foreground mb-2 block">
              Sport
            </label>
            <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
              {SPORTS.map((sport) => (
                <button
                  key={sport}
                  type="button"
                  onClick={() => updateField("sport", sport)}
                  className={cn(
                    "flex-shrink-0 px-3 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap",
                    formState.sport === sport
                      ? "bg-foreground text-background shadow-md scale-105"
                      : "bg-muted text-muted-foreground hover:bg-secondary"
                  )}
                >
                  {sport}
                </button>
              ))}
            </div>
          </div>

          {/* Odds & Stake - Side by Side */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <SmartOddsInput
              ref={oddsInputRef}
              value={formState.odds}
              onChange={(value) => updateField("odds", value)}
              placeholder="150"
              defaultSign="+"
              label="Odds"
              className="[&_input]:h-12 [&_input]:text-lg"
            />
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Stake
              </label>
              <Input
                type="text"
                inputMode="decimal"
                placeholder="$25"
                value={formState.stake}
                onChange={(e) => updateField("stake", e.target.value)}
                className="h-12 text-lg font-mono text-center"
              />
              {/* Quick Stake Presets - directly under stake field */}
              <div className="flex gap-2 mt-2">
                {[10, 25, 50].map((amount) => (
                  <button
                    key={amount}
                    type="button"
                    onClick={() => updateField("stake", amount.toString())}
                    className={cn(
                      "flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors",
                      formState.stake === amount.toString()
                        ? "bg-foreground text-background"
                        : "bg-muted text-muted-foreground hover:bg-secondary"
                    )}
                  >
                    ${amount}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Market Selection */}
          <div className="mb-4">
            <label className="text-xs font-medium text-muted-foreground mb-2 block">
              Market
            </label>
            <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
              {MARKETS.map((market) => (
                <button
                  key={market}
                  type="button"
                  onClick={() => updateField("market", market)}
                  className={cn(
                    "flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap",
                    formState.market === market
                      ? "bg-foreground text-background"
                      : "bg-muted text-muted-foreground hover:bg-secondary"
                  )}
                >
                  {market}
                </button>
              ))}
            </div>
          </div>

          {/* Promo Type Selection */}
          <div className="mb-4">
            <label className="text-xs font-medium text-muted-foreground mb-2 block">
              Promo Type
            </label>
            <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1 pt-0.5">
              {PROMO_TYPES.map((promo) => (
                <button
                  key={promo.value}
                  type="button"
                  onClick={() => updateField("promo_type", promo.value)}
                  className={cn(
                    "flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap",
                    formState.promo_type === promo.value
                      ? promo.value === "bonus_bet" 
                        ? "bg-[#7A9E7E]/30 text-[#2C2416] ring-1 ring-[#7A9E7E]"
                        : "bg-foreground text-background"
                      : "bg-muted text-muted-foreground hover:bg-secondary"
                  )}
                >
                  {promo.label}
                </button>
              ))}
            </div>
          </div>

          {/* Vig Hint */}
          <div className="text-xs text-muted-foreground mb-3 flex items-center gap-2">
            <span>
              Using {calculatedVig !== null ? "calculated" : "default"} vig:{" "}
              <span className="font-mono font-medium">
                {(effectiveVig * 100).toFixed(1)}%
              </span>
              {calculatedVig === null && (
                <span className="text-muted-foreground/70"> ({formState.market})</span>
              )}
            </span>
          </div>

          {/* Custom Boost Percent (shows when boost_custom selected) */}
          {formState.promo_type === "boost_custom" && (
            <div className="mb-4">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Boost Percentage
              </label>
              <Input
                type="text"
                inputMode="decimal"
                placeholder="e.g. 75"
                value={formState.boost_percent}
                onChange={(e) => updateField("boost_percent", e.target.value)}
                className="h-10"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Enter the boost % (e.g., 75 for a 75% profit boost)
              </p>
            </div>
          )}

          {/* Advanced Options Toggle */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1 text-xs text-muted-foreground mb-3"
          >
            {showAdvanced ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {showAdvanced ? "Hide" : "Show"} advanced options
          </button>

          {showAdvanced && (
            <div className="space-y-3 mb-4 p-3 rounded-lg bg-muted/50 border border-border">
              {/* Event */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Event
                </label>
                <Input
                  type="text"
                  placeholder="Lions vs Bears"
                  value={formState.event}
                  onChange={(e) => updateField("event", e.target.value)}
                  className="h-10"
                />
              </div>

              {/* Opposing Odds (for accurate vig) */}
              <div>
                <SmartOddsInput
                  ref={opposingOddsInputRef}
                  value={formState.opposing_odds}
                  onChange={(value) => updateField("opposing_odds", value)}
                  placeholder="180"
                  defaultSign="-"
                  label="Opposing Odds"
                  className="[&_input]:h-10"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Enter opposing line for accurate vig calculation
                </p>
              </div>

              {/* Payout Override */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Payout Override
                </label>
                <Input
                  type="text"
                  inputMode="decimal"
                  placeholder={ev.winPayout > 0 ? `Calculated: ${ev.winPayout.toFixed(2)}` : "e.g. 35.50"}
                  value={formState.payout_override}
                  onChange={(e) => updateField("payout_override", e.target.value)}
                  className="h-10"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Override if the book's payout differs from calculated
                </p>
              </div>

              {/* Notes */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Notes
                </label>
                <Input
                  type="text"
                  placeholder="Any additional context..."
                  value={formState.notes}
                  onChange={(e) => updateField("notes", e.target.value)}
                  className="h-10"
                />
              </div>
            </div>
          )}

          {/* EV Preview */}
          {isValid && ev.evTotal > 0 && (
            <div className="rounded-lg bg-[#4A7C59]/10 border border-[#4A7C59]/20 p-3 mb-4">
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Expected Value</span>
                <span className="font-mono font-semibold text-[#4A7C59]">
                  +{formatCurrency(ev.evTotal)}
                </span>
              </div>
              <div className="flex justify-between items-center mt-1">
                <span className="text-xs text-muted-foreground">To Win</span>
                <span className="font-mono text-sm">
                  {formatCurrency(ev.winPayout)}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Sticky Footer */}
        <div className="absolute bottom-0 left-0 right-0 bg-background border-t border-border p-4 flex gap-3">
          <Button
            variant="outline"
            className="flex-1 h-12"
            onClick={() => handleLogBet(true)}
            disabled={!isValid || createBet.isPending}
          >
            {createBet.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Plus className="h-4 w-4 mr-1" />
                Log & Add Another
              </>
            )}
          </Button>
          <Button
            className="flex-1 h-12"
            onClick={() => handleLogBet(false)}
            disabled={!isValid || createBet.isPending}
          >
            {createBet.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              "Log Bet"
            )}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// Client-side EV calculation
function calculateEVClient(
  oddsAmerican: number,
  stake: number,
  promoType: PromoType,
  boostPercent: number = 0,
  payoutOverride?: number,
  vig: number = 0.045
): { evTotal: number; winPayout: number } {
  if (oddsAmerican === 0 || stake <= 0) {
    return { evTotal: 0, winPayout: 0 };
  }

  let decimalOdds = americanToDecimal(oddsAmerican);
  
  // Apply boost if applicable
  let effectiveBoost = 0;
  if (promoType === "boost_30") effectiveBoost = 0.3;
  else if (promoType === "boost_50") effectiveBoost = 0.5;
  else if (promoType === "boost_100") effectiveBoost = 1.0;
  else if (promoType === "boost_custom") effectiveBoost = boostPercent / 100;
  
  if (effectiveBoost > 0) {
    // Boost applies to profit portion only
    const baseProfit = decimalOdds - 1;
    const boostedProfit = baseProfit * (1 + effectiveBoost);
    decimalOdds = 1 + boostedProfit;
  }
  
  const impliedProb = 1 / americanToDecimal(oddsAmerican); // Use unboosted for fair prob
  const fairProb = impliedProb / (1 + vig);

  let winPayout: number;
  let evTotal: number;

  if (promoType === "bonus_bet") {
    // Bonus bet: stake not returned on win
    const calculatedPayout = stake * (decimalOdds - 1);
    // Use override if provided, otherwise calculated
    winPayout = payoutOverride || calculatedPayout;
    evTotal = fairProb * winPayout; // No risk on bonus bet
  } else {
    // Standard or boosted bet
    const calculatedPayout = stake * decimalOdds;
    // Use override if provided, otherwise calculated
    winPayout = payoutOverride || calculatedPayout;
    const profit = winPayout - stake;
    evTotal = (fairProb * profit) - ((1 - fairProb) * stake);
  }

  return { evTotal, winPayout };
}

