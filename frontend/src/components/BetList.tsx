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
import { useBets, useUpdateBetResult, useDeleteBet, useBalances } from "@/lib/hooks";
import { EditBetModal } from "@/components/EditBetModal";
import type { Bet, BetResult } from "@/lib/types";
import { formatCurrency, formatOdds, cn, formatRelativeTime, formatShortDate, formatFullDateTime, americanToDecimal } from "@/lib/utils";
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

// ============ PROMO TYPE DISPLAY CONFIG ============
const promoTypeConfig: Record<string, { short: string; bg: string; text: string }> = {
  standard: { short: "Std", bg: "bg-[#DDD5C7]", text: "text-[#6B5E4F]" },
  bonus_bet: { short: "BB", bg: "bg-[#7A9E7E]/20", text: "text-[#2C2416]" },
  no_sweat: { short: "NS", bg: "bg-[#4A7C59]/15", text: "text-[#4A7C59]" },
  promo_qualifier: { short: "PQ", bg: "bg-[#B85C38]/15", text: "text-[#B85C38]" },
  boost_30: { short: "30%", bg: "bg-[#C4A35A]/20", text: "text-[#8B7355]" },
  boost_50: { short: "50%", bg: "bg-[#C4A35A]/20", text: "text-[#8B7355]" },
  boost_100: { short: "100%", bg: "bg-[#C4A35A]/20", text: "text-[#8B7355]" },
  boost_custom: { short: "Boost", bg: "bg-[#C4A35A]/20", text: "text-[#8B7355]" },
};

// ============ MARKET VIG DEFAULTS ============
const MARKET_VIG: Record<string, number> = {
  ML: 0.045,
  Spread: 0.045,
  Total: 0.045,
  Parlay: 0.12,
  Prop: 0.07,
  Futures: 0.07,
  SGP: 0.12,
};

