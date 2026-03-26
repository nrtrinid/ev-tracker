"use client";

import Link from "next/link";
import { useState, useEffect, useMemo } from "react";
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
import { useBets, useUpdateBetResult, useDeleteBet, useCreateBet, useBalances, useParlaySlips } from "@/lib/hooks";
import { Skeleton } from "@/components/ui/skeleton";
import { EditBetModal } from "@/components/EditBetModal";
import type { Bet, BetResult, ParlaySlip, TutorialPracticeBet } from "@/lib/types";
import { PROMO_TYPE_CONFIG } from "@/lib/types";
import { formatCurrency, formatOdds, cn, formatRelativeTime, formatShortDate, formatFullDateTime, americanToDecimal, decimalToAmerican, calculateImpliedProb } from "@/lib/utils";
import {
  SPORTSBOOK_BADGE_COLORS,
  SPORTSBOOK_TEXT_COLORS,
} from "@/lib/sportsbook-config";
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
  ArrowRight,
  SlidersHorizontal,
} from "lucide-react";
import { toast } from "sonner";

const resultConfig: Record<
  BetResult,
  { label: string; color: string; bgColor: string; icon: React.ReactNode; stampClass: string }
> = {
  pending: {
    label: "Pending",
    color: "text-pending",
    bgColor: "bg-pending/10",
    icon: <Clock className="h-3.5 w-3.5" />,
    stampClass: "stamp",
  },
  win: {
    label: "Win",
    color: "text-profit",
    bgColor: "bg-profit/20",
    icon: <Check className="h-3.5 w-3.5" />,
    stampClass: "stamp-win",
  },
  loss: {
    label: "Loss",
    color: "text-loss",
    bgColor: "bg-loss/20",
    icon: <X className="h-3.5 w-3.5" />,
    stampClass: "stamp-loss",
  },
  push: {
    label: "Push",
    color: "text-muted-foreground",
    bgColor: "bg-muted/50",
    icon: <Minus className="h-3.5 w-3.5" />,
    stampClass: "stamp-push",
  },
  void: {
    label: "Void",
    color: "text-muted-foreground",
    bgColor: "bg-muted/50",
    icon: <Minus className="h-3.5 w-3.5" />,
    stampClass: "stamp",
  },
};

// Using shared PROMO_TYPE_CONFIG from types.ts

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

