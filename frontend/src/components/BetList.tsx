"use client";

import { useState, useRef } from "react";
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
import { useBets, useUpdateBetResult, useDeleteBet } from "@/lib/hooks";
import { EditBetModal } from "@/components/EditBetModal";
import type { Bet, BetResult } from "@/lib/types";
import { formatCurrency, formatOdds, cn, formatRelativeTime, formatShortDate, formatFullDateTime } from "@/lib/utils";
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
} from "lucide-react";
import { toast } from "sonner";

const resultConfig: Record<
  BetResult,
  { label: string; color: string; bgColor: string; icon: React.ReactNode }
> = {
  pending: {
    label: "Pending",
    color: "text-yellow-600",
    bgColor: "bg-yellow-50",
    icon: <Clock className="h-4 w-4" />,
  },
  win: {
    label: "Win",
    color: "text-green-600",
    bgColor: "bg-green-50",
    icon: <Check className="h-4 w-4" />,
  },
  loss: {
    label: "Loss",
    color: "text-red-600",
    bgColor: "bg-red-50",
    icon: <X className="h-4 w-4" />,
  },
  push: {
    label: "Push",
    color: "text-gray-600",
    bgColor: "bg-gray-50",
    icon: <Minus className="h-4 w-4" />,
  },
  void: {
    label: "Void",
    color: "text-gray-600",
    bgColor: "bg-gray-50",
    icon: <Minus className="h-4 w-4" />,
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

// ============ SHARED BET CARD BASE ============
// Consistent layout for both Pending and History views
interface BetCardBaseProps {
  bet: Bet;
  headerRight: React.ReactNode;
  footer: React.ReactNode;
  showProfit?: boolean;
  timeDisplay?: "relative" | "date"; // relative for pending, date for history
}

function BetCardBase({ bet, headerRight, footer, showProfit = false, timeDisplay }: BetCardBaseProps) {
  const [expanded, setExpanded] = useState(false);
  const borderColor = sportsbookColors[bet.sportsbook] || "bg-gray-400";
  const textColor = sportsbookTextColors[bet.sportsbook] || "text-gray-600";

  // Format time based on display mode
  const timeText = timeDisplay === "relative" 
    ? formatRelativeTime(bet.created_at)
    : timeDisplay === "date"
    ? formatShortDate(bet.event_date)
    : null;

  return (
    <div className="border rounded-lg overflow-hidden flex">
      {/* Colored left border for sportsbook branding */}
      <div className={cn("w-1 shrink-0", borderColor)} />
      
      <div className="flex-1 p-4 space-y-3">
        {/* Header - Selection first, sportsbook in subtitle */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            {/* Primary: Selection name + time */}
            <div className="flex items-center gap-2">
              <p className="font-semibold text-sm leading-tight">{bet.event}</p>
              {timeText && (
                <span className="text-xs text-muted-foreground shrink-0">• {timeText}</span>
              )}
            </div>
            {/* Secondary: Sportsbook (colored) • Sport • Market */}
            <div className="flex items-center gap-1.5 mt-1">
              <span className={cn("w-2 h-2 rounded-full shrink-0", borderColor)} />
              <span className="text-xs truncate">
                <span className={cn("font-semibold", textColor)}>{bet.sportsbook}</span>
                <span className="text-muted-foreground"> • {bet.sport} • {bet.market}</span>
              </span>
            </div>
          </div>
          {headerRight}
        </div>

      {/* Numbers - Consistent grid */}
      <div className="grid grid-cols-4 gap-4 text-sm">
        <div>
          <p className="text-muted-foreground text-xs">Odds</p>
          <p className="font-mono font-medium">{formatOdds(bet.odds_american)}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Stake</p>
          <p className="font-medium">{formatCurrency(bet.stake)}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">EV</p>
          <p className={cn("font-medium", bet.ev_total > 0 ? "text-green-600" : "text-red-600")}>
            {formatCurrency(bet.ev_total)}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">{showProfit ? "Profit" : "To Win"}</p>
          <p
            className={cn(
              "font-medium",
              showProfit
                ? bet.real_profit === null
                  ? "text-muted-foreground"
                  : bet.real_profit >= 0
                  ? "text-green-600"
                  : "text-red-600"
                : "text-foreground"
            )}
          >
            {showProfit
              ? bet.real_profit !== null
                ? formatCurrency(bet.real_profit)
                : "—"
              : formatCurrency(bet.win_payout - bet.stake)}
          </p>
        </div>
      </div>

      {/* Footer - Varies by card type */}
      {footer}

      {/* Expandable Details - Shared */}
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
            <div>
              <p className="text-muted-foreground text-xs">Promo Type</p>
              <p className="font-medium capitalize">{bet.promo_type.replace("_", " ")}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Win Payout</p>
              <p className="font-medium">{formatCurrency(bet.win_payout)}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Decimal Odds</p>
              <p className="font-mono">{bet.odds_decimal.toFixed(3)}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">EV per $</p>
              <p className="font-mono">{(bet.ev_per_dollar * 100).toFixed(1)}%</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Event Date</p>
              <p className="font-medium">{formatShortDate(bet.event_date)}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Logged</p>
              <p className="font-medium">{formatFullDateTime(bet.created_at)}</p>
            </div>
            {bet.settled_at && (
              <div className="col-span-2">
                <p className="text-muted-foreground text-xs">Settled</p>
                <p className="font-medium">{formatFullDateTime(bet.settled_at)}</p>
              </div>
            )}
          </div>
          {bet.notes && (
            <div className="text-sm mt-3">
              <p className="text-muted-foreground text-xs">Notes</p>
              <p>{bet.notes}</p>
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

  return <BetCardBase bet={bet} headerRight={headerRight} footer={footer} showProfit={false} timeDisplay="relative" />;
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

  const handleDelete = () => {
    deleteBet.mutate(bet.id, {
      onSuccess: () => toast.success("Bet deleted"),
      onError: () => toast.error("Failed to delete bet"),
    });
  };

  const headerRight = (
    <div className="flex items-center gap-2">
      {/* Result Badge */}
      <div className={cn("flex items-center gap-1 px-2 py-1 rounded text-xs font-medium", config.color, config.bgColor)}>
        {config.icon}
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

  return <BetCardBase bet={bet} headerRight={headerRight} footer={footer} showProfit={true} timeDisplay="date" />;
}

// ============ MAIN BET LIST ============
export function BetList() {
  const { data: bets, isLoading, error } = useBets();
  const updateResult = useUpdateBetResult();
  const [editingBet, setEditingBet] = useState<Bet | null>(null);
  const [activeTab, setActiveTab] = useState<"pending" | "history">("pending");

  // Handle result change with undo toast
  const handleResultChange = (bet: Bet, newResult: BetResult, previousResult: BetResult) => {
    updateResult.mutate(
      { id: bet.id, result: newResult },
      {
        onSuccess: () => {
          const toastMessage =
            newResult === "win"
              ? "🎉 Marked as Win"
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

  const pendingBets = bets?.filter((bet) => bet.result === "pending") || [];
  const settledBets = bets?.filter((bet) => bet.result !== "pending") || [];

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          {/* Two-way toggle: Pending | History */}
          <div className="flex rounded-lg bg-muted p-1">
            <Button
              variant={activeTab === "pending" ? "default" : "ghost"}
              size="sm"
              className={cn("flex-1 h-9", activeTab === "pending" && "shadow-sm")}
              onClick={() => setActiveTab("pending")}
            >
              <Clock className="h-4 w-4 mr-2" />
              Pending
              {pendingBets.length > 0 && (
                <span className="ml-2 bg-yellow-100 text-yellow-800 px-1.5 py-0.5 rounded text-xs font-medium">
                  {pendingBets.length}
                </span>
              )}
            </Button>
            <Button
              variant={activeTab === "history" ? "default" : "ghost"}
              size="sm"
              className={cn("flex-1 h-9", activeTab === "history" && "shadow-sm")}
              onClick={() => setActiveTab("history")}
            >
              History
              <span className="ml-2 text-muted-foreground text-xs">({settledBets.length})</span>
            </Button>
          </div>

          {/* Summary stats for pending tab */}
          {activeTab === "pending" && pendingBets.length > 0 && (
            <div className="flex justify-between text-sm text-muted-foreground pt-3">
              <span>
                <span className="font-medium text-foreground">
                  {formatCurrency(pendingBets.reduce((s, b) => s + b.stake, 0))}
                </span>{" "}
                at risk
              </span>
              <span>
                <span className="font-medium text-green-600">
                  +{formatCurrency(pendingBets.reduce((s, b) => s + b.ev_total, 0))}
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
                <p className="text-center text-muted-foreground py-8">
                  No pending bets. All caught up! 🎉
                </p>
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
                <p className="text-center text-muted-foreground py-8">No bet history yet.</p>
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
