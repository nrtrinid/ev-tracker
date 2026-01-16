"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
} from "@/components/ui/sheet";
import { useBets, useUpdateBetResult, useDeleteBet, useCreateBet, useBalances } from "@/lib/hooks";
import { Skeleton } from "@/components/ui/skeleton";
import { EditBetModal } from "@/components/EditBetModal";
import type { Bet, BetResult } from "@/lib/types";
import { PROMO_TYPE_CONFIG } from "@/lib/types";
import { formatCurrency, formatOdds, cn, formatRelativeTime, formatShortDate, formatFullDateTime, americanToDecimal, decimalToAmerican, calculateImpliedProb, calculateHoldFromOdds } from "@/lib/utils";
import {
  Check,
  X,
  Clock,
  Trash2,
  ChevronDown,
  ChevronUp,
  Minus,
  Pencil,
  MoreHorizontal,
  RotateCcw,
  History,
  Target,
  Wallet,
  SlidersHorizontal,
} from "lucide-react";
import { toast } from "sonner";

const resultConfig: Record<
  BetResult,
  { label: string; color: string; bgColor: string; icon: React.ReactNode; stampClass: string }
> = {
  pending: {
    label: "Pending",
    color: "text-[#C4A35A]",
    bgColor: "bg-[#C4A35A]/10",
    icon: <Clock className="h-3.5 w-3.5" />,
    stampClass: "stamp",
  },
  win: {
    label: "Win",
    color: "text-[#4A7C59]",
    bgColor: "bg-[#4A7C59]/20",
    icon: <Check className="h-3.5 w-3.5" />,
    stampClass: "stamp-win",
  },
  loss: {
    label: "Loss",
    color: "text-[#B85C38]",
    bgColor: "bg-[#B85C38]/20",
    icon: <X className="h-3.5 w-3.5" />,
    stampClass: "stamp-loss",
  },
  push: {
    label: "Push",
    color: "text-[#6B5E4F]",
    bgColor: "bg-[#6B5E4F]/15",
    icon: <Minus className="h-3.5 w-3.5" />,
    stampClass: "stamp-push",
  },
  void: {
    label: "Void",
    color: "text-[#6B5E4F]",
    bgColor: "bg-[#6B5E4F]/15",
    icon: <Minus className="h-3.5 w-3.5" />,
    stampClass: "stamp",
  },
};

// ============ SPORTSBOOK COLOR MAP ============
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

const sportsbookTextColors: Record<string, string> = {
  DraftKings: "text-draftkings",
  FanDuel: "text-fanduel",
  BetMGM: "text-betmgm",
  Caesars: "text-caesars",
  "ESPN Bet": "text-espnbet",
  Fanatics: "text-fanatics",
  "Hard Rock": "text-hardrock",
  bet365: "text-bet365",
};

// Using shared PROMO_TYPE_CONFIG from types.ts

// ============ MARKET VIG DEFAULTS ============
const MARKET_VIG: Record<string, number> = {
  ML: 0.045,
  Spread: 0.045,
  Total: 0.045,
  Parlay: 0.15,
  Prop: 0.09,
  Futures: 0.20,
  SGP: 0.20,
};

// ============ HELPER FUNCTIONS ============
// Note: calculateImpliedProb, calculateHoldFromOdds, decimalToAmerican imported from @/lib/utils

function calculateBoostedOdds(originalOdds: number, boostPercent: number | null, promoType: string): number | null {
  // Check if this is a boost promo type
  const isBoost = promoType.startsWith("boost");
  if (!isBoost) return null;
  
  // Determine effective boost percentage
  let effectiveBoost = 0;
  if (promoType === "boost_30") {
    effectiveBoost = 0.3;
  } else if (promoType === "boost_50") {
    effectiveBoost = 0.5;
  } else if (promoType === "boost_100") {
    effectiveBoost = 1.0;
  } else if (promoType === "boost_custom") {
    if (boostPercent === null || boostPercent === 0) return null;
    effectiveBoost = boostPercent / 100;
  } else {
    return null;
  }
  
  // Calculate boosted decimal odds
  // Formula matches backend: base_winnings = stake * (decimal - 1)
  // extra_winnings = base_winnings * boost
  // total_payout = stake + base_winnings + extra_winnings
  // effective_decimal = total_payout / stake = 1 + base_winnings/stake + extra_winnings/stake
  // = 1 + (decimal - 1) + (decimal - 1) * boost = 1 + (decimal - 1) * (1 + boost)
  const originalDecimal = americanToDecimal(originalOdds);
  const baseProfit = originalDecimal - 1;
  const boostedProfit = baseProfit * (1 + effectiveBoost);
  const boostedDecimal = 1 + boostedProfit;
  
  return decimalToAmerican(boostedDecimal);
}

