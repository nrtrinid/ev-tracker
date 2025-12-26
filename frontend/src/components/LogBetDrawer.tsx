"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  });
  const [showAdvanced, setShowAdvanced] = useState(false);
  
  const oddsInputRef = useRef<HTMLInputElement>(null);
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
        oddsInputRef.current?.focus();
      }, 300);
    }
  }, [open]);

  // Parse numeric values
  const oddsNum = parseFloat(formState.odds) || 0;
  const stakeNum = parseFloat(formState.stake) || 0;

  // Calculate EV for display
  const ev = calculateEVClient(
    oddsNum,
    stakeNum,
    formState.promo_type,
    MARKET_VIG[formState.market] || 0.045
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
      });

      toast.success("Bet logged!", {
        id: toastId,
        description: `+${formatCurrency(ev.evTotal)} EV on ${formState.sportsbook}`,
      });

      if (keepOpen) {
        // Batch mode: Clear odds/stake, keep sportsbook/sport, focus odds
        setFormState(prev => ({
          ...prev,
          odds: "",
          stake: "",
          event: "",
        }));
        setTimeout(() => {
          oddsInputRef.current?.focus();
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
        });
      }
    } catch (error) {
      toast.error("Failed to log bet", {
        id: toastId,
        description: "Check your connection and try again",
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
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Odds
              </label>
              <Input
                ref={oddsInputRef}
                type="text"
                inputMode="numeric"
                placeholder="+150"
                value={formState.odds}
                onChange={(e) => updateField("odds", e.target.value)}
                className="h-12 text-lg font-mono text-center"
              />
            </div>
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
            </div>
          </div>

          {/* Quick Stake Presets */}
          <div className="flex gap-2 mb-4">
            {[10, 25, 50, 100].map((amount) => (
              <button
                key={amount}
                type="button"
                onClick={() => updateField("stake", amount.toString())}
                className={cn(
                  "flex-1 py-2 rounded-lg text-sm font-medium transition-colors",
                  formState.stake === amount.toString()
                    ? "bg-foreground text-background"
                    : "bg-muted text-muted-foreground hover:bg-secondary"
                )}
              >
                ${amount}
              </button>
            ))}
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
            <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
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

          {/* Advanced Options Toggle */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1 text-xs text-muted-foreground mb-3"
          >
            {showAdvanced ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {showAdvanced ? "Hide" : "Show"} advanced
          </button>

          {showAdvanced && (
            <div className="space-y-3 mb-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Event (optional)
                </label>
                <Input
                  type="text"
                  placeholder="Lions vs Bears"
                  value={formState.event}
                  onChange={(e) => updateField("event", e.target.value)}
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
  vig: number = 0.045
): { evTotal: number; winPayout: number } {
  if (oddsAmerican === 0 || stake <= 0) {
    return { evTotal: 0, winPayout: 0 };
  }

  const decimalOdds = americanToDecimal(oddsAmerican);
  const impliedProb = 1 / decimalOdds;
  const fairProb = impliedProb / (1 + vig);

  let winPayout: number;
  let evTotal: number;

  if (promoType === "bonus_bet") {
    // Bonus bet: stake not returned on win
    winPayout = stake * (decimalOdds - 1);
    const fairWinProb = fairProb;
    evTotal = (fairWinProb * winPayout) - 0; // No risk on bonus bet
  } else {
    // Standard bet
    winPayout = stake * decimalOdds;
    const profit = winPayout - stake;
    evTotal = (fairProb * profit) - ((1 - fairProb) * stake);
  }

  return { evTotal, winPayout };
}