// ============ HELPER FUNCTIONS ============
function calculateImpliedProb(oddsAmerican: number): number {
  if (oddsAmerican === 0) return 0;
  if (oddsAmerican > 0) {
    return 100 / (oddsAmerican + 100);
  } else {
    return Math.abs(oddsAmerican) / (Math.abs(oddsAmerican) + 100);
  }
}

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
  const promoConfig = promoTypeConfig[bet.promo_type] || { short: "Std", bg: "bg-[#DDD5C7]", text: "text-[#6B5E4F]" };
  
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
                  promoConfig.bg,
                  promoConfig.text
                )}>
                  {promoLabel}
                </span>
              )}
              <span className="text-xs text-muted-foreground">{bet.sport} • {bet.market}</span>
            </div>
          </div>
          {headerRight}
        </div>

        {/* Data Row: Odds, Stake, EV, To Win/Profit */}
        <div className="grid grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground text-xs">Odds</p>
            <p className="font-mono font-semibold">{formatOdds(bet.odds_american)}</p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Stake</p>
            <p className="font-mono font-medium">{formatCurrency(bet.stake)}</p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">EV</p>
            <p className={cn("font-mono font-semibold", bet.ev_total >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]")}>
              {bet.ev_total >= 0 ? "+" : ""}{formatCurrency(bet.ev_total)}
            </p>
          </div>
          <div>
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
          <div className="pt-2 border-t">
            <div className="grid grid-cols-2 gap-4 text-sm">
              {/* Required Win % - always show */}
              <div>
                <p className="text-muted-foreground text-xs">Req. Win %</p>
                <p className="font-mono">{(impliedProb * 100).toFixed(1)}%</p>
              </div>
              {/* Pending: Vig | Settled: EV per $ */}
              {mode === "pending" ? (
                <div>
                  <p className="text-muted-foreground text-xs">Vig</p>
                  <p className="font-mono">{(displayVig * 100).toFixed(1)}%</p>
                </div>
              ) : (
                <div>
                  <p className="text-muted-foreground text-xs">EV per $</p>
                  <p className="font-mono">{(bet.ev_per_dollar * 100).toFixed(1)}%</p>
                </div>
              )}
              {/* Pending: EV per $ | Settled: Event Date */}
              {mode === "pending" ? (
                <div>
                  <p className="text-muted-foreground text-xs">EV per $</p>
                  <p className="font-mono">{(bet.ev_per_dollar * 100).toFixed(1)}%</p>
                </div>
              ) : (
                <div>
                  <p className="text-muted-foreground text-xs">Event Date</p>
                  <p className="font-medium">{formatShortDate(bet.event_date)}</p>
                </div>
              )}
              {/* Pending: Event Date | Settled: Win Payout (closer to profit - right column) */}
              {mode === "pending" ? (
                <div>
                  <p className="text-muted-foreground text-xs">Event Date</p>
                  <p className="font-medium">{formatShortDate(bet.event_date)}</p>
                </div>
              ) : (
                <div>
                  <p className="text-muted-foreground text-xs">Win Payout</p>
                  <p className="font-mono">{formatCurrency(bet.win_payout)}</p>
                </div>
              )}
              {/* Logged */}
              <div>
                <p className="text-muted-foreground text-xs">Logged</p>
                <p className="font-medium">{formatFullDateTime(bet.created_at)}</p>
              </div>
              {/* Settled - settled only */}
              {bet.settled_at && (
                <div>
                  <p className="text-muted-foreground text-xs">Settled</p>
                  <p className="font-medium">{formatFullDateTime(bet.settled_at)}</p>
                </div>
              )}
            </div>
            {/* Opposing Odds - if present */}
            {bet.opposing_odds && (
              <div className="col-span-2">
                <p className="text-muted-foreground text-xs">Opposing Line</p>
                <p className="font-mono text-xs">{formatOdds(bet.opposing_odds)}</p>
              </div>
            )}
            {/* Notes - if present */}
            {bet.notes && (
              <div className="col-span-2 text-sm mt-3">
                <p className="text-muted-foreground text-xs mb-1">Notes</p>
                <p className="ruled-lines pl-2 py-1 min-h-[24px]">{bet.notes}</p>
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
}

function PendingCard({ bet, onEdit, onResultChange }: PendingCardProps) {
  const deleteBet = useDeleteBet();

  const handleDelete = () => {
    deleteBet.mutate(bet.id, {
      onSuccess: () => toast.success("Bet deleted"),
      onError: () => toast.error("Failed to delete bet"),
    });
  };

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
        <DropdownMenuItem onClick={handleDelete} className="text-red-600">
          <Trash2 className="h-4 w-4 mr-2" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const footer = (
    <div className="flex gap-3 pt-2">
      <Button
        size="lg"
        variant="outline"
        className="flex-1 h-12 text-green-600 border-green-200 hover:bg-green-50 hover:text-green-700 hover:border-green-300"
        onClick={() => onResultChange(bet, "win", "pending")}
      >
        <Check className="h-5 w-5 mr-2" />
        Won
      </Button>
      <Button
        size="lg"
        variant="outline"
        className="flex-1 h-12 text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700 hover:border-red-300"
        onClick={() => onResultChange(bet, "loss", "pending")}
      >
        <X className="h-5 w-5 mr-2" />
        Lost
      </Button>
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
}

function HistoryCard({ bet, onEdit, onResultChange }: HistoryCardProps) {
  const deleteBet = useDeleteBet();
  const config = resultConfig[bet.result];
  
  // Random stamp rotation for realistic hand-stamped look - re-randomizes when result changes
  const [randomRotation, setRandomRotation] = useState(Math.floor(Math.random() * 7) - 3);
  
  // Re-randomize when result changes (like applying a new stamp)
  useEffect(() => {
    setRandomRotation(Math.floor(Math.random() * 7) - 3);
  }, [bet.result]);

  const handleDelete = () => {
    deleteBet.mutate(bet.id, {
      onSuccess: () => toast.success("Bet deleted"),
      onError: () => toast.error("Failed to delete bet"),
    });
  };

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
          <DropdownMenuItem onClick={handleDelete} className="text-red-600">
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

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          Loading bets...
        </CardContent>
      </Card>
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
      return bet.promo_type === "bonus_bet" || 
             bet.promo_type?.includes("boost");
    }
    // "cash" = standard bets (not bonus/boost)
    return bet.promo_type === "standard" || 
           bet.promo_type === null || 
           bet.promo_type === undefined;
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
          {/* Compact Header: Tabs + Filter Button */}
          <div className="flex items-center justify-between -mx-2 -mt-2 mb-2">
            {/* Manila folder tabs: Pending | History */}
            <div className="flex gap-1">
            <button
              className={cn(
                "folder-tab px-4 py-2 flex items-center gap-2",
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
                "folder-tab px-4 py-2 flex items-center gap-2",
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
              Filter
              {activeFilterCount > 0 && (
                <span className="ml-0.5 px-1.5 py-0.5 text-xs rounded-full bg-background text-foreground">
                  {activeFilterCount}
                </span>
              )}
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
          
          <div className="space-y-6">
            {/* Sportsbook Selector */}
            <div>
              <h3 className="text-sm font-medium mb-3">Sportsbook</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => setSelectedBook("all")}
                  className={cn(
                    "px-3 py-2 rounded-lg text-sm font-medium transition-colors",
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
                      "px-3 py-2 rounded-lg text-sm font-medium transition-colors",
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
            
            {/* Bet Type Selector */}
            <div>
              <h3 className="text-sm font-medium mb-3">Bet Type</h3>
              <div className="flex flex-wrap gap-2">
                {([
                  { key: "all", label: "All Bets" },
                  { key: "cash", label: "Cash Bets" },
                  { key: "bonus", label: "Bonus & Boosts" },
                ] as const).map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => setBetTypeFilter(key)}
                    className={cn(
                      "px-3 py-2 rounded-lg text-sm font-medium transition-colors",
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
