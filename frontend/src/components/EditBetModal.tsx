"use client";

import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { useUpdateBet } from "@/lib/hooks";
import type { Bet, PromoType } from "@/lib/types";
import { SPORTSBOOKS, SPORTS, MARKETS, PROMO_TYPES } from "@/lib/types";
import { 
  cn, 
  americanToDecimal
} from "@/lib/utils";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

// Smart vig defaults based on market type
const MARKET_VIG: Record<string, number> = {
  ML: 0.045,      // Standard markets: 4.5%
  Spread: 0.045,
  Total: 0.045,
  Prop: 0.07,     // Juiced markets: 7%
  Futures: 0.07,
  SGP: 0.12,      // Exotic markets: 12%
};

// Map sportsbook names to button variants
const sportsbookVariants: Record<string, string> = {
  DraftKings: "draftkings",
  FanDuel: "fanduel",
  BetMGM: "betmgm",
  Caesars: "caesars",
  "ESPN Bet": "espnbet",
  Fanatics: "fanatics",
  "Hard Rock": "hardrock",
  bet365: "bet365",
};

interface EditBetModalProps {
  bet: Bet | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EditBetModal({ bet, open, onOpenChange }: EditBetModalProps) {
  const updateBet = useUpdateBet();
  const [showAdvanced, setShowAdvanced] = useState(false);
  const oddsInputRef = useRef<HTMLInputElement>(null);

  const [formData, setFormData] = useState({
    sportsbook: "",
    sport: "",
    event: "",
    market: "ML",
    promo_type: "bonus_bet" as PromoType,
    odds: "",
    stake: "",
    boost_percent: "",
    winnings_cap: "",
    opposing_odds: "",
    notes: "",
    event_date: "",
  });

  // Populate form when bet changes
  useEffect(() => {
    if (bet) {
      setFormData({
        sportsbook: bet.sportsbook,
        sport: bet.sport,
        event: bet.event,
        market: bet.market,
        promo_type: bet.promo_type,
        odds: String(bet.odds_american),
        stake: String(bet.stake),
        boost_percent: bet.boost_percent ? String(bet.boost_percent) : "",
        winnings_cap: bet.winnings_cap ? String(bet.winnings_cap) : "",
        opposing_odds: "",
        notes: bet.notes || "",
        event_date: bet.event_date || "",
      });
      // Always start with advanced options hidden for compact view
      setShowAdvanced(false);
    }
  }, [bet]);

  const updateField = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const oddsNum = parseFloat(formData.odds) || 0;
  const stakeNum = parseFloat(formData.stake) || 0;
  const opposingOddsNum = parseFloat(formData.opposing_odds) || 0;

  // Get smart vig default based on market
  const defaultVig = MARKET_VIG[formData.market] || 0.045;

  // Calculate actual vig if opposing odds provided (for advanced options hint)
  const calculatedVig = opposingOddsNum !== 0 
    ? calculateHoldFromOdds(oddsNum, opposingOddsNum)
    : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bet) return;

    if (!formData.sportsbook || !formData.sport || !oddsNum || !stakeNum) {
      toast.error("Missing required fields");
      return;
    }

    const boostPercentNum = parseFloat(formData.boost_percent) || 0;
    const winningsCapNum = parseFloat(formData.winnings_cap) || 0;

