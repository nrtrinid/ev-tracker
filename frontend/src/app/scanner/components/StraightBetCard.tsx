import { ChevronRight, ExternalLink, Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { MarketSide } from "@/lib/types";
import { calculateStealthStake, cn, formatCurrency, formatOdds } from "@/lib/utils";
import { buildScannerActionModel } from "../scanner-ui-model";

interface StraightBetCardProps {
  side: MarketSide & { _retention?: number; _boostedEV?: number };
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  tutorialMode?: boolean;
  kellyMultiplier: number;
  bankroll: number;
  boostPercent: number;
  onLogBet: (side: MarketSide) => void;
  onAddToCart: (side: MarketSide) => void;
  onStartPlaceFlow: (side: MarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

function formatGameTime(isoString: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function bookAbbrev(name: string): string {
  const map: Record<string, string> = {
    DraftKings: "DK",
    FanDuel: "FD",
    BetMGM: "MGM",
    Caesars: "CZR",
    "ESPN Bet": "ESPN",
  };
  return map[name] || name;
}

function calculateBoostedEV(side: MarketSide, boostPercent: number): number {
  const baseProfit = side.book_decimal - 1;
  const boostedProfit = baseProfit * (1 + boostPercent / 100);
  const boostedDecimal = 1 + boostedProfit;
  return (side.true_prob * boostedDecimal - 1) * 100;
}

function boostedDecimalOdds(side: MarketSide, boostPercent: number): number {
  const baseProfit = side.book_decimal - 1;
  return 1 + baseProfit * (1 + boostPercent / 100);
}

function decimalToAmerican(decimal: number): number {
  if (decimal >= 2.0) return Math.round((decimal - 1) * 100);
  return Math.round(-100 / (decimal - 1));
}

function calculateRetention(side: MarketSide): number {
  return (side.book_decimal - 1) * side.true_prob;
}

function getLootTier(evPercentage: number): { colorClass: string } {
  if (evPercentage < 1.5) {
    return { colorClass: "text-muted-foreground" };
  }
  if (evPercentage < 3.5) {
    return { colorClass: "text-[#4A7C59]" };
  }
  if (evPercentage < 5.5) {
    return { colorClass: "text-[#3B6C8E]" };
  }
  return { colorClass: "text-[#9A3F86]" };
}

function getWorkflowHint(params: {
  activeLens: StraightBetCardProps["activeLens"];
  side: MarketSide;
  boostPercent: number;
}): string {
  const { activeLens, side, boostPercent } = params;
  const duplicateState = side.scanner_duplicate_state ?? "new";
  if (duplicateState === "better_now") {
    return "This line is better than the one you already logged.";
  }
  if (duplicateState === "already_logged") {
    return "You already have exposure here, so only add it if you want another ticket.";
  }
  if (activeLens === "profit_boost") {
    return `With the ${boostPercent}% boost applied, this price looks better than the regular line.`;
  }
  if (activeLens === "bonus_bet") {
    return "This is a cleaner way to turn a bonus bet into cash value.";
  }
  if (activeLens === "qualifier") {
    return "This stays closer to break-even, which is useful for promo setup bets.";
  }
  return `This line looks about ${Math.abs(side.ev_percentage).toFixed(1)}% better than our fair-price estimate.`;
}

export function StraightBetCard({
  side,
  activeLens,
  tutorialMode = false,
  kellyMultiplier,
  bankroll,
  boostPercent,
  onLogBet,
  onAddToCart,
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: StraightBetCardProps) {
  const actionModel = buildScannerActionModel({
    sportsbook: side.sportsbook,
    sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
  });

  const duplicateState = side.scanner_duplicate_state ?? "new";
  const rawKellyStake = Math.max(0, side.base_kelly_fraction * kellyMultiplier * bankroll);
  const stealthKellyStake = calculateStealthStake(rawKellyStake);
  const workflowHint = getWorkflowHint({ activeLens, side, boostPercent });

  const metric =
    activeLens === "bonus_bet"
      ? {
          label: "Retention",
          value: `${(((side._retention ?? calculateRetention(side)) * 100).toFixed(1))}%`,
        }
      : activeLens === "profit_boost"
        ? {
            label: "Boost Edge",
            value: `${(((side._boostedEV ?? calculateBoostedEV(side, boostPercent)) >= 0 ? "+" : "") + (side._boostedEV ?? calculateBoostedEV(side, boostPercent)).toFixed(1))}%`,
          }
        : {
            label: "Edge",
            value: `${side.ev_percentage >= 0 ? "+" : ""}${side.ev_percentage.toFixed(1)}%`,
          };

  let metricColorClass = "text-foreground";
  if (activeLens === "standard") {
    metricColorClass = getLootTier(side.ev_percentage).colorClass;
  } else if (activeLens === "profit_boost") {
    const bev = side._boostedEV ?? calculateBoostedEV(side, boostPercent);
    metricColorClass = bev > 0 ? "text-[#C4A35A]" : "text-muted-foreground";
  } else if (activeLens === "bonus_bet") {
    metricColorClass = "text-[#0EA5A4]";
  } else if (activeLens === "qualifier") {
    if (side.ev_percentage < -2) metricColorClass = "text-[#B85C38]";
    else if (side.ev_percentage >= 0) metricColorClass = "text-[#4A7C59]";
  }

  return (
    <Card className="card-hover">
      <CardContent className="space-y-2.5 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            {/* Metadata row: book + sport badges */}
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white",
                  bookColors[side.sportsbook] || "bg-foreground"
                )}
              >
                {bookAbbrev(side.sportsbook)}
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {sportDisplayMap[side.sport] || side.sport}
              </span>
              {duplicateState !== "new" && (
                <span className="rounded border border-[#B85C38]/35 bg-[#B85C38]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#8B3D20]">
                  Already Logged
                </span>
              )}
              {duplicateState === "better_now" && (
                <span className="rounded border border-[#4A7C59]/35 bg-[#4A7C59]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#2E5D39]">
                  Better Now
                </span>
              )}
            </div>

            {/* Title row: team name + market type (non-wrapping) */}
            <div className="mb-2 flex items-center gap-2">
              <p className="line-clamp-2 text-sm font-semibold">
                {side.surface === "player_props" ? side.display_name : side.team}
              </p>
              <span className="shrink-0 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {side.surface === "player_props" ? "Prop" : "ML"}
              </span>
            </div>

            <p className="line-clamp-1 mt-0.5 text-xs text-muted-foreground">{side.event}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">{workflowHint}</p>

            <div className="mt-2 flex flex-col gap-1 text-xs">
              <div className="flex flex-wrap items-center gap-3">
                {(() => {
                  const fairAmerican = decimalToAmerican(1 / side.true_prob);

                  if (activeLens === "profit_boost") {
                    const boostedAmerican = decimalToAmerican(boostedDecimalOdds(side, boostPercent));
                    return (
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono font-medium">
                        <span className="text-[11px] text-muted-foreground">Book</span>
                        <span className="mr-1 text-muted-foreground/70 line-through">
                          {formatOdds(side.book_odds)}
                        </span>
                        <span className="text-foreground">{formatOdds(boostedAmerican)}</span>
                        <span className="text-[11px] text-muted-foreground">
                          Fair {formatOdds(fairAmerican)}
                        </span>
                      </span>
                    );
                  }

                  return (
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono font-medium">
                      <span className="text-[11px] text-muted-foreground">Book</span>
                      <span className="text-foreground">{formatOdds(side.book_odds)}</span>
                      <span className="text-[11px] text-muted-foreground">
                        Fair {formatOdds(fairAmerican)}
                      </span>
                    </span>
                  );
                })()}

                {duplicateState === "better_now" && side.best_logged_odds_american != null && (
                  <span className="text-[11px] text-[#2E5D39]">
                    Logged at {formatOdds(side.best_logged_odds_american)} - now{" "}
                    {formatOdds(side.current_odds_american ?? side.book_odds)}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                <span>{formatGameTime(side.commence_time)}</span>
              </div>
            </div>
          </div>

          <div className="shrink-0 sm:min-w-[92px]">
            <div className="flex items-start justify-between rounded-lg border border-border/60 bg-muted/30 px-3 py-2 sm:block sm:rounded-none sm:border-0 sm:bg-transparent sm:px-0 sm:py-0 sm:text-right">
              <div>
              <p className={cn("text-lg font-mono font-bold leading-tight", metricColorClass)}>
                {metric.value}
              </p>
              <p className="text-[10px] text-muted-foreground">{metric.label}</p>
              </div>

              {activeLens === "standard" ? (
                <p className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground sm:justify-end">
                  Suggested stake:
                  <span className="font-mono font-semibold text-foreground">
                    {formatCurrency(stealthKellyStake)}
                  </span>
                  <span title={`Raw Kelly: ${formatCurrency(rawKellyStake)}`} className="inline-flex">
                    <Info
                      className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70"
                      aria-label="Raw Kelly amount"
                    />
                  </span>
                </p>
              ) : (
                <p className="mt-0.5 text-[10px] text-muted-foreground">Tap through to compare your bet slip.</p>
              )}
            </div>

          </div>
        </div>

        {tutorialMode ? (
          <div className="border-t border-border/60 pt-2">
            <Button
              type="button"
              className="h-10 w-full text-xs font-semibold"
              onClick={() => onLogBet(side)}
            >
              Practice Log Bet
              <ChevronRight className="ml-1 h-3.5 w-3.5" />
            </Button>
          </div>
        ) : actionModel.primary.kind === "open" && actionModel.primary.href ? (
          <div className="space-y-2 border-t border-border/60 pt-2">
            {actionModel.trustHint && (
              <p className="text-[11px] text-muted-foreground">{actionModel.trustHint}</p>
            )}
            <Button asChild className="h-10 w-full text-xs font-semibold">
              <a
                href={actionModel.primary.href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => onStartPlaceFlow(side)}
              >
                {actionModel.primary.label}
                <ExternalLink className="ml-1 h-3.5 w-3.5" />
              </a>
            </Button>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                type="button"
                variant="outline"
                className="h-10 flex-1 text-xs font-medium"
                onClick={() => onLogBet(side)}
              >
                {actionModel.secondary?.label ?? "Review & Log"}
                <ChevronRight className="ml-1 h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="h-10 flex-1 text-xs font-medium text-muted-foreground"
                onClick={() => onAddToCart(side)}
              >
                Save to Cart
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-2 border-t border-border/60 pt-2">
            <Button
              type="button"
              className="h-10 w-full text-xs font-semibold"
              onClick={() => onLogBet(side)}
            >
              {actionModel.primary.label}
              <ChevronRight className="ml-1 h-3.5 w-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="h-10 w-full text-xs font-medium text-muted-foreground"
              onClick={() => onAddToCart(side)}
            >
              Save to Cart
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
