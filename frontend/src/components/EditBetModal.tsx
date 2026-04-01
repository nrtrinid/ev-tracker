"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { SmartOddsInput, type SmartOddsInputRef } from "@/components/SmartOddsInput";
import { Button, type ButtonProps } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useUpdateBet } from "@/lib/hooks";
import {
  MARKETS,
  PROMO_TYPES,
  PROMO_TYPE_CONFIG,
  SPORTS,
  SPORTSBOOKS,
  type Bet,
  type PromoType,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type SportsbookButtonVariant = NonNullable<ButtonProps["variant"]>;

const sportsbookVariants: Record<string, SportsbookButtonVariant> = {
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

interface EditBetFormData {
  sportsbook: string;
  sport: string;
  event: string;
  market: string;
  promo_type: PromoType;
  odds: string;
  stake: string;
  boost_percent: string;
  payout_override: string;
  opposing_odds: string;
  notes: string;
  event_date: string;
}

function isBoostPromoType(promoType: PromoType): boolean {
  return promoType.startsWith("boost");
}

export function EditBetModal({ bet, open, onOpenChange }: EditBetModalProps) {
  const updateBet = useUpdateBet();
  const [showAdvanced, setShowAdvanced] = useState(false);
  const oddsInputRef = useRef<SmartOddsInputRef>(null);
  const opposingOddsInputRef = useRef<SmartOddsInputRef>(null);

  const [formData, setFormData] = useState<EditBetFormData>({
    sportsbook: "",
    sport: "",
    event: "",
    market: "ML",
    promo_type: "bonus_bet",
    odds: "",
    stake: "",
    boost_percent: "",
    payout_override: "",
    opposing_odds: "",
    notes: "",
    event_date: "",
  });

  useEffect(() => {
    if (!bet) return;

    setFormData({
      sportsbook: bet.sportsbook,
      sport: bet.sport,
      event: bet.event,
      market: bet.market,
      promo_type: bet.promo_type,
      odds: String(bet.odds_american),
      stake: String(bet.stake),
      boost_percent: bet.boost_percent ? String(bet.boost_percent) : "",
      payout_override:
        bet.payout_override != null
          ? String(bet.payout_override)
          : !isBoostPromoType(bet.promo_type) && bet.winnings_cap != null
            ? String(bet.winnings_cap)
            : "",
      opposing_odds: bet.opposing_odds != null ? String(bet.opposing_odds) : "",
      notes: bet.notes || "",
      event_date: bet.event_date || "",
    });
    setShowAdvanced(false);
  }, [bet]);

  const updateField = (field: keyof EditBetFormData, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const oddsNum = oddsInputRef.current
    ? oddsInputRef.current.getSignedValue()
    : (formData.odds.trim() !== "" ? parseFloat(formData.odds) || 0 : 0);
  const stakeNum = parseFloat(formData.stake) || 0;
  const opposingOddsNum = opposingOddsInputRef.current
    ? opposingOddsInputRef.current.getSignedValue()
    : (formData.opposing_odds.trim() !== "" ? parseFloat(formData.opposing_odds) || 0 : 0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bet) return;

    if (!formData.sportsbook || !formData.sport || !oddsNum || !stakeNum) {
      toast.error("Missing required fields");
      return;
    }

    const boostPercentRaw = parseFloat(formData.boost_percent);
    const boostPercentNum = isNaN(boostPercentRaw) ? 0 : boostPercentRaw;
    if (
      formData.promo_type === "boost_custom" &&
      (isNaN(boostPercentRaw) || boostPercentNum < 0 || boostPercentNum > 300)
    ) {
      toast.error("Boost percent must be between 0 and 300");
      return;
    }

    const payoutOverrideRaw = parseFloat(formData.payout_override);
    if (
      formData.payout_override.trim() !== "" &&
      (isNaN(payoutOverrideRaw) || payoutOverrideRaw <= 0)
    ) {
      toast.error("Payout override must be greater than 0");
      return;
    }

    const payoutOverrideNum =
      !isNaN(payoutOverrideRaw) && payoutOverrideRaw > 0 ? payoutOverrideRaw : null;
    const trimmedNotes = formData.notes.trim();

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
              ? Math.max(0, Math.min(300, boostPercentNum))
              : null,
          winnings_cap: isBoostPromoType(formData.promo_type) ? undefined : null,
          payout_override: payoutOverrideNum,
          opposing_odds: formData.opposing_odds.trim() !== "" ? opposingOddsNum : null,
          notes: trimmedNotes || null,
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
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Bet</DialogTitle>
          <DialogDescription>
            Update the ticket details and save your changes.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Sportsbook</label>
            <div className="grid grid-cols-4 gap-2">
              {SPORTSBOOKS.map((book) => (
                <Button
                  key={book}
                  type="button"
                  variant={formData.sportsbook === book ? sportsbookVariants[book] : "outline"}
                  size="sm"
                  className={cn(
                    "h-10 text-xs px-2",
                    formData.sportsbook === book && "ring-2 ring-offset-2",
                  )}
                  onClick={() => updateField("sportsbook", book)}
                >
                  {book === "ESPN Bet" ? "ESPN" : book.split(" ")[0]}
                </Button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">Sport</label>
            <div className="flex flex-wrap gap-2">
              {SPORTS.map((sport) => (
                <Button
                  key={sport}
                  type="button"
                  variant={formData.sport === sport ? "default" : "outline"}
                  size="sm"
                  onClick={() => {
                    updateField("sport", sport);
                    setTimeout(() => {
                      oddsInputRef.current?.focus();
                    }, 50);
                  }}
                >
                  {sport}
                </Button>
              ))}
            </div>
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
            {(formData.market === "Prop" ||
              formData.market === "Futures" ||
              formData.market === "SGP") && (
              <p className="text-xs text-muted-foreground mt-1.5">
                {formData.market === "SGP" ? "12%" : "7%"} default vig for {formData.market}
              </p>
            )}
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">Promo Type</label>
            <div className="flex flex-wrap gap-2">
              {PROMO_TYPES.map((promo) => {
                const config = PROMO_TYPE_CONFIG[promo.value];
                const isSelected = formData.promo_type === promo.value;
                return (
                  <Button
                    key={promo.value}
                    type="button"
                    variant={isSelected ? "default" : "outline"}
                    size="sm"
                    className={cn(
                      isSelected && cn(config.selectedBg, config.selectedText, config.ring),
                    )}
                    onClick={() => updateField("promo_type", promo.value)}
                  >
                    {promo.label}
                  </Button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <SmartOddsInput
              ref={oddsInputRef}
              value={formData.odds}
              onChange={(value) => updateField("odds", value)}
              placeholder="150"
              defaultSign={(bet?.odds_american ?? 0) < 0 ? "-" : "+"}
              americanOddsSeed={bet?.odds_american ?? null}
              label="Odds (American)"
              className="[&_input]:text-lg"
            />
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

          <button
            type="button"
            className="text-sm text-muted-foreground hover:text-foreground"
            onClick={() => setShowAdvanced((current) => !current)}
          >
            {showAdvanced ? "Hide" : "Show"} advanced options
          </button>

          {showAdvanced && (
            <div className="space-y-4 pt-2 border-t border-dashed">
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Selection Name <span className="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Input
                  placeholder="e.g. Ravens -3, Jokic 25+ Pts, Oilers ML"
                  value={formData.event}
                  onChange={(e) => updateField("event", e.target.value)}
                />
              </div>

              <div>
                <SmartOddsInput
                  ref={opposingOddsInputRef}
                  value={formData.opposing_odds}
                  onChange={(value) => updateField("opposing_odds", value)}
                  placeholder="180"
                  defaultSign={(bet?.opposing_odds ?? 0) < 0 ? "-" : "+"}
                  americanOddsSeed={bet?.opposing_odds ?? null}
                  label="Opposing Line (optional)"
                  className="[&_input]:font-mono"
                />
              </div>

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

              <div>
                <label className="text-sm font-medium mb-2 block">
                  Payout Override ($) <span className="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Input
                  type="text"
                  inputMode="decimal"
                  placeholder={bet?.win_payout ? `Current: ${bet.win_payout.toFixed(2)}` : "e.g. 35.50"}
                  value={formData.payout_override}
                  onChange={(e) => updateField("payout_override", e.target.value)}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Override if the book&apos;s payout differs from the calculated return.
                </p>
              </div>

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