    try {
      await updateBet.mutateAsync({
        id: bet.id,
        data: {
          sportsbook: formData.sportsbook,
          sport: formData.sport,
          event: formData.event || `${formData.sport} Game`,
          market: formData.market,
          promo_type: formData.promo_type,
          odds_american: oddsNum,
          stake: stakeNum,
          boost_percent:
            formData.promo_type === "boost_custom"
              ? boostPercentNum || undefined
              : undefined,
          winnings_cap: winningsCapNum || undefined,
          notes: formData.notes || undefined,
          event_date: formData.event_date || undefined,
        },
      });

      toast.success("Bet updated!");
      onOpenChange(false);
    } catch (error) {
      console.error("Failed to update bet:", error);
      toast.error("Failed to update bet");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Bet</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Sportsbook Selection - Match new bet form */}
          <div>
            <label className="text-sm font-medium mb-2 block">Sportsbook</label>
            <div className="grid grid-cols-4 gap-2">
              {SPORTSBOOKS.map((book) => (
                <Button
                  key={book}
                  type="button"
                  variant={
                    formData.sportsbook === book
                      ? (sportsbookVariants[book] as any)
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
                  onClick={() => {
                    updateField("sport", sport);
                    setTimeout(() => oddsInputRef.current?.focus(), 50);
                  }}
                >
                  {sport}
                </Button>
              ))}
            </div>
          </div>

          {/* Market Selection - Before Promo Type */}
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
            {/* Show vig hint for non-standard markets */}
            {(formData.market === "Prop" || formData.market === "Futures" || formData.market === "SGP") && (
              <p className="text-xs text-muted-foreground mt-1.5">
                {formData.market === "SGP" ? "12%" : "7%"} default vig for {formData.market}
              </p>
            )}
          </div>

          {/* Promo Type */}
          <div>
            <label className="text-sm font-medium mb-2 block">Promo Type</label>
            <div className="flex flex-wrap gap-2">
              {PROMO_TYPES.map((promo) => (
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
                      "bg-[#C4A35A] hover:bg-[#B8963E] text-[#2C2416]",
                    promo.value === "no_sweat" &&
                      formData.promo_type === promo.value &&
                      "bg-[#4A7C59] hover:bg-[#3D6B4A] text-white",
                    promo.value === "promo_qualifier" &&
                      formData.promo_type === promo.value &&
                      "bg-[#B85C38] hover:bg-[#A04E2E] text-white",
                    promo.value.startsWith("boost") &&
                      formData.promo_type === promo.value &&
                      "bg-[#C4A35A] hover:bg-[#B8963E] text-[#2C2416]"
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

          {/* Odds and Stake */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-2 block">
                Odds (American)
              </label>
              <Input
                ref={oddsInputRef}
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
            <div className="space-y-4 pt-2 border-t border-dashed">
              {/* Selection Name */}
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

              {/* Opposing Odds - For precise vig calculation */}
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Opposing Line <span className="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Input
                  type="number"
                  placeholder="e.g. -180 for the other side"
                  value={formData.opposing_odds}
                  onChange={(e) => updateField("opposing_odds", e.target.value)}
                  className="font-mono"
                />
                {calculatedVig !== null && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Calculated hold: {(calculatedVig * 100).toFixed(1)}% (overrides {(defaultVig * 100).toFixed(1)}% default)
                  </p>
                )}
              </div>

              {/* Event Date */}
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Event Date <span className="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Input
                  type="date"
                  value={formData.event_date}
                  onChange={(e) => updateField("event_date", e.target.value)}
                />
              </div>

              {/* Winnings Cap */}
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Winnings Cap ($) <span className="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Input
                  type="number"
                  placeholder="Optional max bonus winnings"
                  value={formData.winnings_cap}
                  onChange={(e) => updateField("winnings_cap", e.target.value)}
                />
              </div>

              {/* Notes */}
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Notes <span className="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Input
                  placeholder="Optional notes"
                  value={formData.notes}
                  onChange={(e) => updateField("notes", e.target.value)}
                  className="ruled-lines"
                />
              </div>
            </div>
          )}

          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button 
              type="submit" 
              disabled={updateBet.isPending}
            >
              {updateBet.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save Changes"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// Calculate hold from two American odds
function calculateHoldFromOdds(odds1: number, odds2: number): number | null {
  if (odds1 === 0 || odds2 === 0) return null;
  if (Math.abs(odds1) < 100 || Math.abs(odds2) < 100) return null;
  
  const decimal1 = americanToDecimal(odds1);
  const decimal2 = americanToDecimal(odds2);
  
  const impliedProb1 = 1 / decimal1;
  const impliedProb2 = 1 / decimal2;
  
  const hold = (impliedProb1 + impliedProb2) - 1;
  return hold > 0 ? hold : null;
}

