"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBets, useUpdateBetResult, useDeleteBet } from "@/lib/hooks";
import type { Bet, BetResult } from "@/lib/types";
import { formatCurrency, formatOdds, cn } from "@/lib/utils";
import {
  Check,
  X,
  Clock,
  Trash2,
  ChevronDown,
  ChevronUp,
  Minus,
} from "lucide-react";

const resultConfig: Record<
  BetResult,
  { label: string; color: string; icon: React.ReactNode }
> = {
  pending: {
    label: "Pending",
    color: "text-yellow-600 bg-yellow-50",
    icon: <Clock className="h-4 w-4" />,
  },
  win: {
    label: "Win",
    color: "text-green-600 bg-green-50",
    icon: <Check className="h-4 w-4" />,
  },
  loss: {
    label: "Loss",
    color: "text-red-600 bg-red-50",
    icon: <X className="h-4 w-4" />,
  },
  push: {
    label: "Push",
    color: "text-gray-600 bg-gray-50",
    icon: <Minus className="h-4 w-4" />,
  },
  void: {
    label: "Void",
    color: "text-gray-600 bg-gray-50",
    icon: <Minus className="h-4 w-4" />,
  },
};

function BetCard({ bet }: { bet: Bet }) {
  const [expanded, setExpanded] = useState(false);
  const updateResult = useUpdateBetResult();
  const deleteBet = useDeleteBet();

  const handleResultChange = (newResult: BetResult) => {
    updateResult.mutate({ id: bet.id, result: newResult });
  };

  const config = resultConfig[bet.result];

  return (
    <div className="border rounded-lg p-4 space-y-3">
      {/* Header Row */}
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-sm">{bet.sportsbook}</span>
            <span className="text-xs px-2 py-0.5 rounded bg-muted">
              {bet.sport}
            </span>
            <span className="text-xs px-2 py-0.5 rounded bg-muted">
              {bet.market}
            </span>
          </div>
          <p className="text-sm text-muted-foreground truncate mt-1">
            {bet.event}
          </p>
        </div>
        <div
          className={cn(
            "flex items-center gap-1 px-2 py-1 rounded text-xs font-medium",
            config.color
          )}
        >
          {config.icon}
          {config.label}
        </div>
      </div>

      {/* Numbers Row */}
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
          <p
            className={cn(
              "font-medium",
              bet.ev_total > 0 ? "text-green-600" : "text-red-600"
            )}
          >
            {formatCurrency(bet.ev_total)}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Profit</p>
          <p
            className={cn(
              "font-medium",
              bet.real_profit === null
                ? "text-muted-foreground"
                : bet.real_profit >= 0
                ? "text-green-600"
                : "text-red-600"
            )}
          >
            {bet.real_profit !== null
              ? formatCurrency(bet.real_profit)
              : "—"}
          </p>
        </div>
      </div>

      {/* Quick Result Buttons (for pending bets) */}
      {bet.result === "pending" && (
        <div className="flex gap-2 pt-2">
          <Button
            size="sm"
            variant="outline"
            className="flex-1 text-green-600 hover:bg-green-50 hover:text-green-700"
            onClick={() => handleResultChange("win")}
            disabled={updateResult.isPending}
          >
            <Check className="h-4 w-4 mr-1" />
            Win
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="flex-1 text-red-600 hover:bg-red-50 hover:text-red-700"
            onClick={() => handleResultChange("loss")}
            disabled={updateResult.isPending}
          >
            <X className="h-4 w-4 mr-1" />
            Loss
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="px-2"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </Button>
        </div>
      )}

      {/* Expand/Collapse for settled bets */}
      {bet.result !== "pending" && (
        <Button
          size="sm"
          variant="ghost"
          className="w-full text-xs text-muted-foreground"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show less" : "Show more"}
          {expanded ? (
            <ChevronUp className="h-3 w-3 ml-1" />
          ) : (
            <ChevronDown className="h-3 w-3 ml-1" />
          )}
        </Button>
      )}

      {/* Expanded Details */}
      {expanded && (
        <div className="pt-2 border-t space-y-3">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Promo Type</p>
              <p className="font-medium capitalize">
                {bet.promo_type.replace("_", " ")}
              </p>
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
              <p className="font-mono">
                {(bet.ev_per_dollar * 100).toFixed(1)}%
              </p>
            </div>
          </div>

          {bet.notes && (
            <div className="text-sm">
              <p className="text-muted-foreground text-xs">Notes</p>
              <p>{bet.notes}</p>
            </div>
          )}

          {/* Result Change Buttons (for settled bets) */}
          {bet.result !== "pending" && (
            <div className="flex gap-2 pt-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleResultChange("pending")}
                disabled={updateResult.isPending}
              >
                <Clock className="h-4 w-4 mr-1" />
                Pending
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleResultChange("push")}
                disabled={updateResult.isPending}
              >
                Push
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-red-600 hover:bg-red-50 ml-auto"
                onClick={() => {
                  if (confirm("Delete this bet?")) {
                    deleteBet.mutate(bet.id);
                  }
                }}
                disabled={deleteBet.isPending}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function BetList() {
  const { data: bets, isLoading, error } = useBets();
  const [filter, setFilter] = useState<"all" | "pending" | "settled">("all");

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

  const filteredBets = bets?.filter((bet) => {
    if (filter === "pending") return bet.result === "pending";
    if (filter === "settled") return bet.result !== "pending";
    return true;
  });

  const pendingCount = bets?.filter((b) => b.result === "pending").length || 0;

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Bet History</CardTitle>
          <div className="flex gap-1">
            <Button
              size="sm"
              variant={filter === "all" ? "default" : "ghost"}
              onClick={() => setFilter("all")}
            >
              All
            </Button>
            <Button
              size="sm"
              variant={filter === "pending" ? "default" : "ghost"}
              onClick={() => setFilter("pending")}
            >
              Pending {pendingCount > 0 && `(${pendingCount})`}
            </Button>
            <Button
              size="sm"
              variant={filter === "settled" ? "default" : "ghost"}
              onClick={() => setFilter("settled")}
            >
              Settled
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {filteredBets?.length === 0 ? (
          <p className="text-center text-muted-foreground py-8">
            No bets yet. Add your first bet above!
          </p>
        ) : (
          filteredBets?.map((bet) => <BetCard key={bet.id} bet={bet} />)
        )}
      </CardContent>
    </Card>
  );
}
