"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  formatPercent,
  americanToDecimal,
  cn,
} from "@/lib/utils";
import { Loader2, TrendingUp, DollarSign } from "lucide-react";
import { toast } from "sonner";

// Quick stake presets for fast entry
const STAKE_PRESETS = [10, 25, 50, 100] as const;

// Map sportsbook names to button variants
const sportsbookVariants: Record<string, any> = {
  DraftKings: "draftkings",
  FanDuel: "fanduel",
  BetMGM: "betmgm",
  Caesars: "caesars",
  "ESPN Bet": "espnbet",
  Fanatics: "fanatics",
  "Hard Rock": "hardrock",
  bet365: "bet365",
};

interface BetFormData {
  sportsbook: string;
  sport: string;
  event: string;
  market: string;
  promo_type: PromoType;
  odds: string;
  stake: string;
  boost_percent: string;
  winnings_cap: string;
  notes: string;
}

const initialFormData: BetFormData = {
  sportsbook: "",
  sport: "",
  event: "",
  market: "ML",
  promo_type: "bonus_bet",
  odds: "",
  stake: "",
  boost_percent: "",
  winnings_cap: "",
  notes: "",
};

export function BetEntryForm({ onSuccess }: { onSuccess?: () => void }) {
  const [formData, setFormData] = useState<BetFormData>(initialFormData);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const createBet = useCreateBet();

  // Calculate EV in real-time
  const oddsNum = parseFloat(formData.odds) || 0;
  const stakeNum = parseFloat(formData.stake) || 0;
  const boostPercentNum = parseFloat(formData.boost_percent) || 0;
  const winningsCapNum = parseFloat(formData.winnings_cap) || 0;

  // Client-side EV calculation for instant feedback
  const ev = calculateEVClient(
    oddsNum,
    stakeNum,
    formData.promo_type,
    boostPercentNum,
    winningsCapNum || undefined
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.sportsbook || !formData.sport || !oddsNum || !stakeNum) {
      return;
    }

    try {
      await createBet.mutateAsync({
        sportsbook: formData.sportsbook,
        sport: formData.sport,
        event: formData.event || `${formData.sport} Game`,
        market: formData.market,
        promo_type: formData.promo_type,
        odds_american: oddsNum,
        stake: stakeNum,
        boost_percent:
          formData.promo_type === "boost_custom" ? boostPercentNum : undefined,
        winnings_cap: winningsCapNum || undefined,
        notes: formData.notes || undefined,
      });

      // Reset form but keep sportsbook and sport for quick re-entry
      setFormData({
        ...initialFormData,
        sportsbook: formData.sportsbook,
        sport: formData.sport,
      });

      toast.success("Bet logged!", {
        description: `+${formatCurrency(ev.evTotal)} EV on ${formData.sportsbook}`,
      });

      onSuccess?.();
    } catch (error) {
      console.error("Failed to create bet:", error);
      toast.error("Failed to log bet", {
        description: "Check your connection and try again",
      });
    }
  };

  const updateField = (field: keyof BetFormData, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-lg">New Bet</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Sportsbook Selection - Big touch-friendly buttons */}
          <div>
            <label className="text-sm font-medium mb-2 block">Sportsbook</label>
            <div className="grid grid-cols-4 gap-2">
              {SPORTSBOOKS.map((book) => (
                <Button
                  key={book}
                  type="button"
                  variant={
                    formData.sportsbook === book
                      ? sportsbookVariants[book]
                      : "outline"
                  }
                  size="sm"
                  className={cn(
                    "h-10 text-xs px-2",
                    formData.sportsbook === book && "ring-2 ring-offset-2"
                  )}
                  onClick={() => updateField("sportsbook", book)}
                >
                  {book === "ESPN Bet" ? "ESPN" : book.split(" ")[0]}
                </Button>
              ))}
            </div>
          </div>

          {/* Sport Selection */}
          <div>
            <label className="text-sm font-medium mb-2 block">Sport</label>
            <div className="flex flex-wrap gap-2">
              {SPORTS.slice(0, 7).map((sport) => (
                <Button
                  key={sport}
                  type="button"
                  variant={formData.sport === sport ? "default" : "outline"}
                  size="sm"
                  onClick={() => updateField("sport", sport)}
                >
                  {sport}
                </Button>
              ))}
            </div>
          </div>

          {/* Selection and Market - Row layout on larger screens */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-2 block">
                Selection Name <span className="text-muted-foreground font-normal">(optional)</span>
              </label>
              <Input
                placeholder="e.g. Lakers, Chiefs -3, LeBron 25+ pts"
                value={formData.event}
                onChange={(e) => updateField("event", e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">Market</label>
              <div className="flex flex-wrap gap-2">
                {MARKETS.map((market) => (
                  <Button
                    key={market}
                    type="button"
                    variant={formData.market === market ? "default" : "outline"}
                    size="sm"
                    onClick={() => updateField("market", market)}
                  >
                    {market}
                  </Button>
                ))}
              </div>
            </div>
          </div>

          {/* Promo Type */}
          <div>
            <label className="text-sm font-medium mb-2 block">Promo Type</label>
            <div className="flex flex-wrap gap-2">
              {PROMO_TYPES.filter((p) => p.value !== "standard").map((promo) => (
                <Button
                  key={promo.value}
                  type="button"
                  variant={
                    formData.promo_type === promo.value ? "default" : "outline"
                  }
                  size="sm"
                  className={cn(
                    promo.value === "bonus_bet" &&
                      formData.promo_type === promo.value &&
                      "bg-green-600 hover:bg-green-700",
                    promo.value === "no_sweat" &&
                      formData.promo_type === promo.value &&
                      "bg-blue-600 hover:bg-blue-700",
                    promo.value.startsWith("boost") &&
                      formData.promo_type === promo.value &&
                      "bg-purple-600 hover:bg-purple-700"
                  )}
                  onClick={() =>
                    updateField("promo_type", promo.value as PromoType)
                  }
                >
                  {promo.label}
                </Button>
              ))}
            </div>
          </div>

          {/* Odds and Stake - The key inputs */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-2 block">
                Odds (American)
              </label>
              <Input
                type="number"
                placeholder="+150 or -110"
                value={formData.odds}
                onChange={(e) => updateField("odds", e.target.value)}
                className="text-lg font-mono"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">Stake ($)</label>
              <Input
                type="number"
                placeholder="10.00"
                value={formData.stake}
                onChange={(e) => updateField("stake", e.target.value)}
                className="text-lg font-mono"
                step="0.01"
              />
              {/* Quick stake presets */}
              <div className="flex gap-1 mt-2">
                {STAKE_PRESETS.map((preset) => (
                  <Button
                    key={preset}
                    type="button"
                    variant={formData.stake === String(preset) ? "default" : "outline"}
                    size="sm"
                    className="flex-1 h-8 text-xs"
                    onClick={() => updateField("stake", String(preset))}
                  >
                    ${preset}
                  </Button>
                ))}
              </div>
            </div>
          </div>

          {/* Custom Boost Percent (only shown for boost_custom) */}
          {formData.promo_type === "boost_custom" && (
            <div>
              <label className="text-sm font-medium mb-2 block">
                Boost Percentage (%)
              </label>
              <Input
                type="number"
                placeholder="25"
                value={formData.boost_percent}
                onChange={(e) => updateField("boost_percent", e.target.value)}
              />
            </div>
          )}

          {/* Advanced Options Toggle */}
          <button
            type="button"
            className="text-sm text-muted-foreground hover:text-foreground"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? "− Hide" : "+ Show"} advanced options
          </button>

          {showAdvanced && (
            <div className="space-y-4 pt-2">
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Winnings Cap ($)
                </label>
                <Input
                  type="number"
                  placeholder="Optional max bonus winnings"
                  value={formData.winnings_cap}
                  onChange={(e) => updateField("winnings_cap", e.target.value)}
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Notes</label>
                <Input
                  placeholder="Optional notes"
                  value={formData.notes}
                  onChange={(e) => updateField("notes", e.target.value)}
                />
              </div>
            </div>
          )}

          {/* Real-time EV Display */}
          {oddsNum !== 0 && stakeNum > 0 && (
            <div className="rounded-lg bg-muted p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground flex items-center gap-2">
                  <TrendingUp className="h-4 w-4" />
                  Expected Value
                </span>
                <span
                  className={cn(
                    "text-xl font-bold",
                    ev.evTotal > 0 ? "text-green-600" : "text-red-600"
                  )}
                >
                  {formatCurrency(ev.evTotal)}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-2">
                  <DollarSign className="h-4 w-4" />
                  {formData.promo_type === "bonus_bet" ? "Winnings" : "Win Payout"}
                </span>
                <span className="font-medium">
                  {formatCurrency(ev.winPayout)}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">EV per $</span>
                <span className="font-medium">
                  {formatPercent(ev.evPerDollar)}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Decimal Odds</span>
                <span className="font-mono">{ev.decimalOdds.toFixed(3)}</span>
              </div>
            </div>
          )}

          {/* Submit Button */}
          <Button
            type="submit"
            className="w-full h-12 text-lg"
            disabled={
              !formData.sportsbook ||
              !formData.sport ||
              !oddsNum ||
              !stakeNum ||
              createBet.isPending
            }
          >
            {createBet.isPending ? (
              <>
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Saving...
              </>
            ) : (
              `Log Bet (+${formatCurrency(ev.evTotal)} EV)`
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

// Client-side EV calculation for instant feedback
function calculateEVClient(
  oddsAmerican: number,
  stake: number,
  promoType: PromoType,
  boostPercent: number = 0,
  winningsCap?: number,
  kFactor: number = 0.78
): { evPerDollar: number; evTotal: number; winPayout: number; decimalOdds: number } {
  if (oddsAmerican === 0 || stake <= 0) {
    return { evPerDollar: 0, evTotal: 0, winPayout: 0, decimalOdds: 0 };
  }

  const decimalOdds = americanToDecimal(oddsAmerican);

  // Determine effective boost
  let effectiveBoost = 0;
  if (promoType === "boost_30") effectiveBoost = 0.3;
  else if (promoType === "boost_50") effectiveBoost = 0.5;
  else if (promoType === "boost_100") effectiveBoost = 1.0;
  else if (promoType === "boost_custom") effectiveBoost = boostPercent / 100;

  // Calculate win payout
  let winPayout: number;
  if (promoType === "bonus_bet") {
    winPayout = stake * (decimalOdds - 1);
  } else if (promoType.startsWith("boost")) {
    const baseWinnings = stake * (decimalOdds - 1);
    let extraWinnings = baseWinnings * effectiveBoost;
    if (winningsCap && extraWinnings > winningsCap) {
      extraWinnings = winningsCap;
    }
    winPayout = stake + baseWinnings + extraWinnings;
  } else {
    winPayout = stake * decimalOdds;
  }

  // Calculate EV per dollar
  let evPerDollar: number;
  if (promoType === "bonus_bet") {
    evPerDollar = 1 - 1 / decimalOdds;
  } else if (promoType === "no_sweat" || promoType === "promo_qualifier") {
    // No-sweat and promo qualifiers: 0 EV (user logs bonus bet separately when received)
    evPerDollar = 0;
  } else if (promoType.startsWith("boost")) {
    const winProb = 1 / decimalOdds;
    let potentialExtra = effectiveBoost * (decimalOdds - 1);
    if (winningsCap) {
      potentialExtra = Math.min(potentialExtra, winningsCap / stake);
    }
    evPerDollar = winProb * potentialExtra;
  } else {
    evPerDollar = 0;
  }

  return {
    evPerDollar,
    evTotal: stake * evPerDollar,
    winPayout,
    decimalOdds,
  };
}
