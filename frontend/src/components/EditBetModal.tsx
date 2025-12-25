"use client";

import { useState, useEffect } from "react";
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
import { cn, americanToDecimal } from "@/lib/utils";
import { Loader2, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";

interface EditBetModalProps {
  bet: Bet | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EditBetModal({ bet, open, onOpenChange }: EditBetModalProps) {
  const updateBet = useUpdateBet();
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [formData, setFormData] = useState({
    sportsbook: "",
    sport: "",
    event: "",
    market: "",
    promo_type: "bonus_bet" as PromoType,
    odds: "",
    stake: "",
    boost_percent: "",
    winnings_cap: "",
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
        notes: bet.notes || "",
        event_date: bet.event_date || "",
      });
      // Auto-expand advanced if bet has these fields filled
      setShowAdvanced(!!(bet.winnings_cap || bet.notes));
    }
  }, [bet]);

  const updateField = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bet) return;

    const oddsNum = parseFloat(formData.odds);
    const stakeNum = parseFloat(formData.stake);

    if (!formData.sportsbook || !formData.sport || !oddsNum || !stakeNum) {
      toast.error("Missing required fields");
      return;
    }

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
              ? parseFloat(formData.boost_percent) || undefined
              : undefined,
          winnings_cap: parseFloat(formData.winnings_cap) || undefined,
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

  // Calculate EV preview
  const oddsNum = parseFloat(formData.odds) || 0;
  const stakeNum = parseFloat(formData.stake) || 0;
  const decimalOdds = oddsNum !== 0 ? americanToDecimal(oddsNum) : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Bet</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* === CORE FIELDS (Always Visible) === */}
          
          {/* Sportsbook */}
          <div>
            <label className="text-sm font-medium mb-2 block">Sportsbook</label>
            <div className="grid grid-cols-4 gap-1.5">
              {SPORTSBOOKS.map((book) => (
                <Button
                  key={book}
                  type="button"
                  variant={formData.sportsbook === book ? "default" : "outline"}
                  size="sm"
                  className="h-9 text-xs px-1"
                  onClick={() => updateField("sportsbook", book)}
                >
                  {book === "ESPN Bet" ? "ESPN" : book.split(" ")[0]}
                </Button>
              ))}
            </div>
          </div>

          {/* Sport */}
          <div>
            <label className="text-sm font-medium mb-2 block">Sport</label>
            <div className="flex flex-wrap gap-1.5">
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

          {/* Selection */}
          <div>
            <label className="text-sm font-medium mb-2 block">Selection Name</label>
            <Input
              placeholder="e.g. Lakers -5, Bills SGP, LeBron Over"
              value={formData.event}
              onChange={(e) => updateField("event", e.target.value)}
            />
          </div>

          {/* Market */}
          <div>
            <label className="text-sm font-medium mb-2 block">Market</label>
            <div className="flex flex-wrap gap-1.5">
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

          {/* Promo Type */}
          <div>
            <label className="text-sm font-medium mb-2 block">Promo Type</label>
            <div className="flex flex-wrap gap-1.5">
              {PROMO_TYPES.filter((p) => p.value !== "standard").map((promo) => (
                <Button
                  key={promo.value}
                  type="button"
                  variant={formData.promo_type === promo.value ? "default" : "outline"}
                  size="sm"
                  onClick={() => updateField("promo_type", promo.value)}
                >
                  {promo.label}
                </Button>
              ))}
            </div>
          </div>

          {/* Odds and Stake - No quick presets in edit mode */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-2 block">Odds (American)</label>
              <Input
                type="number"
                placeholder="+150 or -110"
                value={formData.odds}
                onChange={(e) => updateField("odds", e.target.value)}
                className="font-mono"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">Stake ($)</label>
              <Input
                type="number"
                placeholder="10.00"
                value={formData.stake}
                onChange={(e) => updateField("stake", e.target.value)}
                className="font-mono"
                step="0.01"
              />
            </div>
          </div>

          {/* Custom Boost Percent - Only for boost_custom */}
          {formData.promo_type === "boost_custom" && (
            <div>
              <label className="text-sm font-medium mb-2 block">Boost %</label>
              <Input
                type="number"
                placeholder="25"
                value={formData.boost_percent}
                onChange={(e) => updateField("boost_percent", e.target.value)}
              />
            </div>
          )}

          {/* === ADVANCED OPTIONS (Collapsible) === */}
          <button
            type="button"
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground w-full"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
            {showAdvanced ? "Hide" : "Show"} advanced options
          </button>

          {showAdvanced && (
            <div className="space-y-4 pl-2 border-l-2 border-muted">
              {/* Event Date */}
              <div>
                <label className="text-sm font-medium mb-2 block">Event Date</label>
                <Input
                  type="date"
                  value={formData.event_date}
                  onChange={(e) => updateField("event_date", e.target.value)}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Date of the game/event
                </p>
              </div>

              {/* Winnings Cap */}
              <div>
                <label className="text-sm font-medium mb-2 block">Winnings Cap ($)</label>
                <Input
                  type="number"
                  placeholder="Optional max bonus winnings"
                  value={formData.winnings_cap}
                  onChange={(e) => updateField("winnings_cap", e.target.value)}
                />
              </div>

              {/* Notes */}
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

          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateBet.isPending}>
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
