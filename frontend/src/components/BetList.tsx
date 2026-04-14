"use client";

import Link from "next/link";
import { useState, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
import {
  FilterChip,
  SingleSelectFilterPills,
} from "@/components/shared/FilterControls";
import { FolderTabs } from "@/components/shared/FolderTabs";
import type { Bet, BetResult, TutorialPracticeBet } from "@/lib/types";
import { PROMO_TYPE_CONFIG } from "@/lib/types";
import { getTrackerSourceLabel } from "@/lib/tracker-source";
import {
  buildTrackerViewQuery,
  DEFAULT_TRACKER_VIEW_STATE,
  matchesTrackerFilters,
  parseTrackerSourceFilter,
  parseTrackerTab,
} from "@/lib/tracker-view";
import { parseParlayLegsFromBet } from "@/lib/parlay-bet-meta";
import { buildTrackedBetCardTitle } from "@/lib/straight-bet-labels";
import { getTrackerSettlementState } from "@/lib/tracker-settlement-state";
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
  Search,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

const resultConfig: Record<
  BetResult,
  { label: string; color: string; bgColor: string; icon: React.ReactNode; stampClass: string }
> = {
  pending: {
    label: "Pending",
    color: "text-color-pending-fg",
    bgColor: "bg-color-pending-subtle",
    icon: <Clock className="h-3.5 w-3.5" />,
    stampClass: "stamp",
  },
  win: {
    label: "Win",
    color: "text-color-profit-fg",
    bgColor: "bg-color-profit-subtle",
    icon: <Check className="h-3.5 w-3.5" />,
    stampClass: "stamp-win",
  },
  loss: {
    label: "Loss",
    color: "text-color-loss-fg",
    bgColor: "bg-color-loss-subtle",
    icon: <X className="h-3.5 w-3.5" />,
    stampClass: "stamp-loss",
  },
  push: {
    label: "Push",
    color: "text-color-neutral-fg",
    bgColor: "bg-color-neutral-subtle",
    icon: <Minus className="h-3.5 w-3.5" />,
    stampClass: "stamp-push",
  },
  void: {
    label: "Void",
    color: "text-color-neutral-fg",
    bgColor: "bg-color-neutral-subtle",
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

function parseValidDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatTimeOnly(date: Date): string {
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function resolveBetGameTime(bet: Bet, parlayLegs: ReturnType<typeof parseParlayLegsFromBet>): Date | null {
  const commence = parseValidDate(bet.commence_time);
  if (commence) return commence;

  if (parlayLegs && parlayLegs.length > 0) {
    let latestLegStart: Date | null = null;
    for (const leg of parlayLegs) {
      const legStart = parseValidDate(leg.commenceTime);
      if (!legStart) continue;
      if (!latestLegStart || legStart > latestLegStart) {
        latestLegStart = legStart;
      }
    }
    if (latestLegStart) return latestLegStart;
  }

  return parseValidDate(bet.event_date);
}

function formatOpenBetEventTimeCompact(isoString: string): string {
  const date = parseValidDate(isoString);
  if (!date) return "";

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfTarget = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDiff = Math.floor((startOfTarget.getTime() - startOfToday.getTime()) / (1000 * 60 * 60 * 24));

  if (dayDiff === 0) {
    return `Today · ${formatTimeOnly(date)}`;
  }

  if (dayDiff > 0 && dayDiff < 7) {
    const weekday = date.toLocaleDateString("en-US", { weekday: "short" });
    return `${weekday} · ${formatTimeOnly(date)}`;
  }

  const monthDay = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${monthDay} · ${formatTimeOnly(date)}`;
}

function formatGameTimeDetail(isoString: string): string {
  const date = parseValidDate(isoString);
  if (!date) return "";
  const weekday = date.toLocaleDateString("en-US", { weekday: "short" });
  const monthDay = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${weekday}, ${monthDay} · ${formatTimeOnly(date)}`;
}

function formatParlayLegSportLabel(sport: string): string {
  const normalized = sport.trim();
  if (!normalized) {
    return "";
  }

  const key = normalized.toLowerCase();
  const sportLabel = key.split("_").pop();
  if (sportLabel && sportLabel !== key) {
    return sportLabel.toUpperCase();
  }

  return normalized;
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
  const borderColor = SPORTSBOOK_BADGE_COLORS[bet.sportsbook] || "bg-gray-400";
  const textColor = SPORTSBOOK_TEXT_COLORS[bet.sportsbook] || "text-gray-600";
  const promoConfig = PROMO_TYPE_CONFIG[bet.promo_type] || PROMO_TYPE_CONFIG.standard;
  const parlayLegs = parseParlayLegsFromBet(bet);
  const displayTitle = buildTrackedBetCardTitle(bet);
  
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
  const resolvedGameTime = resolveBetGameTime(bet, parlayLegs);
  const openBetEventTime =
    mode === "pending" && resolvedGameTime
      ? formatOpenBetEventTimeCompact(resolvedGameTime.toISOString())
      : "";
  



  return (
    <div className="border border-border/80 rounded-lg overflow-hidden flex card-hover bg-card transition-all duration-200 hover:shadow-soft">
      {/* Colored left border for sportsbook branding */}
      <div className={cn("w-1 shrink-0 transition-all duration-200", borderColor)} />
      
      <div className="flex-1 p-4 space-y-3">
        {/* Header: Event name as title + actions */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            {/* Primary: Event name */}
            <p className="font-bold text-sm leading-tight text-foreground">{displayTitle}</p>
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
              <span className="text-xs text-muted-foreground">
                {bet.sport} • {bet.market}
                {openBetEventTime ? ` • ${openBetEventTime}` : ""}
              </span>
              {/* CLV badge — raw market CLV for all bets with a Pinnacle snapshot */}
              {bet.clv_ev_percent !== null && (
                <span className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] font-semibold leading-none",
                  bet.beat_close
                    ? "bg-color-profit-subtle text-color-profit-fg"
                    : "bg-color-loss-subtle text-color-loss-fg"
                )}>
                  CLV {bet.clv_ev_percent >= 0 ? "+" : ""}{bet.clv_ev_percent.toFixed(1)}%
                </span>
              )}
              {bet.pinnacle_odds_at_entry !== null && bet.clv_ev_percent === null && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium leading-none bg-muted text-muted-foreground">
                  CLV pending
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
                  <div className="font-mono font-bold flex flex-row items-baseline">
                    <span className="line-through text-muted-foreground/60 mr-1.5">
                      {formatOdds(bet.odds_american)}
                    </span>
                    <span className="text-foreground">{formatOdds(boostedOdds)}</span>
                  </div>
                );
              }
              return <p className="font-mono font-bold">{formatOdds(bet.odds_american)}</p>;
            })()}
          </div>
          {/* EV - Col 2 on mobile, Col 3 on desktop */}
          <div className="order-2 md:order-3">
            <p className="text-muted-foreground text-xs">EV</p>
            <p className={cn("font-mono font-bold", bet.ev_total >= 0 ? "text-color-profit-fg" : "text-color-loss-fg")}
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
            <p className="font-mono font-bold text-foreground">{formatCurrency(bet.stake)}</p>
          </div>
          {/* To Win/Profit - Col 2 on mobile row 2, Col 4 on desktop */}
          <div className="order-4 md:order-4">
            <p className="text-muted-foreground text-xs">{mode === "settled" ? "Profit" : "Return if Win"}</p>
            <p className={cn(
              "font-mono font-bold",
              mode === "settled"
                ? bet.real_profit !== null && bet.real_profit >= 0 ? "text-color-profit-fg" : "text-color-loss-fg"
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
          className="w-full text-xs text-muted-foreground border border-border/50 hover:border-border hover:bg-muted/40 active:scale-[0.98] transition-all duration-150"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Hide details" : "View details"}
          {expanded ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
        </Button>

        {expanded && (
          <div className="pt-3 border-t border-border space-y-4 animate-fade-in">

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
                        bet.beat_close ? "text-color-profit-fg" : "text-color-loss-fg"
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

            {/* ── Row 2: Parlay leg-level CLV (when available) ── */}
            {parlayLegs && (
              <div
                className={cn(
                  "space-y-1.5",
                  bet.pinnacle_odds_at_entry != null ? "pt-3 border-t border-border" : ""
                )}
              >
                <p className="text-muted-foreground text-[11px] font-medium">Parlay Legs ({parlayLegs.length})</p>
                <div className="space-y-1.5">
                  {parlayLegs.map((leg, index) => {
                    const legCloseOdds =
                      typeof leg.pinnacle_odds_at_close === "number" ? leg.pinnacle_odds_at_close : null;
                    const legLatestOdds =
                      typeof leg.latest_reference_odds === "number" ? leg.latest_reference_odds : null;
                    const legClvPercent =
                      typeof leg.clv_ev_percent === "number" ? leg.clv_ev_percent : null;
                    const hasLegClose = legCloseOdds !== null;
                    const hasLegLatest = legLatestOdds !== null;
                    const hasLegClv = legClvPercent !== null;
                    return (
                      <div
                        key={leg.id || `leg-${index}`}
                        className="rounded-md border border-border/70 bg-muted/20 px-3 py-1.5 space-y-1"
                      >
                        <p className="text-xs font-medium text-foreground">{leg.display}</p>
                        <p className="text-[10px] leading-snug text-muted-foreground">{formatParlayLegSportLabel(leg.sport)} {leg.event ? `• ${leg.event}` : ""}</p>
                        <div className="grid grid-cols-3 gap-x-3 gap-y-1 pt-0.5">
                          <div>
                            <p className="text-muted-foreground text-[11px] mb-0">Your Odds</p>
                            <p className="font-mono text-xs font-semibold">{formatOdds(leg.oddsAmerican)}</p>
                          </div>
                          <div>
                            <p className="text-muted-foreground text-[11px] mb-0">Closing Odds</p>
                            {hasLegClose ? (
                              <p className="font-mono text-xs font-semibold">{formatOdds(legCloseOdds)}</p>
                            ) : hasLegLatest ? (
                              <p className="font-mono text-xs text-muted-foreground">
                                {formatOdds(legLatestOdds)} latest
                              </p>
                            ) : (
                              <p className="text-[11px] text-muted-foreground italic">Pending…</p>
                            )}
                          </div>
                          <div className="flex flex-col items-start">
                            <p className="text-muted-foreground text-[11px] mb-0">CLV</p>
                            {hasLegClv ? (
                              <span
                                className={cn(
                                  "inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold leading-none font-mono self-start",
                                  leg.beat_close
                                    ? "bg-color-profit-subtle text-color-profit-fg"
                                    : "bg-color-loss-subtle text-color-loss-fg"
                                )}
                              >
                                CLV&nbsp;
                                {legClvPercent >= 0 ? "+" : ""}
                                {legClvPercent.toFixed(2)}%
                              </span>
                            ) : (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium leading-none bg-muted text-muted-foreground">
                                CLV pending
                              </span>
                            )}
                          </div>
                        </div>
                        {leg.reference_updated_at && (
                          <p className="text-[10px] text-muted-foreground/50">
                            Close snapshot {formatRelativeTime(leg.reference_updated_at)}
                          </p>
                        )}
                        {!leg.reference_updated_at && leg.latest_reference_updated_at && (
                          <p className="text-[10px] text-muted-foreground/50">
                            Latest reference {formatRelativeTime(leg.latest_reference_updated_at)}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── Row 3: Metadata footer ── */}
            <div className={cn(
              "grid grid-cols-2 md:grid-cols-3 gap-x-3 gap-y-2 pt-3",
              bet.pinnacle_odds_at_entry != null || parlayLegs ? "border-t border-border" : ""
            )}>
              <div>
                <p className="text-muted-foreground text-xs mb-0.5">Req. Win %</p>
                <p className="font-mono text-xs text-foreground/70">{(impliedProb * 100).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-muted-foreground text-xs mb-0.5">
                  {mode === "pending" ? "Game time" : bet.commence_time ? "Game Start" : "Event Date"}
                </p>
                <p className="font-mono text-xs text-foreground/70">
                  {mode === "pending"
                    ? resolvedGameTime
                      ? formatGameTimeDetail(resolvedGameTime.toISOString())
                      : formatShortDate(bet.event_date)
                    : bet.commence_time
                      ? formatGameStartCompact(bet.commence_time)
                      : formatShortDate(bet.event_date)}
                </p>
              </div>
              {/* Timestamp spans full width on mobile so it never truncates */}
              <div className="col-span-2 md:col-span-1">
                <p className="text-muted-foreground text-xs mb-0.5">
                  {bet.settled_at ? "Settled" : "Logged"}
                </p>
                <p className="font-mono text-xs text-foreground/70">
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

function TutorialPracticeCard({
  bet,
}: {
  bet: TutorialPracticeBet;
}) {
  return (
    <div className="rounded-xl border border-primary/20 bg-primary/8 p-4 animate-slide-up" style={{ animationFillMode: "both" }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary animate-fade-in" style={{ animationDelay: "100ms", animationFillMode: "both" }}>
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
          <p className={cn("font-mono font-semibold", bet.ev_total >= 0 ? "text-color-profit-fg" : "text-color-loss-fg")}>
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
        Tutorial-only ticket. It stays local, does not touch real bankroll/stats/history, and is used for onboarding practice only.
      </p>
    </div>
  );
}

// ============ PENDING CARD ============
// Pending tickets favor status clarity first, then manual grading when needed.
interface PendingCardProps {
  bet: Bet;
  onEdit: (bet: Bet) => void;
  onResultChange: (bet: Bet, result: BetResult, previousResult: BetResult) => void;
  onDelete: (bet: Bet) => void;
}

function PendingCard({ bet, onEdit, onResultChange, onDelete }: PendingCardProps) {
  const settlementState = getTrackerSettlementState(bet);
  const [manualControlsOpen, setManualControlsOpen] = useState(
    settlementState.showManualControlsByDefault,
  );

  useEffect(() => {
    setManualControlsOpen(settlementState.showManualControlsByDefault);
  }, [settlementState.kind, settlementState.showManualControlsByDefault]);

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
              {bet.result === "win" ? <Check className="h-4 w-4 mr-2" /> : <Check className="h-4 w-4 mr-2 text-color-profit-fg" />}
              Mark Win {bet.result === "win" && "✓"}
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onResultChange(bet, "loss", "pending")}
              disabled={bet.result === "loss"}
              className={cn(bet.result === "loss" && "opacity-50")}
            >
              {bet.result === "loss" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2 text-color-loss-fg" />}
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

  const statusBadgeClass =
    settlementState.kind === "manual_only" || settlementState.kind === "needs_grading"
      ? "bg-color-loss-subtle text-color-loss-fg"
      : "bg-color-pending-subtle text-color-pending-fg";

  const footer = (
    <div className="pt-2 border-t border-border mt-1 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {settlementState.showStatusBadge && (
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]",
                  statusBadgeClass,
                )}
              >
                {settlementState.badgeLabel}
              </span>
            </div>
          )}
          {settlementState.showStatusBadge ? (
            <>
              <p className="mt-2 text-sm text-muted-foreground">{settlementState.title}</p>
              <p className="mt-0.5 text-xs leading-5 text-muted-foreground/70">
                {settlementState.description}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{settlementState.description}</p>
          )}
        </div>
        {!settlementState.showManualControlsByDefault && (
          <button
            type="button"
            className="shrink-0 text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2 decoration-muted-foreground/40 hover:decoration-foreground/40"
            onClick={() => setManualControlsOpen((open) => !open)}
          >
            {manualControlsOpen ? "Hide" : "Settle manually"}
          </button>
        )}
      </div>
      {manualControlsOpen && (
        <div className="flex gap-2">
          <button
            className="flex-1 h-8 min-h-[44px] flex items-center justify-center gap-1.5 text-sm font-medium rounded-md text-color-profit-fg border border-color-profit/30 bg-color-profit-subtle hover:bg-color-profit/20 active:scale-[0.98] transition-all duration-150"
            onClick={handleWin}
          >
            <Check className="h-4 w-4" />
            Mark Win
          </button>
          <button
            className="flex-1 h-8 min-h-[44px] flex items-center justify-center gap-1.5 text-sm font-medium rounded-md text-color-loss-fg border border-color-loss/30 bg-color-loss-subtle hover:bg-color-loss/20 active:scale-[0.98] transition-all duration-150"
            onClick={handleLoss}
          >
            <X className="h-4 w-4" />
            Mark Loss
          </button>
        </div>
      )}
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
  const [shouldAnimate, setShouldAnimate] = useState(false);
  
  // Re-randomize and trigger animation when result changes (like applying a new stamp)
  useEffect(() => {
    setRandomRotation(Math.floor(Math.random() * 7) - 3);
    setShouldAnimate(true);
    const timer = setTimeout(() => setShouldAnimate(false), 400);
    return () => clearTimeout(timer);
  }, [bet.result]);

  const headerRight = (
    <div className="flex items-center gap-2">
      {/* Result Badge - Ink Stamp Style with random rotation and thunk animation */}
      <div 
        className={cn(
          config.color, 
          config.stampClass,
          shouldAnimate && "animate-stamp-thunk"
        )}
        style={{ 
          transform: `rotate(${randomRotation}deg)`,
          '--stamp-rotate': `${randomRotation}deg`
        } as React.CSSProperties}
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
                {bet.result === "win" ? <Check className="h-4 w-4 mr-2" /> : <Check className="h-4 w-4 mr-2 text-color-profit-fg" />}
                Change to Win {bet.result === "win" && "✓"}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => onResultChange(bet, "loss", bet.result)}
                disabled={bet.result === "loss"}
                className={cn(bet.result === "loss" && "opacity-50")}
              >
                {bet.result === "loss" ? <Check className="h-4 w-4 mr-2" /> : <X className="h-4 w-4 mr-2 text-color-loss-fg" />}
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

  return <BetCardBase bet={bet} headerRight={headerRight} footer={footer} mode="settled" />;
}

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
  const updateResult = useUpdateBetResult();
  const deleteBet = useDeleteBet();
  const createBet = useCreateBet();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [editingBet, setEditingBet] = useState<Bet | null>(null);
  const activeTab = parseTrackerTab(searchParams.get("tab"));
  const selectedBook = searchParams.get("sportsbook") ?? DEFAULT_TRACKER_VIEW_STATE.sportsbook;
  const sourceFilter = parseTrackerSourceFilter(searchParams.get("source"));
  const searchQuery = searchParams.get("search") ?? DEFAULT_TRACKER_VIEW_STATE.search;
  
  // Local search input state for debouncing
  const [searchInput, setSearchInput] = useState(searchQuery);

  const updateTrackerView = (updates: Partial<{
    tab: "pending" | "history";
    source: "all" | "core" | "promos";
    sportsbook: string;
    search: string;
  }>) => {
    const query = buildTrackerViewQuery({
      tab: updates.tab ?? activeTab,
      source: updates.source ?? sourceFilter,
      sportsbook: updates.sportsbook ?? selectedBook,
      search: updates.search ?? searchQuery,
    });
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  
  // Filter drawer state
  const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);
  
  // Debounce search input - 400ms delay
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== searchQuery) {
        updateTrackerView({ search: searchInput });
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [searchInput]); // eslint-disable-line react-hooks/exhaustive-deps
  
  // Sync search input when URL changes externally
  useEffect(() => {
    setSearchInput(searchQuery);
  }, [searchQuery]);

  useEffect(() => {
    if (!tutorialPracticeBet || activeTab === "pending") return;
    const query = buildTrackerViewQuery({
      tab: "pending",
      source: sourceFilter,
      sportsbook: selectedBook,
      search: searchQuery,
    });
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [tutorialPracticeBet, activeTab, pathname, router, searchQuery, selectedBook, sourceFilter]);
  
  // Count active filters for badge
  const activeFilterCount = [
    selectedBook !== "all",
    sourceFilter !== "all",
    searchQuery.trim() !== "",
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
    setSearchInput("");
    updateTrackerView({ sportsbook: "all", source: "all", search: "" });
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
        <CardContent className="py-8 text-center text-destructive">
          Failed to load bets. Is the backend running?
        </CardContent>
      </Card>
    );
  }

  // Apply source + book filters first, then split by status
  const filteredBets = bets?.filter((bet) => matchesTrackerFilters(bet, {
    source: sourceFilter,
    sportsbook: selectedBook,
    search: searchQuery,
  })) || [];
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
  const settledCashBets = settledBets.filter((b) => b.promo_type !== "bonus_bet");
  const settledStakedTotal = settledCashBets.reduce((sum, bet) => sum + bet.stake, 0);
  const settledEvTotal = settledBets.reduce((sum, bet) => sum + bet.ev_total, 0);
  const settledProfitTotal = settledBets.reduce((sum, bet) => sum + (bet.real_profit ?? 0), 0);
  
  // Counts for the current sportsbook selection (before source filter, for accurate book numbers)
  const betsForSelectedBook = bets?.filter((bet) => selectedBook === "all" || bet.sportsbook === selectedBook) || [];
  const pendingForBook = betsForSelectedBook.filter((b) => b.result === "pending");

  const pendingCashForBook = pendingForBook.filter((b) => b.promo_type !== "bonus_bet");
  const visiblePendingCount = pendingBets.length + (tutorialPracticeBet ? 1 : 0);

  return (
    <>
      <Card className="overflow-visible bg-background border-border/60">
        <CardHeader className="pb-3">
          {/* Row 1: Title */}
          <div className="-mx-2 -mt-2 mb-3">
            <h2 className="text-lg font-bold px-2">Tracker</h2>
          </div>
          
          {/* Row 2: Full-width Tabs */}
          <FolderTabs
            className="-mx-2 mb-2"
            triggerClassName="px-4 py-2.5"
            value={activeTab}
            onValueChange={(tab) => updateTrackerView({ tab })}
            items={[
              {
                value: "pending",
                content: (
                  <>
                    <Clock className="h-4 w-4" />
                    Open Bets
                    {visiblePendingCount > 0 && (
                      <span className={cn(
                        "text-xs font-mono font-semibold px-1.5 rounded",
                        activeTab === "pending"
                          ? "bg-color-pending-subtle text-color-pending-fg"
                          : "bg-color-pending-subtle/60 text-color-pending-fg/60"
                      )}>
                        {visiblePendingCount}
                      </span>
                    )}
                  </>
                ),
              },
              {
                value: "history",
                content: (
                  <>
                    <History className="h-4 w-4" />
                    Past Bets
                    <span className={cn(
                      "text-xs font-mono",
                      activeTab === "history" ? "text-muted-foreground" : "text-muted-foreground/50"
                    )}>
                      ({settledBets.length})
                    </span>
                  </>
                ),
              },
            ]}
          />
          
          {/* Search Bar */}
          <div className="relative mb-2">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
            <Input
              type="text"
              placeholder="Search bets by event, sport, or sportsbook..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="pl-9 h-9 bg-muted/30 border-border/60 focus:bg-background transition-colors"
            />
            {searchInput && (
              <button
                onClick={() => setSearchInput("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-muted-foreground/10 text-muted-foreground transition-colors"
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          
          {/* Active Filter Summary (shows when filters applied) */}
          {activeFilterCount > 0 && (
            <div className="flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-muted/50 border border-border">
              <div className="flex flex-wrap items-center gap-2 text-sm flex-1">
                {selectedBook !== "all" && (
                  <FilterChip
                    className={cn(
                      "rounded-full border-transparent px-2 py-0.5 text-xs font-medium text-white",
                      SPORTSBOOK_BADGE_COLORS[selectedBook] || "bg-foreground",
                    )}
                  >
                    {selectedBook}
                  </FilterChip>
                )}
                {sourceFilter !== "all" && (
                  <FilterChip className="rounded-full border-transparent px-2 py-0.5 text-xs font-medium bg-muted-foreground/20 text-muted-foreground">
                    {getTrackerSourceLabel(sourceFilter)}
                  </FilterChip>
                )}
                {searchQuery.trim() && (
                  <FilterChip className="rounded-full border-transparent px-2 py-0.5 text-xs font-medium bg-primary/15 text-primary flex items-center gap-1">
                    <Search className="h-3 w-3" />
                    &quot;{searchQuery.trim()}&quot;
                  </FilterChip>
                )}
                {selectedBook !== "all" && selectedBalance && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    Balance: <span className="font-mono font-semibold text-foreground">{formatCurrency(selectedBalance.balance)}</span>
                    {pendingCashForBook.length > 0 && (
                      <> · Open: <span className="font-mono font-semibold text-color-pending-fg">{formatCurrency(pendingCashForBook.reduce((s, b) => s + b.stake, 0))}</span></>
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
                    {hasPendingFilterEmpty ? "Filtered View" : "Open Bets"}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-foreground">
                    {hasPendingFilterEmpty
                      ? "Your filters are hiding your open bets"
                      : pendingBets.length > 0
                      ? "Track pending tickets here"
                      : allSettledBets.length > 0
                      ? "You're caught up for now"
                      : "Your logged bets will land here"}
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {hasPendingFilterEmpty
                      ? "Clear the current filters or switch books if you want to check every open ticket."
                      : pendingBets.length > 0
                      ? "Most eligible tickets settle automatically after games finish. Manual-only bets and anything the auto-settler misses can still be graded here."
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
                          <Button className="h-10 sm:flex-1" onClick={() => updateTrackerView({ tab: "history" })}>
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
                      ? "Try a different book or source if you want to see your full record."
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
                        <Button className="h-10 sm:w-auto" onClick={() => updateTrackerView({ tab: "pending" })}>
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
              <div className="rounded-lg bg-card border border-border/70 px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Cash in Play</p>
                <p className="font-mono font-bold text-foreground">
                  {formatCurrency(pendingCashBets.reduce((s, b) => s + b.stake, 0))}
                </p>
              </div>
              <div className="rounded-lg bg-card border border-border/70 px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Expected Edge</p>
                <p
                  className={cn(
                    "font-mono font-bold",
                    pendingEvTotal >= 0 ? "text-color-profit-fg" : "text-color-loss-fg",
                  )}
                >
                  {pendingEvTotal >= 0 ? "+" : ""}
                  {formatCurrency(pendingEvTotal)}
                </p>
              </div>
              <div className="rounded-lg bg-card border border-border/70 px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Return if Win</p>
                <p className="font-mono font-bold text-foreground">
                  {formatCurrency(pendingPotentialReturn)}
                </p>
              </div>
            </div>
          )}

          {/* Summary stats for history tab */}
          {activeTab === "history" && settledBets.length > 0 && (
            <div className="grid grid-cols-3 gap-3 pt-3">
              <div className="rounded-lg bg-card border border-border/70 px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Staked</p>
                <p className="font-mono font-bold text-foreground">
                  {formatCurrency(settledStakedTotal)}
                </p>
              </div>
              <div className="rounded-lg bg-card border border-border/70 px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">EV</p>
                <p
                  className={cn(
                    "font-mono font-bold",
                    settledEvTotal >= 0 ? "text-color-profit-fg" : "text-color-loss-fg",
                  )}
                >
                  {settledEvTotal >= 0 ? "+" : ""}
                  {formatCurrency(settledEvTotal)}
                </p>
              </div>
              <div className="rounded-lg bg-card border border-border/70 px-3 py-2 text-center">
                <p className="text-xs text-muted-foreground">Profit</p>
                <p
                  className={cn(
                    "font-mono font-bold",
                    settledProfitTotal >= 0 ? "text-color-profit-fg" : "text-color-loss-fg",
                  )}
                >
                  {settledProfitTotal >= 0 ? "+" : ""}
                  {formatCurrency(settledProfitTotal)}
                </p>
              </div>
            </div>
          )}

        </CardHeader>

        <CardContent className="space-y-3">
          {activeTab === "pending" && (
            <>
              <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                Eligible bets settle automatically during scheduled runs. Manual grading is available if needed.
              </div>
              {tutorialPracticeBet && (
                <div className="animate-slide-up" style={{ animationFillMode: "both" }}>
                  <TutorialPracticeCard bet={tutorialPracticeBet} />
                </div>
              )}
              {hasPendingFilterEmpty ? (
                <div className="text-center py-10 animate-fade-in">
                  <Target className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40 animate-fade-in" style={{ animationDelay: "100ms", animationFillMode: "both" }} />
                  <p className="text-muted-foreground font-medium animate-fade-in" style={{ animationDelay: "150ms", animationFillMode: "both" }}>No open bets match this filter</p>
                  <p className="text-sm text-muted-foreground/60 mt-1 animate-fade-in" style={{ animationDelay: "200ms", animationFillMode: "both" }}>Clear filters or switch books to see the rest of your tickets</p>
                </div>
              ) : pendingBets.length === 0 && !tutorialPracticeBet ? (
                <div className="text-center py-10 animate-fade-in">
                  <Clock className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40 animate-fade-in" style={{ animationDelay: "100ms", animationFillMode: "both" }} />
                  <p className="text-muted-foreground font-medium animate-fade-in" style={{ animationDelay: "150ms", animationFillMode: "both" }}>No open bets right now</p>
                  <p className="text-sm text-muted-foreground/60 mt-1 animate-fade-in" style={{ animationDelay: "200ms", animationFillMode: "both" }}>Log a play and it will stay here until the result is in</p>
                </div>
              ) : (
                pendingBets.map((bet, index) => (
                  <div
                    key={bet.id}
                    className="animate-slide-up"
                    style={{ animationDelay: `${index * 40}ms`, animationFillMode: "both" }}
                  >
                    <PendingCard
                      bet={bet}
                      onEdit={setEditingBet}
                      onResultChange={handleResultChange}
                      onDelete={handleDeleteWithUndo}
                    />
                  </div>
                ))
              )}
            </>
          )}

          {activeTab === "history" && (
            <>
              {hasHistoryFilterEmpty ? (
                <div className="text-center py-10 animate-fade-in">
                  <Target className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40 animate-fade-in" style={{ animationDelay: "100ms", animationFillMode: "both" }} />
                  <p className="text-muted-foreground font-medium animate-fade-in" style={{ animationDelay: "150ms", animationFillMode: "both" }}>No past bets match this filter</p>
                  <p className="text-sm text-muted-foreground/60 mt-1 animate-fade-in" style={{ animationDelay: "200ms", animationFillMode: "both" }}>Clear filters or adjust them to see more of your record</p>
                </div>
              ) : settledBets.length === 0 ? (
                <div className="text-center py-10 animate-fade-in">
                  <History className="h-8 w-8 mx-auto mb-3 text-muted-foreground/40 animate-fade-in" style={{ animationDelay: "100ms", animationFillMode: "both" }} />
                  <p className="text-muted-foreground font-medium animate-fade-in" style={{ animationDelay: "150ms", animationFillMode: "both" }}>No past bets yet</p>
                  <p className="text-sm text-muted-foreground/60 mt-1 animate-fade-in" style={{ animationDelay: "200ms", animationFillMode: "both" }}>Settled tickets will appear here after you mark a result</p>
                </div>
              ) : (
                settledBets.map((bet, index) => (
                  <div
                    key={bet.id}
                    className="animate-slide-up"
                    style={{ animationDelay: `${index * 40}ms`, animationFillMode: "both" }}
                  >
                    <HistoryCard
                      bet={bet}
                      onEdit={setEditingBet}
                      onResultChange={handleResultChange}
                      onDelete={handleDeleteWithUndo}
                    />
                  </div>
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
              Focus on one sportsbook or source if you are checking a specific set of bets.
            </p>
          </SheetHeader>
          
          <div className="space-y-4">
            {/* Sportsbook Selector - Horizontal Scroll */}
            <div>
              <span className="text-xs text-muted-foreground font-medium block mb-2">Sportsbook</span>
              <SingleSelectFilterPills
                value={selectedBook}
                onValueChange={(value) => updateTrackerView({ sportsbook: value })}
                options={[
                  { value: "all", label: "All Books" },
                  ...uniqueBooks.map((book) => ({ value: book, label: book })),
                ]}
                className="flex flex-nowrap gap-2 overflow-x-auto no-scrollbar pb-1"
                baseButtonClassName="px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0"
                activeClassName="bg-foreground text-background shadow-sm"
                inactiveClassName="bg-muted text-muted-foreground hover:bg-secondary"
                getButtonClassName={(option, active) => {
                  if (!active || option.value === "all") return undefined;
                  return `${SPORTSBOOK_BADGE_COLORS[option.value] || "bg-foreground"} text-white shadow-sm`;
                }}
              />
            </div>
            
            {/* Source Selector - Horizontal Scroll */}
            <div>
              <span className="text-xs text-muted-foreground font-medium block mb-2">Source</span>
              <SingleSelectFilterPills
                value={sourceFilter}
                onValueChange={(value) => updateTrackerView({ source: value })}
                options={([
                  { key: "all", label: "All Bets" },
                  { key: "core", label: "Core Bets" },
                  { key: "promos", label: "Promos" },
                ] as const).map(({ key, label }) => ({
                  value: key,
                  label,
                }))}
                className="flex flex-nowrap gap-2 overflow-x-auto no-scrollbar pb-1"
                baseButtonClassName="px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0"
                activeClassName="bg-foreground text-background shadow-sm"
                inactiveClassName="bg-muted text-muted-foreground hover:bg-secondary"
              />
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