// ============ SHARED BET CARD BASE ============
// Compact layout with context-aware data row
interface BetCardBaseProps {
  bet: Bet;
  headerRight: React.ReactNode;
  footer: React.ReactNode;
  mode: "pending" | "settled";
}

function BetCardBase({ bet, headerRight, footer, mode }: BetCardBaseProps) {
  const [expanded, setExpanded] = useState(false);
  const borderColor = sportsbookColors[bet.sportsbook] || "bg-gray-400";
  const textColor = sportsbookTextColors[bet.sportsbook] || "text-gray-600";
  const promoConfig = PROMO_TYPE_CONFIG[bet.promo_type] || PROMO_TYPE_CONFIG.standard;
  
  // Short promo label (BB, 30%, etc.)
  const promoLabel = bet.promo_type === "boost_custom" && bet.boost_percent 
    ? `${bet.boost_percent}%`
    : promoConfig.short;
  
  // Only show promo badge if not standard
  const showPromoBadge = bet.promo_type !== "standard";

  // Calculate implied probability
  const impliedProb = calculateImpliedProb(bet.odds_american);
  
  // Calculate vig from opposing odds if present
  const calculatedVig = bet.opposing_odds 
    ? calculateHoldFromOdds(bet.odds_american, bet.opposing_odds)
    : null;
  
  // Use calculated vig or default based on market
  const displayVig = calculatedVig !== null 
    ? calculatedVig 
    : (MARKET_VIG[bet.market] || 0.045);

  return (
    <div className="border rounded-lg overflow-hidden flex card-hover bg-card">
      {/* Colored left border for sportsbook branding */}
      <div className={cn("w-1 shrink-0", borderColor)} />
      
      <div className="flex-1 p-4 space-y-3">
        {/* Header: Event name as title + actions */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            {/* Primary: Event name */}
            <p className="font-semibold text-sm leading-tight">{bet.event}</p>
            {/* Secondary: Sportsbook [Badge] Sport Market */}
            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <span className={cn("w-2 h-2 rounded-full shrink-0", borderColor)} />
              <span className={cn("font-semibold text-xs", textColor)}>{bet.sportsbook}</span>
              {showPromoBadge && (
                <span className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] font-semibold leading-none",
                  promoConfig.selectedBg,
                  promoConfig.selectedText,
                  promoConfig.ring
                )}>
                  {promoLabel}
                </span>
              )}
              <span className="text-xs text-muted-foreground">{bet.sport} • {bet.market}</span>
            </div>
          </div>
          {headerRight}
        </div>

        {/* Data Grid: 2x2 on mobile, 4-col on desktop */}
        {/* Mobile: Row 1 = Math (Odds, EV), Row 2 = Money (Stake, To Win) */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-3 md:gap-y-0 text-sm">
          {/* Odds - Col 1 on mobile, Col 1 on desktop */}
          <div className="order-1 md:order-1">
            <p className="text-muted-foreground text-xs">Odds</p>
            {(() => {
              const boostedOdds = calculateBoostedOdds(
                bet.odds_american,
                bet.boost_percent,
                bet.promo_type
              );
              
              if (boostedOdds) {
                return (
                  <div className="font-mono font-semibold flex flex-row items-baseline">
                    <span className="line-through text-muted-foreground/60 mr-1.5">
                      {formatOdds(bet.odds_american)}
                    </span>
                    <span className="text-foreground">{formatOdds(boostedOdds)}</span>
                  </div>
                );
              }
              return <p className="font-mono font-semibold">{formatOdds(bet.odds_american)}</p>;
            })()}
          </div>
          {/* EV - Col 2 on mobile, Col 3 on desktop */}
          <div className="order-2 md:order-3">
            <p className="text-muted-foreground text-xs">EV</p>
            <p className={cn("font-mono font-semibold", bet.ev_total >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
              {bet.ev_total >= 0 ? "+" : ""}{formatCurrency(bet.ev_total)}
            </p>
          </div>
          {/* Stake - Col 1 on mobile row 2, Col 2 on desktop */}
          <div className="order-3 md:order-2">
            <p className="text-muted-foreground text-xs">Stake</p>
            <p className="font-mono font-medium">{formatCurrency(bet.stake)}</p>
          </div>
          {/* To Win/Profit - Col 2 on mobile row 2, Col 4 on desktop */}
          <div className="order-4 md:order-4">
            <p className="text-muted-foreground text-xs">{mode === "settled" ? "Profit" : "To Win"}</p>
            <p className={cn(
              "font-mono font-semibold",
              mode === "settled"
                ? bet.real_profit !== null && bet.real_profit >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]"
                : "text-foreground"
            )} style={{ whiteSpace: "nowrap" }}>
              {mode === "settled"
                ? bet.real_profit !== null
                  ? (bet.real_profit >= 0 ? "+" : "") + formatCurrency(bet.real_profit)
                  : "—"
                : formatCurrency(bet.win_payout)}
            </p>
          </div>
        </div>

        {/* Footer - Varies by card type */}
        {footer}

        {/* Expandable Details */}
        <Button
          size="sm"
          variant="ghost"
          className="w-full text-xs text-muted-foreground"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Hide details" : "View details"}
          {expanded ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
        </Button>

        {expanded && (
          <div className="pt-3 border-t border-border">
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              {/* Slot 1: Opposing Line (if available) - Always Top Left */}
              {bet.opposing_odds ? (
                <div>
                  <p className="text-muted-foreground text-xs mb-0.5">Opposing Line</p>
                  <p className="font-mono text-sm text-foreground">{formatOdds(bet.opposing_odds)}</p>
                </div>
              ) : (
                <div>
                  <p className="text-muted-foreground text-xs mb-0.5">Req. Win %</p>
                  <p className="font-mono text-sm text-foreground">{(impliedProb * 100).toFixed(1)}%</p>
                </div>
              )}
              
              {mode === "pending" ? (
                <>
                  {/* PENDING LAYOUT */}
                  {/* Slot 2: Req. Win % (if Opposing Line present) or Vig */}
                  {bet.opposing_odds ? (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">Req. Win %</p>
                      <p className="font-mono text-sm text-foreground">{(impliedProb * 100).toFixed(1)}%</p>
                    </div>
                  ) : (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">Vig</p>
                      <p className="font-mono text-sm text-foreground">{(displayVig * 100).toFixed(1)}%</p>
                    </div>
                  )}
                  {/* Slot 3: Vig (if Opposing Line present) or EV per $ */}
                  {bet.opposing_odds ? (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">Vig</p>
                      <p className="font-mono text-sm text-foreground">{(displayVig * 100).toFixed(1)}%</p>
                    </div>
                  ) : (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">EV per $</p>
                      <p className="font-mono text-sm text-foreground">{(bet.ev_per_dollar * 100).toFixed(1)}%</p>
                    </div>
                  )}
                  {/* Slot 4: EV per $ (if Opposing Line present) or empty */}
                  {bet.opposing_odds && (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">EV per $</p>
                      <p className="font-mono text-sm text-foreground">{(bet.ev_per_dollar * 100).toFixed(1)}%</p>
                    </div>
                  )}
                </>
              ) : (
                <>
                  {/* SETTLED LAYOUT: Prioritize financial data (Win Payout) near Profit */}
                  {/* Slot 2: Win Payout - Directly under Profit (Top Right) */}
                  <div>
                    <p className="text-muted-foreground text-xs mb-0.5">Win Payout</p>
                    <p className="font-mono text-sm text-foreground">{formatCurrency(bet.win_payout)}</p>
                  </div>
                  {/* Slot 3: Req. Win % (if Opposing Line present) or EV per $ */}
                  {bet.opposing_odds ? (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">Req. Win %</p>
                      <p className="font-mono text-sm text-foreground">{(impliedProb * 100).toFixed(1)}%</p>
                    </div>
                  ) : (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">EV per $</p>
                      <p className="font-mono text-sm text-foreground">{(bet.ev_per_dollar * 100).toFixed(1)}%</p>
                    </div>
                  )}
                  {/* Slot 4: EV per $ (if Opposing Line present) or empty */}
                  {bet.opposing_odds && (
                    <div>
                      <p className="text-muted-foreground text-xs mb-0.5">EV per $</p>
                      <p className="font-mono text-sm text-foreground">{(bet.ev_per_dollar * 100).toFixed(1)}%</p>
                    </div>
                  )}
                </>
              )}
            </div>
            
            {/* Dates Section - Pushed to bottom, full width */}
            <div className="mt-3 pt-3 border-t border-border grid grid-cols-2 gap-x-4 gap-y-2">
              <div>
                <p className="text-muted-foreground text-xs mb-0.5">Event Date</p>
                <p className="font-medium text-sm text-foreground">{formatShortDate(bet.event_date)}</p>
              </div>
              <div>
                <p className="text-muted-foreground text-xs mb-0.5">Logged</p>
                <p className="font-medium text-sm text-foreground">{formatFullDateTime(bet.created_at)}</p>
              </div>
              {bet.settled_at && (
                <div className="col-span-2">
                  <p className="text-muted-foreground text-xs mb-0.5">Settled</p>
                  <p className="font-medium text-sm text-foreground">{formatFullDateTime(bet.settled_at)}</p>
                </div>
              )}
            </div>
            
            {/* Notes - Full width at bottom */}
            {bet.notes && (
              <div className="mt-3 pt-3 border-t border-border">
                <p className="text-muted-foreground text-xs mb-0.5">Notes</p>
                <p className="text-sm text-foreground leading-relaxed pl-2 border-l-2 border-border">{bet.notes}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ============ PENDING CARD ============
// Action-focused with big Win/Loss buttons
interface PendingCardProps {
  bet: Bet;
  onEdit: (bet: Bet) => void;
  onResultChange: (bet: Bet, result: BetResult, previousResult: BetResult) => void;
  onDelete: (bet: Bet) => void;
}

function PendingCard({ bet, onEdit, onResultChange, onDelete }: PendingCardProps) {

  const headerRight = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => onEdit(bet)}>
          <Pencil className="h-4 w-4 mr-2" />
          Edit
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {/* Change Status Submenu - shows all 5 options, current is disabled + checkmark */}
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <RotateCcw className="h-4 w-4 mr-2" />
            Change Status
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "pending", "pending")}
              disabled={bet.result === "pending"}
              className={cn(bet.result === "pending" && "opacity-50")}
            >
              {bet.result === "pending" ? <Check className="h-4 w-4 mr-2" /> : <Clock className="h-4 w-4 mr-2" />}
              Pending {bet.result === "pending" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "win", "pending")}
              disabled={bet.result === "win"}
              className={cn(bet.result === "win" && "opacity-50")}
            >
              {bet.result === "win" ? <Check className="h-4 w-4 mr-2" /> : <Check className="h-4 w-4 mr-2 text-green-600" />}
              Win {bet.result === "win" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "loss", "pending")}
              disabled={bet.result === "loss"}
              className={cn(bet.result === "loss" && "opacity-50")}
            >
              {bet.result === "loss" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2 text-red-600" />}
              Loss {bet.result === "loss" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "push", "pending")}
              disabled={bet.result === "push"}
              className={cn(bet.result === "push" && "opacity-50")}
            >
              {bet.result === "push" ? <Check className="h-4 w-4 mr-2" /> : <Minus className="h-4 w-4 mr-2" />}
              Push {bet.result === "push" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "void", "pending")}
              disabled={bet.result === "void"}
              className={cn(bet.result === "void" && "opacity-50")}
            >
              {bet.result === "void" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2" />}
              Void {bet.result === "void" && "✓"}
            </DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => onDelete(bet)} className="text-red-600">
          <Trash2 className="h-4 w-4 mr-2" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const handleWin = () => {
    // Haptic feedback on mobile
    if (typeof navigator !== "undefined" && navigator.vibrate) {
      navigator.vibrate(10);
    }
    onResultChange(bet, "win", "pending");
  };

  const handleLoss = () => {
    // Haptic feedback on mobile
    if (typeof navigator !== "undefined" && navigator.vibrate) {
      navigator.vibrate(10);
    }
    onResultChange(bet, "loss", "pending");
  };

  const footer = (
    <div className="flex gap-2 pt-2 border-t border-border mt-1">
      <button
        className="flex-1 h-8 min-h-[44px] flex items-center justify-center gap-1.5 text-sm font-medium rounded-md text-[#4A7C59] border border-[#4A7C59]/30 bg-[#4A7C59]/10 hover:bg-[#4A7C59]/20 active:bg-[#4A7C59]/25 transition-colors"
        onClick={handleWin}
      >
        <Check className="h-4 w-4" />
        Won
      </button>
      <button
        className="flex-1 h-8 min-h-[44px] flex items-center justify-center gap-1.5 text-sm font-medium rounded-md text-[#B85C38] border border-[#B85C38]/30 bg-[#B85C38]/10 hover:bg-[#B85C38]/20 active:bg-[#B85C38]/25 transition-colors"
        onClick={handleLoss}
      >
        <X className="h-4 w-4" />
        Lost
      </button>
    </div>
  );

  return <BetCardBase bet={bet} headerRight={headerRight} footer={footer} mode="pending" />;
}

// ============ HISTORY CARD ============
// Read-only with result badge and menu for corrections
interface HistoryCardProps {
  bet: Bet;
  onEdit: (bet: Bet) => void;
  onResultChange: (bet: Bet, result: BetResult, previousResult: BetResult) => void;
  onDelete: (bet: Bet) => void;
}

function HistoryCard({ bet, onEdit, onResultChange, onDelete }: HistoryCardProps) {
  const config = resultConfig[bet.result];
  
  // Random stamp rotation for realistic hand-stamped look - re-randomizes when result changes
  const [randomRotation, setRandomRotation] = useState(Math.floor(Math.random() * 7) - 3);
  
  // Re-randomize when result changes (like applying a new stamp)
  useEffect(() => {
    setRandomRotation(Math.floor(Math.random() * 7) - 3);
  }, [bet.result]);

  const headerRight = (
    <div className="flex items-center gap-2">
      {/* Result Badge - Ink Stamp Style with random rotation */}
      <div 
        className={cn(config.color, config.stampClass)}
        style={{ transform: `rotate(${randomRotation}deg)` }}
      >
        {config.label}
      </div>
      {/* Actions Menu */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => onEdit(bet)}>
            <Pencil className="h-4 w-4 mr-2" />
            Edit
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          {/* Change Status Submenu - shows all 5 options, current is disabled + checkmark */}
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <RotateCcw className="h-4 w-4 mr-2" />
              Change Status
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "pending", bet.result)}
                disabled={bet.result === "pending"}
                className={cn(bet.result === "pending" && "opacity-50")}
              >
                {bet.result === "pending" ? <Check className="h-4 w-4 mr-2" /> : <Clock className="h-4 w-4 mr-2" />}
                Pending {bet.result === "pending" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "win", bet.result)}
                disabled={bet.result === "win"}
                className={cn(bet.result === "win" && "opacity-50")}
              >
                {bet.result === "win" ? <Check className="h-4 w-4 mr-2" /> : <Check className="h-4 w-4 mr-2 text-green-600" />}
                Win {bet.result === "win" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "loss", bet.result)}
                disabled={bet.result === "loss"}
                className={cn(bet.result === "loss" && "opacity-50")}
              >
                {bet.result === "loss" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2 text-red-600" />}
                Loss {bet.result === "loss" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "push", bet.result)}
                disabled={bet.result === "push"}
                className={cn(bet.result === "push" && "opacity-50")}
              >
                {bet.result === "push" ? <Check className="h-4 w-4 mr-2" /> : <Minus className="h-4 w-4 mr-2" />}
                Push {bet.result === "push" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "void", bet.result)}
                disabled={bet.result === "void"}
                className={cn(bet.result === "void" && "opacity-50")}
              >
                {bet.result === "void" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2" />}
                Void {bet.result === "void" && "✓"}
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => onDelete(bet)} className="text-red-600">
            <Trash2 className="h-4 w-4 mr-2" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  // No action footer for history - just the static result
  const footer = null;

  return <BetCardBase bet={bet} headerRight={headerRight} footer={footer} mode="settled" />;
}

