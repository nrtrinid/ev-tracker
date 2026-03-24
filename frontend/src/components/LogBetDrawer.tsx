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
  PROMO_TYPE_CONFIG,
  type BetCreate,
  type PromoType,
  type ScannedBetData,
  type TutorialPracticeBet,
} from "@/lib/types";
import {
  formatCurrency,
  americanToDecimal,
  cn,
  calculateHoldFromOdds,
  calculateStealthStake,
} from "@/lib/utils";
import { Loader2, Plus, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";

// Smart vig defaults based on market type
const MARKET_VIG: Record<string, number> = {
  ML: 0.045,
  Spread: 0.045,
  Total: 0.045,
  Parlay: 0.15,
  Prop: 0.09,
  Futures: 0.20,
  SGP: 0.20,
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
  initialValues?: ScannedBetData;
  practiceMode?: boolean;
  onPracticeLogged?: (bet: TutorialPracticeBet) => void;
  onLogged?: () => void;
  onSubmitOverride?: (payload: BetCreate) => Promise<void>;
}

// CLV metadata is read-only scanner passthrough — never user-editable
interface ClvMeta {
  pinnacle_odds_at_entry?: number;
  commence_time?: string;
  clv_team?: string;
  clv_sport_key?: string;
  clv_event_id?: string;
  true_prob_at_entry?: number;
  source_event_id?: string;
  source_market_key?: string;
  source_selection_key?: string;
  participant_name?: string;
  participant_id?: string;
  selection_side?: string;
  line_value?: number;
  selection_meta?: Record<string, unknown>;
  surface?: ScannedBetData["surface"];
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
  event_date: string;
  opposing_odds: string;
  boost_percent: string;
  payout_override: string;
  notes: string;
}

interface BoostRowValue {
  type: "boost";
  book: string;
  boosted: string;
  fair: string | null;
  fairPct: string | null;
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

function isBoostRowValue(value: unknown): value is BoostRowValue {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<BoostRowValue>;
  return candidate.type === "boost" &&
    typeof candidate.book === "string" &&
    typeof candidate.boosted === "string" &&
    (typeof candidate.fair === "string" || candidate.fair === null) &&
    (typeof candidate.fairPct === "string" || candidate.fairPct === null);
}

function buildScannerInitialStake(initialValues: ScannedBetData): string {
  const isPromo = initialValues.promo_type !== "standard";
  if (isPromo) {
    return "10.00";
  }
  const stealth =
    initialValues.stealth_kelly_stake ??
    (initialValues.raw_kelly_stake != null
      ? calculateStealthStake(initialValues.raw_kelly_stake)
      : undefined);
  const stake = stealth ?? initialValues.kelly_suggestion;
  return stake != null && stake > 0 ? stake.toFixed(2) : "";
}

function buildInitialFormState(initialValues?: ScannedBetData): FormState {
  if (initialValues) {
    const initialEventDate =
      initialValues.commence_time
        ? new Date(initialValues.commence_time).toISOString().slice(0, 10)
        : new Date().toISOString().slice(0, 10);

    return {
      sportsbook: initialValues.sportsbook,
      sport: initialValues.sport,
      market: initialValues.market,
      promo_type: initialValues.promo_type,
      odds: String(initialValues.odds_american),
      stake: buildScannerInitialStake(initialValues),
      event: initialValues.event,
      event_date: initialEventDate,
      opposing_odds: initialValues.opposing_odds != null ? String(initialValues.opposing_odds) : "",
      boost_percent: initialValues.boost_percent != null ? String(initialValues.boost_percent) : "",
      payout_override: "",
      notes: "",
    };
  }

  return {
    sportsbook: getStickySportsbook(),
    sport: "",
    market: "ML",
    promo_type: getStickyPromoType(),
    odds: "",
    stake: "",
    event: "",
    event_date: new Date().toISOString().slice(0, 10),
    opposing_odds: "",
    boost_percent: "",
    payout_override: "",
    notes: "",
  };
}

export function LogBetDrawer({
  open,
  onOpenChange,
  initialValues,
  practiceMode = false,
  onPracticeLogged,
  onLogged,
  onSubmitOverride,
}: LogBetDrawerProps) {
  const isScannerFlow = !!initialValues;
  const isTutorialPracticeFlow = isScannerFlow && practiceMode;
  const [formState, setFormState] = useState<FormState>(() => buildInitialFormState(initialValues));
  const [showManualSetup, setShowManualSetup] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // CLV metadata — captured from scanner, passed through silently to backend
  const clvMeta = useRef<ClvMeta>({});
  if (initialValues) {
    clvMeta.current = {
      pinnacle_odds_at_entry: initialValues.pinnacle_odds_at_entry,
      commence_time: initialValues.commence_time,
      clv_team: initialValues.clv_team,
      clv_sport_key: initialValues.clv_sport_key,
      clv_event_id: initialValues.clv_event_id,
      true_prob_at_entry: initialValues.true_prob_at_entry,
      source_event_id: initialValues.source_event_id,
      source_market_key: initialValues.source_market_key,
      source_selection_key: initialValues.source_selection_key,
      participant_name: initialValues.participant_name,
      participant_id: initialValues.participant_id,
      selection_side: initialValues.selection_side,
      line_value: initialValues.line_value,
      selection_meta: initialValues.selection_meta,
      surface: initialValues.surface,
    };
  }

  const oddsInputRef = useRef<SmartOddsInputRef>(null);
  const opposingOddsInputRef = useRef<SmartOddsInputRef>(null);
  const createBet = useCreateBet();
  const [customSubmitPending, setCustomSubmitPending] = useState(false);

  // Initialize sticky values on mount (skip when pre-filled from scanner)
  useEffect(() => {
    if (open) {
      setFormState(buildInitialFormState(initialValues));
      setShowManualSetup((initialValues?.promo_type ?? getStickyPromoType()) !== "standard");
      setTimeout(() => {
        const input = document.querySelector('[data-odds-input]') as HTMLInputElement;
        input?.focus();
      }, 300);
    }
  }, [open, initialValues]);

  // Parse numeric values - get signed values from SmartOddsInput refs.
  // Fallback to formState.odds so EV card and submit enable when drawer is prefilled from scanner before ref has updated.
  const oddsNum =
    oddsInputRef.current?.getSignedValue() ||
    (formState.odds.trim() !== "" ? parseFloat(formState.odds) || 0 : 0);
  const stakeNum = parseFloat(formState.stake) || 0;
  const opposingOddsNum = opposingOddsInputRef.current?.getSignedValue() || 0;
  const boostPercentRaw = parseFloat(formState.boost_percent);
  const boostPercentNum = isNaN(boostPercentRaw) ? 0 : boostPercentRaw;
  const boostPercentClamped = Math.max(0, Math.min(300, boostPercentNum));
  const payoutOverrideNum = parseFloat(formState.payout_override) || 0;

  // Get smart vig default based on market
  const defaultVig = MARKET_VIG[formState.market] || 0.045;

  // Calculate actual vig if opposing odds provided
  const calculatedVig = opposingOddsNum !== 0 
    ? calculateHoldFromOdds(oddsNum, opposingOddsNum)
    : null;

  // Use calculated vig if available, otherwise smart default
  const effectiveVig = calculatedVig !== null ? calculatedVig : defaultVig;

  // Calculate EV for display — use scanner's true_prob when available (accurate +EV for standard bets)
  const ev = calculateEVClient(
    oddsNum,
    stakeNum,
    formState.promo_type,
    boostPercentClamped,
    payoutOverrideNum || undefined,
    effectiveVig,
    clvMeta.current.true_prob_at_entry,
  );

  // Vig nudge: only relevant when we're using a vig estimate (not a scanner bet with true_prob)
  // const hasTrueProb = ... // Removed to fix lint error
  // const betterVig = ... // Removed to fix lint error
  // const evWithBetterVig = ... // Removed to fix lint error
  // const vigNudgeValue = evWithBetterVig.evTotal - ev.evTotal; // Removed to fix lint error

  const invalidBoost = formState.promo_type === "boost_custom" && (isNaN(boostPercentRaw) || boostPercentNum < 0 || boostPercentNum > 300);
  const duplicateState = initialValues?.scanner_duplicate_state ?? "new";
  const hasDuplicateExposure = duplicateState === "already_logged" || duplicateState === "better_now";
  const isSubmitting = createBet.isPending || customSubmitPending;
  const selectedPromoLabel =
    PROMO_TYPES.find((promo) => promo.value === formState.promo_type)?.label ?? "Standard";

  const bestLoggedOdds = initialValues?.best_logged_odds_american;
  const currentOdds = initialValues?.current_odds_american ?? initialValues?.odds_american;

  const updateField = (field: keyof FormState, value: string) => {
    setFormState(prev => ({ ...prev, [field]: value }));
  };

  const isValid =
    !!formState.sportsbook &&
    !!formState.sport &&
    formState.odds.trim() !== "" &&
    stakeNum > 0;
  // Removed unused showVigNudge

  const handleLogBet = async (keepOpen: boolean) => {
    if (!isValid) return;

    // Save sticky values
    localStorage.setItem("ev-tracker-sportsbook", formState.sportsbook);
    localStorage.setItem("ev-tracker-promo-type", formState.promo_type);

    if (isTutorialPracticeFlow) {
      const tutorialBet: TutorialPracticeBet = {
        id: `tutorial-practice-${Date.now()}`,
        created_at: new Date().toISOString(),
        event_date: formState.event_date || new Date().toISOString().slice(0, 10),
        sport: formState.sport,
        event: formState.event || `${formState.sport} Practice Ticket`,
        market: formState.market,
        sportsbook: formState.sportsbook,
        surface: clvMeta.current.surface ?? "straight_bets",
        promo_type: formState.promo_type,
        odds_american: oddsNum,
        stake: stakeNum,
        win_payout: ev.winPayout,
        ev_total: ev.evTotal,
        ev_per_dollar: stakeNum > 0 ? ev.evTotal / stakeNum : 0,
      };

      toast.success("Practice ticket saved", {
        description: "This tutorial ticket is local only. We are taking you back Home to review where it appears in the tracker.",
      });
      onOpenChange(false);
      onPracticeLogged?.(tutorialBet);
      return;
    }

    // Optimistic toast for speed
    const toastId = toast.loading("Logging bet...");

    try {
      const payload: BetCreate = {
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
        event_date: formState.event_date || undefined,
        // CLV passthrough — silently stored for closing-line tracking
        ...clvMeta.current,
      };

      if (onSubmitOverride) {
        setCustomSubmitPending(true);
        try {
          await onSubmitOverride(payload);
        } finally {
          setCustomSubmitPending(false);
        }
      } else {
        await createBet.mutateAsync(payload);
      }

      toast.success("Bet logged!", {
        id: toastId,
        description: `${ev.evTotal >= 0 ? "+" : ""}${formatCurrency(ev.evTotal)} EV on ${formState.sportsbook}`,
      });
      onLogged?.();

      if (keepOpen) {
        // Batch mode: Clear bet-specific fields, keep sportsbook/sport/market/promo
        setFormState(prev => ({
          ...prev,
          odds: "",
          stake: "",
          event: "",
          event_date: prev.event_date,
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
          event_date: formState.event_date || new Date().toISOString().slice(0, 10),
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
          <p className="text-left text-sm text-muted-foreground">
            {isTutorialPracticeFlow
              ? "Practice the final step here. This ticket stays local to the tutorial and will not touch your real stats or bankroll."
              : isScannerFlow
              ? "Step 3 of 3: confirm what you placed, then log it."
              : "Quick Log starts with the essentials. We assume a standard moneyline bet unless you change the setup."}
          </p>
        </SheetHeader>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-4 pb-32">
          {hasDuplicateExposure && (
            <div className="mb-4 rounded-lg border border-[#B85C38]/30 bg-[#B85C38]/10 px-3 py-2 text-xs text-[#8B3D20]">
              {duplicateState === "better_now" ? (
                <>
                  <p className="font-semibold">You already logged this side at a lower price.</p>
                  <p className="mt-0.5">
                    You already logged this side at {bestLoggedOdds != null ? formatAmerican(bestLoggedOdds) : "previous odds"}. The scanner now shows {currentOdds != null ? formatAmerican(currentOdds) : "a better line"}.
                  </p>
                </>
              ) : (
                <>
                  <p className="font-semibold">You already logged this side.</p>
                  <p className="mt-0.5">Logging again will increase exposure on the same outcome.</p>
                </>
              )}
            </div>
          )}

          {isScannerFlow ? (
            <div className="mb-4 rounded-xl border border-border bg-muted/40 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
                {isTutorialPracticeFlow ? "Tutorial Practice" : "Scanner Review"}
              </p>
              <p className="mt-1 text-sm font-semibold text-foreground">{formState.event}</p>
              <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-muted-foreground">Book</p>
                  <p className="font-medium text-foreground">{formState.sportsbook}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Market</p>
                  <p className="font-medium text-foreground">{formState.market}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Sport</p>
                  <p className="font-medium text-foreground">{formState.sport}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Date</p>
                  <p className="font-medium text-foreground">{formState.event_date}</p>
                </div>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {isTutorialPracticeFlow
                  ? "Use this practice ticket to learn where scanner plays get confirmed. Saving it here keeps everything local to the tutorial."
                  : "Only change the odds or stake below if your bet slip differed from the scanner card."}
              </p>
            </div>
          ) : (
            <>
              <div className="mb-4 rounded-xl border border-border bg-muted/40 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
                  Quick Log
                </p>
                <p className="mt-1 text-sm text-foreground">
                  Start with book, sport, odds, and stake. Open Bet Setup only if this ticket is not a normal moneyline cash bet.
                </p>
              </div>

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
            </>
          )}

          {/* Odds & Stake - Side by Side */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <SmartOddsInput
              ref={oddsInputRef}
              value={formState.odds}
              onChange={(value) => updateField("odds", value)}
              placeholder="150"
              defaultSign="+"
              label={isScannerFlow ? "Placed Odds" : "Odds"}
              className="[&_input]:h-12 [&_input]:text-lg"
            />
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                {isScannerFlow ? "Stake Placed" : "Stake"}
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
                {[5, 10, 25].map((amount) => (
                  <button
                    key={amount}
                    type="button"
                    onClick={() => updateField("stake", amount.toFixed(2))}
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

          {!isScannerFlow && (
            <div className="mb-4 rounded-lg border border-border bg-muted/30 p-3">
              <button
                type="button"
                onClick={() => setShowManualSetup((current) => !current)}
                className="flex w-full items-center justify-between text-left"
              >
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Bet Setup</p>
                  <p className="mt-0.5 text-sm text-foreground">
                    {formState.market} • {selectedPromoLabel}
                  </p>
                </div>
                {showManualSetup ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>

              {showManualSetup ? (
                <div className="mt-3 space-y-4">
                  <div>
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
                              : "bg-background text-muted-foreground hover:bg-secondary"
                          )}
                        >
                          {market}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-2 block">
                      Promo Type
                    </label>
                    <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1 pt-0.5">
                      {PROMO_TYPES.map((promo) => {
                        const config = PROMO_TYPE_CONFIG[promo.value];
                        const isSelected = formState.promo_type === promo.value;
                        return (
                          <button
                            key={promo.value}
                            type="button"
                            onClick={() => updateField("promo_type", promo.value)}
                            className={cn(
                              "flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap",
                              isSelected
                                ? cn(config.selectedBg, config.selectedText, config.ring)
                                : "bg-background text-muted-foreground hover:bg-secondary"
                            )}
                          >
                            {promo.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">
                  Leave this closed for a normal moneyline cash bet, or open it if you are logging a prop, parlay, or promo ticket.
                </p>
              )}
            </div>
          )}

          {/* Vig Nudge was shown here previously; EV now primarily relies on sharp fair odds when available. */}

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
              <div className="mt-1">
                {invalidBoost ? (
                  <p className="text-xs text-[#B85C38]">Enter a value between 0 and 300.</p>
                ) : (
                  <p className="text-xs text-muted-foreground">Using {boostPercentClamped.toFixed(0)}% boost.</p>
                )}
              </div>
            </div>
          )}

          {/* Advanced Options Toggle */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1 text-xs text-muted-foreground mb-3"
          >
            {showAdvanced ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {showAdvanced ? "Hide" : "Show"} {isScannerFlow ? "more details" : "advanced options"}
          </button>

          {showAdvanced && (
            <div className="space-y-3 mb-4 p-3 rounded-lg bg-muted/50 border border-border">
              {isScannerFlow && (
                <>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-2 block">
                      Promo Type
                    </label>
                    <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1 pt-0.5">
                      {PROMO_TYPES.map((promo) => {
                        const config = PROMO_TYPE_CONFIG[promo.value];
                        const isSelected = formState.promo_type === promo.value;
                        return (
                          <button
                            key={promo.value}
                            type="button"
                            onClick={() => updateField("promo_type", promo.value)}
                            className={cn(
                              "flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap",
                              isSelected
                                ? cn(config.selectedBg, config.selectedText, config.ring)
                                : "bg-background text-muted-foreground hover:bg-secondary"
                            )}
                          >
                            {promo.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div>
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
                              : "bg-background text-muted-foreground hover:bg-secondary"
                          )}
                        >
                          {market}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {/* Selection Name */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Selection Name
                </label>
                <Input
                  type="text"
                  placeholder="e.g. Ravens -3, Jokic 25+ Pts, Oilers ML"
                  value={formState.event}
                  onChange={(e) => updateField("event", e.target.value)}
                  className="h-10"
                />
              </div>

              {/* Event Date */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Event Date
                </label>
                <Input
                  type="date"
                  value={formState.event_date}
                  onChange={(e) => updateField("event_date", e.target.value)}
                  className="h-10"
                />
              </div>

              {/* Opposing Odds (optional; mainly for manual bets without Pinnacle data) */}
              <div>
                <div data-opposing-odds-input>
                  <SmartOddsInput
                    ref={opposingOddsInputRef}
                    value={formState.opposing_odds}
                    onChange={(value) => updateField("opposing_odds", value)}
                    placeholder="180"
                    defaultSign="-"
                    label="Opposing Odds"
                    className="[&_input]:h-10"
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Optional: enter the other side of this market if you want a more precise EV estimate without a sharp line.
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
                  Override if the book&apos;s payout differs from calculated
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
          {isValid && (() => {
            const promoType = formState.promo_type;
            const trueProb = clvMeta.current.true_prob_at_entry;
            const fairProbPct = trueProb != null ? (trueProb * 100).toFixed(1) : null;
            const fairDecimal = trueProb != null && trueProb > 0 ? 1 / trueProb : null;
            const fairAmerican = fairDecimal
              ? formatAmerican(
                  fairDecimal >= 2 ? (fairDecimal - 1) * 100 : -100 / (fairDecimal - 1)
                )
              : null;

            const unboostedDecimal = oddsNum !== 0
              ? americanToDecimal(oddsNum)
              : formState.odds.trim() !== ""
              ? americanToDecimal(parseFloat(formState.odds))
              : null;

            const bookAmerican = formatAmerican(
              oddsNum || parseFloat(formState.odds) || 0
            );

            const isBoost =
              promoType === "boost_30" ||
              promoType === "boost_50" ||
              promoType === "boost_100" ||
              promoType === "boost_custom";

            let headlineLabel = "Expected Value";
            const rows: { label: string; value: string }[] = [];

            if (promoType === "bonus_bet") {
              headlineLabel = "Expected Cash Value";
              if (stakeNum > 0 && unboostedDecimal) {
                const retention =
                  (unboostedDecimal - 1) *
                  (trueProb ?? (fairProbPct ? parseFloat(fairProbPct) / 100 : 0));
                rows.push({
                  label: "Retention",
                  value: `${(retention * 100).toFixed(1)}% of stake`,
                });
              }
              if (fairAmerican && fairProbPct) {
                rows.push({
                  label: "Book vs Fair",
                  value: `Book: ${bookAmerican} | Fair: ${fairAmerican} (${fairProbPct}%)`
                });
              }
            } else if (isBoost) {
              headlineLabel = "Boosted EV";
              if (unboostedDecimal) {
                const baseDecimal = unboostedDecimal;
                const baseProfit = baseDecimal - 1;
                const boostFactor =
                  promoType === "boost_30"
                    ? 0.3
                    : promoType === "boost_50"
                    ? 0.5
                    : promoType === "boost_100"
                    ? 1.0
                    : boostPercentClamped / 100;
                const boostedProfit = baseProfit * (1 + boostFactor);
                const boostedDecimal = 1 + boostedProfit;
                const boostedAmerican = formatAmerican(
                  boostedDecimal >= 2
                    ? (boostedDecimal - 1) * 100
                    : -100 / (boostedDecimal - 1)
                );
                rows.push({
                  label: "Book vs Fair",
                  value: JSON.stringify({
                    type: "boost",
                    book: bookAmerican,
                    boosted: boostedAmerican,
                    fair: fairAmerican,
                    fairPct: fairProbPct,
                  }),
                });
              }
            } else if (promoType === "promo_qualifier" || promoType === "no_sweat") {
              headlineLabel = "Qualifying Cost";
              if (fairAmerican && fairProbPct) {
                rows.push({
                  label: "Book vs Fair",
                  value: `Book: ${bookAmerican} | Fair: ${fairAmerican} (${fairProbPct}%)`,
                });
              }
            } else {
              // Standard cash bet
              if (fairAmerican && fairProbPct) {
                rows.push({
                  label: "Book vs Fair",
                  value: `Book: ${bookAmerican} | Fair: ${fairAmerican} (${fairProbPct}%)`,
                });
              }
            }

            return (
              <div
                className={cn(
                  "rounded-lg border p-3 mb-4 space-y-1.5",
                  ev.evTotal >= 0
                    ? "bg-[#4A7C59]/10 border-[#4A7C59]/20"
                    : "bg-[#B85C38]/10 border-[#B85C38]/20"
                )}
              >
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">{headlineLabel}</span>
                  <span
                    className={cn(
                      "font-mono font-semibold",
                      ev.evTotal >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]"
                    )}
                  >
                    {ev.evTotal >= 0 ? "+" : ""}
                    {formatCurrency(ev.evTotal)}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-muted-foreground">To Win</span>
                  <span className="font-mono text-sm">
                    {formatCurrency(ev.winPayout)}
                  </span>
                </div>
                {rows.map((row) => {

                  let parsed: unknown = null;
                  try {
                    parsed = JSON.parse(row.value);
                  } catch {
                    parsed = null;
                  }
                  const boostRow = isBoostRowValue(parsed) ? parsed : null;

                  return (
                    <div
                      key={row.label}
                      className="flex justify-between items-center text-xs text-muted-foreground/90 mt-0.5"
                    >
                      <span>{row.label}</span>
                      <span className="font-mono text-[11px] text-right">
                        {boostRow ? (
                          <>
                            Book:{" "}
                            <span className="line-through text-muted-foreground/70 mr-1">
                              {boostRow.book}
                            </span>
                            <span className="text-foreground">
                              {boostRow.boosted}
                            </span>
                            {boostRow.fair && boostRow.fairPct && (
                              <>
                                {" "}
                                | Fair: {boostRow.fair} ({boostRow.fairPct}%)
                              </>
                            )}
                          </>
                        ) : (
                          row.value
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </div>

        {/* Sticky Footer */}
        <div className="absolute bottom-0 left-0 right-0 bg-background border-t border-border p-4 flex gap-3">
          {isScannerFlow ? (
            <>
              <Button
                variant="outline"
                className="flex-1 h-12"
                onClick={() => setShowAdvanced((current) => !current)}
                disabled={isSubmitting}
              >
                {showAdvanced ? "Hide Details" : "More Details"}
              </Button>
              <Button
                className="flex-1 h-12"
                onClick={() => handleLogBet(false)}
                disabled={!isValid || invalidBoost || isSubmitting}
              >
                {isSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isTutorialPracticeFlow ? (
                  "Save Practice Ticket"
                ) : hasDuplicateExposure ? (
                  "Log Another Ticket"
                ) : (
                  "Confirm & Log Bet"
                )}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                className="flex-1 h-12"
                onClick={() => handleLogBet(true)}
                disabled={!isValid || invalidBoost || isSubmitting}
              >
                {isSubmitting ? (
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
                disabled={!isValid || invalidBoost || isSubmitting}
              >
                {isSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  hasDuplicateExposure ? "Log Another Ticket" : "Log Bet"
                )}
              </Button>
            </>
          )}
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
  vig: number = 0.045,
  trueProb?: number,
): { evTotal: number; winPayout: number } {
  if (oddsAmerican === 0 || stake <= 0) {
    return { evTotal: 0, winPayout: 0 };
  }

  const unboostedDecimal = americanToDecimal(oddsAmerican);
  let decimalOdds = unboostedDecimal;
  
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
  
  // Calculate win probability from UNBOOSTED odds (the true market)
  const winProbability = 1 / unboostedDecimal;
  // Removed unused fairProb

  let winPayout: number;
  let evTotal: number;

  if (promoType === "bonus_bet") {
    // Bonus bet: stake not returned on win
    const calculatedPayout = stake * (decimalOdds - 1);
    winPayout = payoutOverride || calculatedPayout;
    // EV = stake × (1 - 1/decimal_odds) - you're not risking real money
    evTotal = stake * (1 - (1 / unboostedDecimal));
  } else if (effectiveBoost > 0) {
    // Boosted bet: EV comes from the boost value minus vig
    const calculatedPayout = stake * decimalOdds;
    winPayout = payoutOverride || calculatedPayout;
    // EV = win_probability × boost_amount - vig
    const potentialExtra = effectiveBoost * (unboostedDecimal - 1);
    const boostValue = winProbability * potentialExtra;
    const evPerDollar = boostValue - vig;
    evTotal = stake * evPerDollar;
  } else if (trueProb !== undefined) {
    // Scanner bet: use de-vigged Pinnacle probability for accurate EV
    const calculatedPayout = stake * decimalOdds;
    winPayout = payoutOverride || calculatedPayout;
    evTotal = stake * (trueProb * unboostedDecimal - 1);
  } else {
    // Standard bet logged manually: estimate cost as -vig
    const calculatedPayout = stake * decimalOdds;
    winPayout = payoutOverride || calculatedPayout;
    evTotal = stake * -vig;
  }

  return { evTotal, winPayout };
}

function formatAmerican(odds: number): string {
  const rounded = Math.round(odds);
  if (rounded === 0) return "0";
  return rounded > 0 ? `+${rounded}` : `${rounded}`;
}