function formatGameStartCompact(isoString: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

// ============ SHARED BET CARD BASE ============
// Compact layout with context-aware data row
interface BetCardBaseProps {
  bet: Bet;
  headerRight: React.ReactNode;
  footer: React.ReactNode;
  mode: "pending" | "settled";
  parlaySlip?: ParlaySlip;
}

function BetCardBase({ bet, headerRight, footer, mode, parlaySlip }: BetCardBaseProps) {
  const [expanded, setExpanded] = useState(false);
  const borderColor = SPORTSBOOK_BADGE_COLORS[bet.sportsbook] || "bg-gray-400";
  const textColor = SPORTSBOOK_TEXT_COLORS[bet.sportsbook] || "text-gray-600";
  const promoConfig = PROMO_TYPE_CONFIG[bet.promo_type] || PROMO_TYPE_CONFIG.standard;
  
  // Short promo label (BB, 30%, etc.)
  const promoLabel = bet.promo_type === "boost_custom" && bet.boost_percent 
    ? `${bet.boost_percent}%`
    : promoConfig.short;
  
  // Only show promo badge if not standard
  const showPromoBadge = bet.promo_type !== "standard";

  // Calculate implied probability
  const impliedProb = calculateImpliedProb(bet.odds_american);
  const hasDistinctLatestRefresh = Boolean(
    bet.latest_pinnacle_updated_at &&
    bet.latest_pinnacle_updated_at !== bet.clv_updated_at
  );
  



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
              {/* CLV badge — raw market CLV for all bets with a Pinnacle snapshot */}
              {bet.clv_ev_percent !== null && (
                <span className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] font-semibold leading-none",
                  bet.beat_close
                    ? "bg-profit/15 text-profit"
                    : "bg-loss/15 text-loss"
                )}>
                  CLV {bet.clv_ev_percent >= 0 ? "+" : ""}{bet.clv_ev_percent.toFixed(1)}%
                </span>
              )}
              {bet.pinnacle_odds_at_entry !== null && bet.clv_ev_percent === null && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium leading-none bg-muted text-muted-foreground">
                  CLV ⏳
                </span>
              )}
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
            <p className={cn("font-mono font-semibold", bet.ev_total >= 0 ? "text-profit" : "text-loss")}
               style={{ whiteSpace: "nowrap" }}>
              {bet.ev_total >= 0 ? "+" : ""}{formatCurrency(bet.ev_total)}{" "}
              <span className="font-normal text-xs opacity-70">
                ({bet.ev_per_dollar >= 0 ? "+" : ""}{(bet.ev_per_dollar * 100).toFixed(1)}%)
              </span>
            </p>
          </div>
          {/* Stake - Col 1 on mobile row 2, Col 2 on desktop */}
          <div className="order-3 md:order-2">
            <p className="text-muted-foreground text-xs">Stake</p>
            <p className="font-mono font-medium">{formatCurrency(bet.stake)}</p>
          </div>
          {/* To Win/Profit - Col 2 on mobile row 2, Col 4 on desktop */}
          <div className="order-4 md:order-4">
            <p className="text-muted-foreground text-xs">{mode === "settled" ? "Profit" : "Return if Win"}</p>
            <p className={cn(
              "font-mono font-semibold",
              mode === "settled"
                ? bet.real_profit !== null && bet.real_profit >= 0 ? "text-profit" : "text-loss"
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
          <div className="pt-3 border-t border-border space-y-4">

            {/* ── Parlay legs (parlay bets only) ── */}
            {bet.surface === "parlay" && parlaySlip && parlaySlip.legs.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-2">
                  Parlay Legs ({parlaySlip.legs.length})
                </p>
                <div className="space-y-1.5">
                  {parlaySlip.legs.map((leg) => (
                    <div
                      key={leg.id}
                      className="flex items-center justify-between rounded-md bg-muted/40 px-2.5 py-2"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium">{leg.display}</p>
                        <p className="truncate text-[11px] text-muted-foreground">
                          {leg.marketDisplay ?? leg.marketKey}
                          {leg.lineValue != null ? ` ${leg.lineValue}` : ""}
                          {leg.selectionSide
                            ? ` · ${leg.selectionSide.charAt(0).toUpperCase() + leg.selectionSide.slice(1)}`
                            : ""}
                        </p>
                      </div>
                      <span className="ml-3 shrink-0 font-mono text-xs font-semibold">
                        {formatOdds(leg.oddsAmerican)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Row 1: CLV (all bets with a Pinnacle entry snapshot) ── */}
            {bet.pinnacle_odds_at_entry != null && (
              <div>
                <div className="grid grid-cols-3 gap-x-3">
                  {/* Col 1: Entry odds — always the raw (unboosted) market line */}
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">Your Odds</p>
                    <p className="font-mono text-sm font-semibold">{formatOdds(bet.odds_american)}</p>
                  </div>
                  {/* Col 2: Pinnacle close */}
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">Closing Odds</p>
                    {bet.pinnacle_odds_at_close != null ? (
                      <p className="font-mono text-sm font-semibold">{formatOdds(bet.pinnacle_odds_at_close)}</p>
                    ) : (
                      <p className="text-xs text-muted-foreground italic">Pending…</p>
                    )}
                  </div>
                  {/* Col 3: CLV result */}
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">CLV</p>
                    {bet.clv_ev_percent != null ? (
                      <p className={cn(
                        "font-mono text-sm font-semibold",
                        bet.beat_close ? "text-profit" : "text-loss"
                      )}>
                        {bet.clv_ev_percent >= 0 ? "+" : ""}{bet.clv_ev_percent.toFixed(2)}%
                      </p>
                    ) : (
                      <p className="text-xs text-muted-foreground italic">—</p>
                    )}
                  </div>
                </div>
                {/* Close-capture vs latest-refresh timestamps */}
                <div className="mt-1.5 space-y-0.5">
                  {bet.clv_updated_at && (
                    <p className="text-[10px] text-muted-foreground/50">
                      Close snapshot {formatRelativeTime(bet.clv_updated_at)}
                    </p>
                  )}
                  {hasDistinctLatestRefresh && bet.latest_pinnacle_updated_at && (
                    <p className="text-[10px] text-muted-foreground/50">
                      Latest Pinnacle refresh {formatRelativeTime(bet.latest_pinnacle_updated_at)}
                    </p>
                  )}
                  {bet.promo_type !== "standard" && (
                    <p className="text-[10px] text-muted-foreground/40 italic">
                      CLV is calculated against the original market line to preserve sharp analytics.
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* ── Row 2: Metadata footer ── */}
            <div className={cn(
              "grid grid-cols-2 md:grid-cols-3 gap-x-3 gap-y-2 pt-3",
              bet.pinnacle_odds_at_entry != null ? "border-t border-border" : ""
            )}>
              <div>
                <p className="text-muted-foreground/60 text-xs mb-0.5">Req. Win %</p>
                <p className="font-mono text-xs text-muted-foreground">{(impliedProb * 100).toFixed(1)}%</p>
              </div>
              {bet.scan_ev_percent_at_log !== null && (
                <div>
                  <p className="text-muted-foreground/60 text-xs mb-0.5">EV at log</p>
                  <p className={cn(
                    "font-mono text-xs font-semibold",
                    bet.scan_ev_percent_at_log >= 0 ? "text-profit" : "text-loss"
                  )}>
                    {bet.scan_ev_percent_at_log >= 0 ? "+" : ""}{bet.scan_ev_percent_at_log.toFixed(1)}%
                  </p>
                </div>
              )}
              <div>
                <p className="text-muted-foreground/60 text-xs mb-0.5">
                  {bet.commence_time ? "Game Start" : "Event Date"}
                </p>
                <p className="font-mono text-xs text-muted-foreground">
                  {bet.commence_time ? formatGameStartCompact(bet.commence_time) : formatShortDate(bet.event_date)}
                </p>
              </div>
              {/* Timestamp spans full width on mobile so it never truncates */}
              <div className="col-span-2 md:col-span-1">
                <p className="text-muted-foreground/60 text-xs mb-0.5">
                  {bet.settled_at ? "Settled" : "Logged"}
                </p>
                <p className="font-mono text-xs text-muted-foreground">
                  {bet.settled_at ? formatFullDateTime(bet.settled_at) : formatFullDateTime(bet.created_at)}
                </p>
              </div>
            </div>

            {/* ── Notes ── */}
            {bet.notes && (
              <div className="pt-3 border-t border-border">
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

function TutorialPracticeCard({ bet }: { bet: TutorialPracticeBet }) {
  return (
    <div className="rounded-xl border border-primary/20 bg-primary/8 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
            Tutorial Practice Ticket
          </p>
          <p className="mt-1 text-sm font-semibold text-foreground">{bet.event}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {bet.sportsbook} / {bet.sport} / {bet.market}
          </p>
        </div>
        <div className="rounded-full border border-primary/20 bg-background/80 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
          Local Only
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">Odds</p>
          <p className="font-mono font-semibold">{formatOdds(bet.odds_american)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Stake</p>
          <p className="font-mono font-semibold">{formatCurrency(bet.stake)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Practice EV</p>
          <p className={cn("font-mono font-semibold", bet.ev_total >= 0 ? "text-profit" : "text-loss")}>
            {bet.ev_total >= 0 ? "+" : ""}
            {formatCurrency(bet.ev_total)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Return if Win</p>
          <p className="font-mono font-semibold">{formatCurrency(bet.win_payout)}</p>
        </div>
      </div>

      <p className="mt-3 text-xs text-muted-foreground">
        This practice ticket is part of the tutorial only. It will disappear when you finish the walkthrough and never touches your real bankroll, stats, or history.
      </p>
    </div>
  );
}

// ============ PENDING CARD ============
// Action-focused with big Win/Loss buttons
interface PendingCardProps {
  bet: Bet;
  parlaySlip?: ParlaySlip;
  onEdit: (bet: Bet) => void;
  onResultChange: (bet: Bet, result: BetResult, previousResult: BetResult) => void;
  onDelete: (bet: Bet) => void;
}

function PendingCard({ bet, parlaySlip, onEdit, onResultChange, onDelete }: PendingCardProps) {

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
            Other Result
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "pending", "pending")}
              disabled={bet.result === "pending"}
              className={cn(bet.result === "pending" && "opacity-50")}
            >
              {bet.result === "pending" ? <Check className="h-4 w-4 mr-2" /> : <Clock className="h-4 w-4 mr-2" />}
              Keep Open {bet.result === "pending" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "win", "pending")}
              disabled={bet.result === "win"}
              className={cn(bet.result === "win" && "opacity-50")}
            >
              {bet.result === "win" ? <Check className="h-4 w-4 mr-2" /> : <Check className="h-4 w-4 mr-2 text-profit" />}
              Mark Win {bet.result === "win" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "loss", "pending")}
              disabled={bet.result === "loss"}
              className={cn(bet.result === "loss" && "opacity-50")}
            >
              {bet.result === "loss" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2 text-loss" />}
              Mark Loss {bet.result === "loss" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "push", "pending")}
              disabled={bet.result === "push"}
              className={cn(bet.result === "push" && "opacity-50")}
            >
              {bet.result === "push" ? <Check className="h-4 w-4 mr-2" /> : <Minus className="h-4 w-4 mr-2" />}
              Mark Push {bet.result === "push" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "void", "pending")}
              disabled={bet.result === "void"}
              className={cn(bet.result === "void" && "opacity-50")}
            >
              {bet.result === "void" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2" />}
              Mark Void {bet.result === "void" && "✓"}
            </DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => onDelete(bet)} className="text-destructive">
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
        className="flex-1 h-8 min-h-[44px] flex items-center justify-center gap-1.5 text-sm font-medium rounded-md text-profit border border-profit/30 bg-profit/10 hover:bg-profit/20 active:bg-profit/25 transition-colors"
        onClick={handleWin}
      >
        <Check className="h-4 w-4" />
        Mark Win
      </button>
      <button
        className="flex-1 h-8 min-h-[44px] flex items-center justify-center gap-1.5 text-sm font-medium rounded-md text-loss border border-loss/30 bg-loss/10 hover:bg-loss/20 active:bg-loss/25 transition-colors"
        onClick={handleLoss}
      >
        <X className="h-4 w-4" />
        Mark Loss
      </button>
    </div>
  );

  return <BetCardBase bet={bet} headerRight={headerRight} footer={footer} mode="pending" parlaySlip={parlaySlip} />;
}

// ============ HISTORY CARD ============
// Read-only with result badge and menu for corrections
interface HistoryCardProps {
  bet: Bet;
  parlaySlip?: ParlaySlip;
  onEdit: (bet: Bet) => void;
  onResultChange: (bet: Bet, result: BetResult, previousResult: BetResult) => void;
  onDelete: (bet: Bet) => void;
}

function HistoryCard({ bet, parlaySlip, onEdit, onResultChange, onDelete }: HistoryCardProps) {
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
              Fix Result
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "pending", bet.result)}
                disabled={bet.result === "pending"}
                className={cn(bet.result === "pending" && "opacity-50")}
              >
                {bet.result === "pending" ? <Check className="h-4 w-4 mr-2" /> : <Clock className="h-4 w-4 mr-2" />}
                Move to Open Bets {bet.result === "pending" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "win", bet.result)}
                disabled={bet.result === "win"}
                className={cn(bet.result === "win" && "opacity-50")}
              >
              {bet.result === "win" ? <Check className="h-4 w-4 mr-2" /> : <Check className="h-4 w-4 mr-2 text-profit" />}
              Change to Win {bet.result === "win" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "loss", bet.result)}
                disabled={bet.result === "loss"}
                className={cn(bet.result === "loss" && "opacity-50")}
              >
              {bet.result === "loss" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2 text-loss" />}
              Change to Loss {bet.result === "loss" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "push", bet.result)}
                disabled={bet.result === "push"}
                className={cn(bet.result === "push" && "opacity-50")}
              >
                {bet.result === "push" ? <Check className="h-4 w-4 mr-2" /> : <Minus className="h-4 w-4 mr-2" />}
                Change to Push {bet.result === "push" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "void", bet.result)}
                disabled={bet.result === "void"}
                className={cn(bet.result === "void" && "opacity-50")}
              >
                {bet.result === "void" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2" />}
                Change to Void {bet.result === "void" && "✓"}
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => onDelete(bet)} className="text-destructive">
          <Trash2 className="h-4 w-4 mr-2" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    </div>
  );

  // No action footer for history - just the static result
  const footer = null;

  return <BetCardBase bet={bet} headerRight={headerRight} footer={footer} mode="settled" parlaySlip={parlaySlip} />;
}

// ============ HISTORY FILTER TYPES ============
type BetTypeFilter = "all" | "cash" | "bonus";

// ============ MAIN BET LIST ============
export function BetList({
  showWorkflowCoach = true,
  tutorialPracticeBet = null,
}: {
  showWorkflowCoach?: boolean;
  tutorialPracticeBet?: TutorialPracticeBet | null;
} = {}) {
  const { data: bets, isLoading, error } = useBets();
  const { data: balances } = useBalances();
  const { data: parlaySlips } = useParlaySlips();
  const updateResult = useUpdateBetResult();
  const deleteBet = useDeleteBet();
  const createBet = useCreateBet();

  // Map logged_bet_id → ParlaySlip for parlay leg lookups
  const slipByBetId = useMemo(() => {
    const map = new Map<string, ParlaySlip>();
    parlaySlips?.forEach((slip) => {
      if (slip.logged_bet_id) map.set(slip.logged_bet_id, slip);
    });
    return map;
  }, [parlaySlips]);
  const [editingBet, setEditingBet] = useState<Bet | null>(null);
  const [activeTab, setActiveTab] = useState<"pending" | "history">("pending");
  
  // Filter drawer state
  const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);
  const [selectedBook, setSelectedBook] = useState<string>("all");
  const [betTypeFilter, setBetTypeFilter] = useState<BetTypeFilter>("all");

  useEffect(() => {
    if (!tutorialPracticeBet) return;
    setActiveTab("pending");
  }, [tutorialPracticeBet]);
  
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
          const winProfit = bet.promo_type === "bonus_bet" ? bet.win_payout : bet.win_payout - bet.stake;
          const toastMessage =
            newResult === "win"
              ? "Marked as Win"
              : newResult === "loss"
              ? "Marked as Loss"
              : newResult === "push"
              ? "Marked as Push"
              : newResult === "void"
              ? "Marked as Void"
              : "Moved to Open Bets";

          const moveDescription =
            previousResult === "pending" && newResult !== "pending"
              ? "Moved to Past Bets."
              : previousResult !== "pending" && newResult === "pending"
              ? "Moved back to Open Bets."
              : previousResult !== "pending" && newResult !== "pending"
              ? "Past Bets updated."
              : undefined;

          const outcomeDescription =
            newResult === "win"
              ? `+${formatCurrency(winProfit)} profit.`
              : newResult === "loss"
              ? bet.promo_type === "bonus_bet"
                ? "Bonus bet settled as a loss."
                : `${formatCurrency(bet.stake)} stake lost.`
              : newResult === "push"
              ? "Stake returned."
              : newResult === "void"
              ? "Bet voided."
              : undefined;

          const toastDescription = [outcomeDescription, moveDescription].filter(Boolean).join(" ");

          toast(toastMessage, {
            description: toastDescription || undefined,
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
      payout_override: bet.payout_override || undefined,
      notes: bet.notes || undefined,
      opposing_odds: bet.opposing_odds || undefined,
      event_date: bet.event_date || undefined,
    };

    deleteBet.mutate(bet.id, {
      onSuccess: () => {
        const returnsCashStake = bet.result === "pending" && bet.promo_type !== "bonus_bet";
        const deleteDescription = returnsCashStake
          ? `${bet.sportsbook} • ${formatCurrency(bet.stake)} returned to bankroll`
          : bet.result === "pending" && bet.promo_type === "bonus_bet"
          ? `${bet.sportsbook} • Bonus bet removed (no cash stake return)`
          : `${bet.sportsbook} • ${formatCurrency(bet.stake)}`;

        toast("Bet deleted", {
          description: deleteDescription,
          duration: 5000,
          action: {
            label: "Undo",
            onClick: () => {
              createBet.mutate(betData, {
                onSuccess: (restoredBet) => {
                  if (bet.result === "pending") {
                    toast.success("Bet restored to Open Bets");
                    return;
                  }

                  updateResult.mutate(
                    { id: restoredBet.id, result: bet.result },
                    {
                      onSuccess: () => {
                        const resultLabel =
                          bet.result === "win"
                            ? "Win"
                            : bet.result === "loss"
                            ? "Loss"
                            : bet.result === "push"
                            ? "Push"
                            : "Void";
                        toast.success(`Bet restored as ${resultLabel}`);
                      },
                      onError: () => {
                        toast.error("Bet restored, but failed to restore result");
                      },
                    }
                  );
                },
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
  const allPendingBets = bets?.filter((bet) => bet.result === "pending") || [];
  const allSettledBets = bets?.filter((bet) => bet.result !== "pending") || [];
  const hasPendingFilterEmpty = activeFilterCount > 0 && pendingBets.length === 0 && allPendingBets.length > 0;
  const hasHistoryFilterEmpty = activeFilterCount > 0 && settledBets.length === 0 && allSettledBets.length > 0;

  // Cash-at-risk exposure should exclude bonus bet stake (not real cash).
  const pendingCashBets = pendingBets.filter((b) => b.promo_type !== "bonus_bet");
  const pendingPotentialReturn = pendingBets.reduce((sum, bet) => sum + bet.win_payout, 0);
  const pendingEvTotal = pendingBets.reduce((sum, bet) => sum + bet.ev_total, 0);
  
  // Counts for the current sportsbook selection (before type filter, for accurate numbers)
  const booksWithBetType = bets?.filter(matchesSportsbook) || [];
  const pendingForBook = booksWithBetType.filter(b => b.result === "pending");

  const pendingCashForBook = pendingForBook.filter((b) => b.promo_type !== "bonus_bet");
  const visiblePendingCount = pendingBets.length + (tutorialPracticeBet ? 1 : 0);

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
              Open Bets
              {visiblePendingCount > 0 && (
                <span className={cn(
                  "text-xs font-mono font-semibold px-1.5 rounded",
                  activeTab === "pending"
                    ? "bg-pending/20 text-pending"
                    : "bg-pending/10 text-pending/70"
                )}>
                  {visiblePendingCount}
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
              Past Bets
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
                    SPORTSBOOK_BADGE_COLORS[selectedBook] || "bg-foreground"
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
                    Balance: <span className="font-mono font-semibold text-foreground">{formatCurrency(selectedBalance.balance)}</span>
                    {pendingCashForBook.length > 0 && (
                      <> · Open: <span className="font-mono font-semibold text-pending">{formatCurrency(pendingCashForBook.reduce((s, b) => s + b.stake, 0))}</span></>
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

          {showWorkflowCoach && (
            <div className="rounded-xl border border-primary/15 bg-primary/5 px-4 py-3">
              {activeTab === "pending" ? (
                <>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
                    {hasPendingFilterEmpty ? "Filtered View" : pendingBets.length > 0 ? "Step 3: Check Results" : "Open Bets"}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-foreground">
                    {hasPendingFilterEmpty
                      ? "Your filters are hiding your open bets"
                      : pendingBets.length > 0
                      ? "Mark finished tickets here"
                      : allSettledBets.length > 0
                      ? "You're caught up for now"
                      : "Your logged bets will land here"}
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {hasPendingFilterEmpty
                      ? "Clear the current filters or switch books if you want to check every open ticket."
                      : pendingBets.length > 0
                      ? "When a game settles at the sportsbook, tap Mark Win or Mark Loss. Use the menu if you need Push or Void."
                      : allSettledBets.length > 0
                      ? "You do not have any open bets right now. Review Past Bets or scan for another play when you're ready."
                      : "After you log a play, it stays in Open Bets until the result is in."}
                  </p>
                  {(hasPendingFilterEmpty || pendingBets.length === 0) && (
                    <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                      {hasPendingFilterEmpty ? (
                        <>
                          <Button className="h-10 sm:flex-1" onClick={clearFilters}>
                            Clear Filters
                          </Button>
                          <Button variant="outline" className="h-10 sm:flex-1" onClick={() => setFilterDrawerOpen(true)}>
                            Adjust Filters
                          </Button>
                        </>
                      ) : allSettledBets.length > 0 ? (
                        <>
                          <Button className="h-10 sm:flex-1" onClick={() => setActiveTab("history")}>
                            View Past Bets
                          </Button>
                          <Button asChild variant="outline" className="h-10 sm:flex-1">
                            <Link href="/">
                              Find a Play
                              <ArrowRight className="ml-2 h-4 w-4" />
                            </Link>
                          </Button>
                        </>
                      ) : (
                        <Button asChild className="h-10 sm:w-auto">
                          <Link href="/">
                            Find a Play
                            <ArrowRight className="ml-2 h-4 w-4" />
                          </Link>
                        </Button>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
                    {hasHistoryFilterEmpty ? "Filtered View" : "Past Bets"}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-foreground">
                    {hasHistoryFilterEmpty
                      ? "Your filters are hiding your past bets"
                      : settledBets.length > 0
                      ? "Review your results here"
                      : allPendingBets.length > 0
                      ? "Nothing has settled yet"
                      : "Past Bets will build over time"}
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {hasHistoryFilterEmpty
                      ? "Try a different book or ticket type if you want to see your full record."
                      : settledBets.length > 0
                      ? "Use Past Bets to review outcomes and spot patterns after your tickets are graded."
                      : allPendingBets.length > 0
                      ? "Your open bets are still waiting on results. Come back here once those games finish."
                      : "Once you settle a logged ticket, it moves here so you can keep a running record."}
                  </p>
                  {(hasHistoryFilterEmpty || settledBets.length === 0 || allPendingBets.length > 0) && (
                    <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                      {hasHistoryFilterEmpty ? (
                        <>
                          <Button className="h-10 sm:flex-1" onClick={clearFilters}>
                            Clear Filters
                          </Button>
                          <Button variant="outline" className="h-10 sm:flex-1" onClick={() => setFilterDrawerOpen(true)}>
                            Adjust Filters
                          </Button>
                        </>
                      ) : allPendingBets.length > 0 ? (
                        <Button className="h-10 sm:w-auto" onClick={() => setActiveTab("pending")}>
                          Back to Open Bets
                        </Button>
                      ) : settledBets.length === 0 ? (
                        <Button asChild className="h-10 sm:w-auto">
                          <Link href="/">
                            Find a Play
                            <ArrowRight className="ml-2 h-4 w-4" />
                          </Link>
                        </Button>
                      ) : null}
                    </div>
                  )}
                </>
              )}
            </div>
          )}


          {/* Summary stats for pending tab */}
          {activeTab === "pending" && pendingBets.length > 0 && (
            <div className="grid grid-cols-3 gap-3 pt-3">
              <div className="rounded-lg bg-muted/50 border border-border px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Cash in Play</p>
                <p className="font-mono font-semibold text-foreground">
                  {formatCurrency(pendingCashBets.reduce((s, b) => s + b.stake, 0))}
                </p>
              </div>
              <div className="rounded-lg bg-muted/50 border border-border px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Expected Edge</p>
                <p
                  className={cn(
                    "font-mono font-semibold",
                    pendingEvTotal >= 0 ? "text-profit" : "text-loss",
                  )}
                >
                  {pendingEvTotal >= 0 ? "+" : ""}
                  {formatCurrency(pendingEvTotal)}
                </p>
              </div>
              <div className="rounded-lg bg-muted/50 border border-border px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Return if Win</p>
                <p className="font-mono font-semibold text-foreground">
                  {formatCurrency(pendingPotentialReturn)}
                </p>
              </div>
            </div>
          )}
        </CardHeader>

        <CardContent className="space-y-3">
          {activeTab === "pending" && (
            <>
              {pendingBets.length > 0 && !hasPendingFilterEmpty && (
                <div className="rounded-lg border border-border bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
                  Settled one? Open the ticket card and use <span className="font-medium text-foreground">Mark Win</span> or <span className="font-medium text-foreground">Mark Loss</span> to keep your record current.
                </div>
              )}
              {tutorialPracticeBet && <TutorialPracticeCard bet={tutorialPracticeBet} />}
              {hasPendingFilterEmpty ? (
                <div className="text-center py-10">
                  <Target className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40" />
                  <p className="text-muted-foreground font-medium">No open bets match this filter</p>
                  <p className="text-sm text-muted-foreground/60 mt-1">Clear filters or switch books to see the rest of your tickets</p>
                </div>
              ) : pendingBets.length === 0 && !tutorialPracticeBet ? (
                <div className="text-center py-10">
                  <Clock className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40" />
                  <p className="text-muted-foreground font-medium">No open bets right now</p>
                  <p className="text-sm text-muted-foreground/60 mt-1">Log a play and it will stay here until the result is in</p>
                </div>
              ) : (
                pendingBets.map((bet) => (
                  <PendingCard
                    key={bet.id}
                    bet={bet}
                    parlaySlip={slipByBetId.get(bet.id)}
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
              {hasHistoryFilterEmpty ? (
                <div className="text-center py-10">
                  <Target className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40" />
                  <p className="text-muted-foreground font-medium">No past bets match this filter</p>
                  <p className="text-sm text-muted-foreground/60 mt-1">Clear filters or adjust them to see more of your record</p>
                </div>
              ) : settledBets.length === 0 ? (
                <div className="text-center py-10">
                  <History className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40" />
                  <p className="text-muted-foreground font-medium">No past bets yet</p>
                  <p className="text-sm text-muted-foreground/60 mt-1">Settled tickets will appear here after you mark a result</p>
                </div>
              ) : (
                settledBets.map((bet) => (
                  <HistoryCard
                    key={bet.id}
                    bet={bet}
                    parlaySlip={slipByBetId.get(bet.id)}
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
              <SheetTitle>Refine Tracker</SheetTitle>
              {activeFilterCount > 0 && (
                <button
                  onClick={clearFilters}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Clear all
                </button>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              Focus on one sportsbook or ticket type if you are checking a specific set of bets.
            </p>
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
                        ? `${SPORTSBOOK_BADGE_COLORS[book] || "bg-foreground"} text-white shadow-sm`
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