// ============ HISTORY FILTER TYPES ============
type BetTypeFilter = "all" | "cash" | "bonus";

// ============ MAIN BET LIST ============
export function BetList() {
  const { data: bets, isLoading, error } = useBets();
  const { data: balances } = useBalances();
  const updateResult = useUpdateBetResult();
  const deleteBet = useDeleteBet();
  const createBet = useCreateBet();
  const [editingBet, setEditingBet] = useState<Bet | null>(null);
  const [activeTab, setActiveTab] = useState<"pending" | "history">("pending");
  
  // Filter drawer state
  const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);
  const [selectedBook, setSelectedBook] = useState<string>("all");
  const [betTypeFilter, setBetTypeFilter] = useState<BetTypeFilter>("all");
  
  // Count active filters for badge
  const activeFilterCount = [
    selectedBook !== "all",
    betTypeFilter !== "all",
  ].filter(Boolean).length;
  
  // Get unique sportsbooks from bets
  const uniqueBooks = useMemo(() => {
    if (!bets) return [];
    const books = Array.from(new Set(bets.map(b => b.sportsbook)));
    return books.sort();
  }, [bets]);
  
  // Get balance for selected sportsbook
  const selectedBalance = useMemo(() => {
    if (selectedBook === "all" || !balances) return null;
    return balances.find(b => b.sportsbook === selectedBook) || null;
  }, [selectedBook, balances]);
  
  // Clear all filters
  const clearFilters = () => {
    setSelectedBook("all");
    setBetTypeFilter("all");
  };

  // Handle result change with undo toast
  const handleResultChange = (bet: Bet, newResult: BetResult, previousResult: BetResult) => {
    updateResult.mutate(
      { id: bet.id, result: newResult },
      {
        onSuccess: () => {
          const toastMessage =
            newResult === "win"
              ? "Marked as Win"
              : newResult === "loss"
              ? "Marked as Loss"
              : newResult === "push"
              ? "Marked as Push"
              : newResult === "void"
              ? "Marked as Void"
              : "Marked as Pending";

          const toastDescription =
            newResult === "win"
              ? `+${formatCurrency(bet.win_payout - bet.stake)} profit`
              : newResult === "loss"
              ? `-${formatCurrency(bet.stake)}`
              : undefined;

          toast(toastMessage, {
            description: toastDescription,
            duration: 5000,
            action: {
              label: "Undo",
              onClick: () => {
                updateResult.mutate(
                  { id: bet.id, result: previousResult },
                  {
                    onSuccess: () => toast.info("Reverted"),
                    onError: () => toast.error("Failed to undo"),
                  }
                );
              },
            },
          });
        },
        onError: () => {
          toast.error("Failed to update result");
        },
      }
    );
  };

  // Handle delete with undo toast
  const handleDeleteWithUndo = (bet: Bet) => {
    // Store bet data for potential undo
    const betData = {
      sport: bet.sport,
      event: bet.event,
      market: bet.market,
      sportsbook: bet.sportsbook,
      promo_type: bet.promo_type,
      odds_american: bet.odds_american,
      stake: bet.stake,
      boost_percent: bet.boost_percent || undefined,
      winnings_cap: bet.winnings_cap || undefined,
      notes: bet.notes || undefined,
      opposing_odds: bet.opposing_odds || undefined,
      event_date: bet.event_date || undefined,
    };

    deleteBet.mutate(bet.id, {
      onSuccess: () => {
        toast("Bet deleted", {
          description: `${bet.sportsbook} • ${formatCurrency(bet.stake)}`,
          duration: 5000,
          action: {
            label: "Undo",
            onClick: () => {
              createBet.mutate(betData, {
                onSuccess: () => toast.success("Bet restored"),
                onError: () => toast.error("Failed to restore bet"),
              });
            },
          },
        });
      },
      onError: () => {
        toast.error("Failed to delete bet");
      },
    });
  };

  if (isLoading) {
    return (
      <div className="space-y-3">
        {/* Skeleton cards */}
        {[1, 2, 3].map((i) => (
          <Card key={i}>
            <CardHeader className="pb-2 pt-3 px-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-5 w-5 rounded" />
                  <Skeleton className="h-4 w-24" />
                </div>
                <Skeleton className="h-5 w-12" />
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-3 pt-0">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div>
                  <Skeleton className="h-3 w-10 mb-1" />
                  <Skeleton className="h-5 w-14" />
                </div>
                <div>
                  <Skeleton className="h-3 w-8 mb-1" />
                  <Skeleton className="h-5 w-12" />
                </div>
                <div>
                  <Skeleton className="h-3 w-10 mb-1" />
                  <Skeleton className="h-5 w-16" />
                </div>
                <div>
                  <Skeleton className="h-3 w-12 mb-1" />
                  <Skeleton className="h-5 w-14" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-red-600">
          Failed to load bets. Is the backend running?
        </CardContent>
      </Card>
    );
  }

  // Helper to check if bet matches sportsbook filter
  const matchesSportsbook = (bet: Bet) => 
    selectedBook === "all" || bet.sportsbook === selectedBook;
  
  // Helper to check if bet matches type filter
  const matchesBetType = (bet: Bet) => {
    if (betTypeFilter === "all") return true;
    if (betTypeFilter === "bonus") {
      // Bonus bets funded by bonus bet stake
      return bet.promo_type === "bonus_bet";
    }
    // Cash bets: everything except bonus bet stake
    return bet.promo_type !== "bonus_bet";
  };
  
  // Apply book and type filters first, then split by status
  const filteredBets = bets?.filter(bet => matchesSportsbook(bet) && matchesBetType(bet)) || [];
  const pendingBets = filteredBets.filter((bet) => bet.result === "pending");
  const settledBets = filteredBets.filter((bet) => bet.result !== "pending");
  
  // Counts for the current sportsbook selection (before type filter, for accurate numbers)
  const booksWithBetType = bets?.filter(matchesSportsbook) || [];
  const pendingForBook = booksWithBetType.filter(b => b.result === "pending");
  const settledForBook = booksWithBetType.filter(b => b.result !== "pending");

  return (
    <>
      <Card className="overflow-visible">
        <CardHeader className="pb-3">
          {/* Row 1: Title + Filter Button */}
          <div className="flex items-center justify-between -mx-2 -mt-2 mb-3">
            <h2 className="text-lg font-semibold px-2">Tracker</h2>
            
            {/* Filter Button with Badge */}
            <button
              onClick={() => setFilterDrawerOpen(true)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                activeFilterCount > 0
                  ? "bg-foreground text-background"
                  : "bg-muted text-muted-foreground hover:bg-secondary"
              )}
            >
              <SlidersHorizontal className="h-4 w-4" />
              <span className="hidden sm:inline">Filter</span>
              {activeFilterCount > 0 && (
                <span className="ml-0.5 px-1.5 py-0.5 text-xs rounded-full bg-background text-foreground">
                  {activeFilterCount}
                </span>
              )}
            </button>
          </div>
          
          {/* Row 2: Full-width Tabs */}
          <div className="flex gap-1 -mx-2 mb-2">
            <button
              className={cn(
                "folder-tab flex-1 px-4 py-2.5 flex items-center justify-center gap-2",
                activeTab === "pending" ? "folder-tab-active" : "folder-tab-inactive"
              )}
              onClick={() => setActiveTab("pending")}
            >
              <Clock className="h-4 w-4" />
              Pending
              {pendingBets.length > 0 && (
                <span className={cn(
                  "text-xs font-mono font-semibold px-1.5 rounded",
                  activeTab === "pending" 
                    ? "bg-[#C4A35A]/20 text-[#8B7355]" 
                    : "bg-[#C4A35A]/10 text-[#8B7355]/70"
                )}>
                  {pendingBets.length}
                </span>
              )}
            </button>
            <button
              className={cn(
                "folder-tab flex-1 px-4 py-2.5 flex items-center justify-center gap-2",
                activeTab === "history" ? "folder-tab-active" : "folder-tab-inactive"
              )}
              onClick={() => setActiveTab("history")}
            >
              <History className="h-4 w-4" />
              History
              <span className={cn(
                "text-xs font-mono",
                activeTab === "history" ? "text-muted-foreground" : "text-muted-foreground/50"
              )}>
                ({settledBets.length})
              </span>
            </button>
          </div>
          
          {/* Active Filter Summary (shows when filters applied) */}
          {activeFilterCount > 0 && (
            <div className="flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-muted/50 border border-border">
              <div className="flex flex-wrap items-center gap-2 text-sm flex-1">
                {selectedBook !== "all" && (
                  <span className={cn(
                    "px-2 py-0.5 rounded-full text-xs font-medium text-white",
                    sportsbookColors[selectedBook] || "bg-foreground"
                  )}>
                    {selectedBook}
                  </span>
                )}
                {betTypeFilter !== "all" && (
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-muted-foreground/20 text-muted-foreground">
                    {betTypeFilter === "bonus" ? "Bonus Bets" : "Cash Bets"}
                  </span>
                )}
                {selectedBook !== "all" && selectedBalance && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    Balance: <span className="font-mono font-semibold text-foreground">{formatCurrency(selectedBalance.profit + selectedBalance.net_deposits)}</span>
                    {pendingForBook.length > 0 && (
                      <> · Pending: <span className="font-mono font-semibold text-[#C4A35A]">{formatCurrency(pendingForBook.reduce((s, b) => s + b.stake, 0))}</span></>
                    )}
                  </span>
                )}
              </div>
              <button
                onClick={clearFilters}
                className="p-1 rounded hover:bg-muted-foreground/10 text-muted-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}


          {/* Summary stats for pending tab */}
          {activeTab === "pending" && pendingBets.length > 0 && (
            <div className="flex justify-between text-sm text-muted-foreground pt-3">
              <span>
                <span className="font-mono font-medium text-foreground">
                  {formatCurrency(pendingBets.reduce((s, b) => s + b.stake, 0))}
                </span>{" "}
                at risk
              </span>
              <span>
                <span className={cn(
                  "font-mono font-medium",
                  pendingBets.reduce((s, b) => s + b.ev_total, 0) >= 0 
                    ? "text-[#4A7C59]" 
                    : "text-[#B85C38]"
                )}>
                  {pendingBets.reduce((s, b) => s + b.ev_total, 0) >= 0 ? "+" : ""}
                  {formatCurrency(pendingBets.reduce((s, b) => s + b.ev_total, 0))}
                </span>{" "}
                expected
              </span>
            </div>
          )}
        </CardHeader>

        <CardContent className="space-y-3">
          {activeTab === "pending" && (
            <>
              {pendingBets.length === 0 ? (
                <div className="text-center py-10">
                  <Clock className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40" />
                  <p className="text-muted-foreground font-medium">No pending bets</p>
                  <p className="text-sm text-muted-foreground/60 mt-1">Find some +EV lines and get started</p>
                </div>
              ) : (
                pendingBets.map((bet) => (
                  <PendingCard
                    key={bet.id}
                    bet={bet}
                    onEdit={setEditingBet}
                    onResultChange={handleResultChange}
                    onDelete={handleDeleteWithUndo}
                  />
                ))
              )}
            </>
          )}

          {activeTab === "history" && (
            <>
              {settledBets.length === 0 ? (
                <div className="text-center py-10">
                  <History className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40" />
                  <p className="text-muted-foreground font-medium">No history yet</p>
                  <p className="text-sm text-muted-foreground/60 mt-1">Settled bets will appear here</p>
                </div>
              ) : settledBets.length === 0 ? (
                <div className="text-center py-10">
                  <Target className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40" />
                  <p className="text-muted-foreground font-medium">No bets match this filter</p>
                  <p className="text-sm text-muted-foreground/60 mt-1">Try a different filter</p>
                </div>
              ) : (
                settledBets.map((bet) => (
                  <HistoryCard
                    key={bet.id}
                    bet={bet}
                    onEdit={setEditingBet}
                    onResultChange={handleResultChange}
                    onDelete={handleDeleteWithUndo}
                  />
                ))
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Filter Drawer (Bottom Sheet) */}
      <Sheet open={filterDrawerOpen} onOpenChange={setFilterDrawerOpen}>
        <SheetContent side="bottom" className="px-6 pb-8">
          <SheetHeader className="pb-4">
            <div className="flex items-center justify-between">
              <SheetTitle>Filter Bets</SheetTitle>
              {activeFilterCount > 0 && (
                <button
                  onClick={clearFilters}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Clear all
                </button>
              )}
            </div>
          </SheetHeader>
          
          <div className="space-y-4">
            {/* Sportsbook Selector - Horizontal Scroll */}
            <div>
              <span className="text-xs text-muted-foreground font-medium block mb-2">Sportsbook</span>
              <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
                <button
                  onClick={() => setSelectedBook("all")}
                  className={cn(
                    "px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0",
                    selectedBook === "all"
                      ? "bg-foreground text-background shadow-sm"
                      : "bg-muted text-muted-foreground hover:bg-secondary"
                  )}
                >
                  All Books
                </button>
                {uniqueBooks.map((book) => (
                  <button
                    key={book}
                    onClick={() => setSelectedBook(book)}
                    className={cn(
                      "px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0",
                      selectedBook === book
                        ? `${sportsbookColors[book] || "bg-foreground"} text-white shadow-sm`
                        : "bg-muted text-muted-foreground hover:bg-secondary"
                    )}
                  >
                    {book}
                  </button>
                ))}
              </div>
            </div>
            
            {/* Bet Type Selector - Horizontal Scroll */}
            <div>
              <span className="text-xs text-muted-foreground font-medium block mb-2">Bet Type</span>
              <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
                {([
                  { key: "all", label: "All Bets" },
                  { key: "cash", label: "Cash Bets" },
                  { key: "bonus", label: "Bonus Bets" },
                ] as const).map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => setBetTypeFilter(key)}
                    className={cn(
                      "px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0",
                      betTypeFilter === key
                        ? "bg-foreground text-background shadow-sm"
                        : "bg-muted text-muted-foreground hover:bg-secondary"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          
          {/* Apply Button */}
          <div className="pt-6">
            <SheetClose asChild>
              <Button className="w-full" size="lg">
                Apply Filters
              </Button>
            </SheetClose>
          </div>
        </SheetContent>
      </Sheet>

      {/* Edit Modal */}
      <EditBetModal
        bet={editingBet}
        open={editingBet !== null}
        onOpenChange={(open) => {
          if (!open) setEditingBet(null);
        }}
      />
    </>
  );
}
