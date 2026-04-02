import { Check, ChevronRight, ExternalLink, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { MarketSide } from "@/lib/types";
import { cn, formatOdds } from "@/lib/utils";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { buildScannerActionModel, canAddScannerLensToParlayCart } from "../scanner-ui-model";
import { getStandardEdgeColorClass } from "./scanner-card-colors";

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

/** Promos mode merges player_props into the straight-bets card; use prop-style labels + titles. */
function formatPlayerPropMarketTag(marketKey: string | undefined | null): string {
  const key = (marketKey ?? "").trim();
  const map: Record<string, string> = {
    player_points: "PTS",
    player_rebounds: "REB",
    player_assists: "AST",
    player_threes: "3PM",
    player_points_rebounds_assists: "PRA",
  };
  if (map[key]) return map[key];
  if (!key) return "Prop";
  return key.replace(/^player_/, "").replaceAll("_", " ").toUpperCase();
}

function primarySelectionTitle(side: MarketSide): string {
  if (side.surface === "player_props") {
    return (
      side.display_name.trim() ||
      side.player_name.trim() ||
      side.team?.trim() ||
      ""
    );
  }
  const marketKey = String(side.market_key || "").toLowerCase();
  if (marketKey.includes("totals")) {
    const sideLabel = String(side.selection_side ?? side.team ?? "").trim();
    const lineValue = side.line_value;
    const lineLabel =
      lineValue == null
        ? ""
        : Number.isInteger(lineValue)
          ? `${lineValue}`
          : `${Number.parseFloat(lineValue.toFixed(2))}`;
    const normalizedSideLabel = `${sideLabel.charAt(0).toUpperCase()}${sideLabel.slice(1)}`.trim();
    return `Game Total ${normalizedSideLabel}${lineLabel ? ` ${lineLabel}` : ""}`.trim();
  }
  if (marketKey.includes("spreads")) {
    const lineValue = side.line_value;
    const lineLabel =
      lineValue == null
        ? ""
        : lineValue > 0
          ? ` +${Number.isInteger(lineValue) ? lineValue : Number.parseFloat(lineValue.toFixed(2))}`
          : ` ${Number.isInteger(lineValue) ? lineValue : Number.parseFloat(lineValue.toFixed(2))}`;
    return `${(side.team?.trim() || side.team_short?.trim() || "").trim()}${lineLabel}`;
  }
  return (side.team?.trim() || side.team_short?.trim() || "").trim();
}

function formatStraightMarketLabel(side: MarketSide): string {
  if (side.surface === "player_props") {
    return formatPlayerPropMarketTag(side.market_key);
  }
  const key = String(side.market_key || "").toLowerCase();
  if (key.includes("totals")) return "Total";
  if (key.includes("spreads")) return "Spread";
  return "ML";
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

function getDuplicateBadge(duplicateState: MarketSide["scanner_duplicate_state"]) {
  if (duplicateState === "better_now") {
    return {
      label: "Better Now",
      className:
        "rounded border border-profit/35 bg-profit/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-profit",
    };
  }
  if (duplicateState === "already_logged") {
    return {
      label: "Already Placed",
      className:
        "rounded border border-loss/35 bg-loss/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-loss",
    };
  }
  if (duplicateState === "logged_elsewhere") {
    return {
      label: "Logged Elsewhere",
      className:
        "rounded border border-primary/35 bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground",
    };
  }
  return null;
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
  const { cart, isHydrated, removeCartLeg } = useBettingPlatformStore();
  const actionModel = buildScannerActionModel({
    sportsbook: side.sportsbook,
    sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
    sportsbookDeeplinkLevel: side.sportsbook_deeplink_level,
  });

  const duplicateState = side.scanner_duplicate_state ?? "new";
  const duplicateBadge = getDuplicateBadge(duplicateState);
  const canAddToCart = canAddScannerLensToParlayCart(activeLens);

  // kellyMultiplier and bankroll are kept in props for API compatibility (used by LogBetDrawer via onLogBet)
  void (kellyMultiplier * bankroll);

  const boostedEV = side._boostedEV ?? calculateBoostedEV(side, boostPercent);
  const metric =
    activeLens === "bonus_bet"
      ? {
          label: "Retention",
          value: `${((side._retention ?? calculateRetention(side)) * 100).toFixed(1)}%`,
        }
      : activeLens === "profit_boost"
        ? {
            label: "Boost Edge",
            value: `${boostedEV >= 0 ? "+" : ""}${boostedEV.toFixed(1)}%`,
          }
        : {
            label: "Edge",
            value: `${side.ev_percentage >= 0 ? "+" : ""}${side.ev_percentage.toFixed(1)}%`,
          };

  let metricColorClass = "text-foreground";
  if (activeLens === "standard") {
    metricColorClass = getStandardEdgeColorClass(side.ev_percentage);
  } else if (activeLens === "profit_boost") {
    metricColorClass = boostedEV > 0 ? "text-primary" : "text-muted-foreground";
  } else if (activeLens === "bonus_bet") {
    metricColorClass = "text-[#0EA5A4]";
  } else if (activeLens === "qualifier") {
    if (side.ev_percentage < -2) metricColorClass = "text-destructive";
    else if (side.ev_percentage >= 0) metricColorClass = "text-profit";
  }

  const fairAmerican = decimalToAmerican(1 / side.true_prob);
  const marketLabel = formatStraightMarketLabel(side);
  const legId = `${side.surface}:${side.selection_key ?? `${side.event}:${side.team}:${side.sportsbook}:${side.market_key ?? "ml"}`}`;
  const isInCart = isHydrated && cart.some((leg) => leg.id === legId);

  return (
    <Card className="card-hover cursor-pointer" onClick={() => onLogBet(side)}>
      <CardContent className="px-3 py-2.5">
        {/* Row 0: badges left, EV stacked right */}
        <div className="mb-1 flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
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
            <span className="rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {marketLabel}
            </span>
            {duplicateBadge && (
              <span className={duplicateBadge.className}>{duplicateBadge.label}</span>
            )}
          </div>
          <div className="shrink-0 text-right" data-testid="ev-display">
            <p className={cn("font-mono text-base font-bold leading-none", metricColorClass)}>
              {metric.value}
            </p>
            <p className="mt-0.5 text-[10px] tracking-wide text-muted-foreground">{metric.label}</p>
          </div>
        </div>

        {/* Row 1: team / player prop display name (promos merges props into this card) */}
        <p className="line-clamp-1 text-sm font-semibold leading-snug">
          {primarySelectionTitle(side)}
        </p>

        {/* Row 2: matchup + formatted game time */}
        <p className="mt-0.5 text-xs text-muted-foreground">
          {side.event} • {formatGameTime(side.commence_time)}
        </p>

        {/* Row 3: book odds, fair odds (lens-aware) */}
        <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[11px] font-medium">
          {activeLens === "profit_boost" ? (
            <>
              <span className="text-muted-foreground">
                Book <span className="text-muted-foreground/70 line-through">{formatOdds(side.book_odds)}</span>{" "}
                <span className="text-foreground">{formatOdds(decimalToAmerican(boostedDecimalOdds(side, boostPercent)))}</span>
              </span>
              <span className="text-muted-foreground">
                Fair <span className="text-foreground">{formatOdds(fairAmerican)}</span>
              </span>
            </>
          ) : (
            <>
              <span className="text-muted-foreground">
                Book <span className="text-foreground">{formatOdds(side.book_odds)}</span>
              </span>
              <span className="text-muted-foreground">
                Fair <span className="text-foreground">{formatOdds(fairAmerican)}</span>
              </span>
            </>
          )}
          {duplicateState === "better_now" && side.best_logged_odds_american != null && (
            <span className="text-[11px] text-profit">
              Logged at {formatOdds(side.best_logged_odds_american)} · now{" "}
              {formatOdds(side.current_odds_american ?? side.book_odds)}
            </span>
          )}
        </div>

        {/* Row 4: action row — Place + toggle grouped left, Review pinned right */}
        {tutorialMode ? (
          <div className="mt-1.5 border-t border-border/60 pt-1.5">
            <Button
              type="button"
              className="h-8 w-full text-xs font-medium"
              onClick={(e) => {
                e.stopPropagation();
                onLogBet(side);
              }}
            >
              Practice Log Bet
              <ChevronRight className="ml-1 h-3 w-3" />
            </Button>
          </div>
        ) : actionModel.primary.kind === "open" && actionModel.primary.href ? (
          <div className="mt-1.5 flex items-center gap-1.5 border-t border-border/60 pt-1.5">
            <Button asChild className="h-8 flex-[0.9] text-xs font-medium" onClick={(e) => e.stopPropagation()}>
              <a
                href={actionModel.primary.href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => onStartPlaceFlow(side)}
              >
                {actionModel.primary.label}
                <ExternalLink className="ml-1 h-3 w-3" />
              </a>
            </Button>
            {canAddToCart && (
              <button
                type="button"
                aria-label={isInCart ? "Remove from cart" : "Add to cart"}
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded border text-xs transition-colors",
                  isInCart
                    ? "border-primary/30 bg-primary/15 text-primary"
                    : "border-border bg-muted/40 text-muted-foreground hover:border-primary/30 hover:bg-primary/10 hover:text-primary"
                )}
                onClick={(e) => {
                  e.stopPropagation();
                  if (isInCart) removeCartLeg(legId);
                  else onAddToCart(side);
                }}
              >
                {isInCart ? <Check className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
              </button>
            )}
            <button
              type="button"
              className="ml-auto flex shrink-0 items-center whitespace-nowrap text-xs text-muted-foreground"
              onClick={(e) => {
                e.stopPropagation();
                onLogBet(side);
              }}
            >
              Review <ChevronRight className="ml-0.5 h-3 w-3" />
            </button>
          </div>
        ) : (
          <div className="mt-1.5 flex items-center gap-1.5 border-t border-border/60 pt-1.5">
            <Button
              type="button"
              className="h-8 flex-[0.9] text-xs font-medium"
              onClick={(e) => {
                e.stopPropagation();
                onLogBet(side);
              }}
            >
              {actionModel.primary.label}
              <ChevronRight className="ml-1 h-3 w-3" />
            </Button>
            {canAddToCart && (
              <button
                type="button"
                aria-label={isInCart ? "Remove from cart" : "Add to cart"}
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded border text-xs transition-colors",
                  isInCart
                    ? "border-primary/30 bg-primary/15 text-primary"
                    : "border-border bg-muted/40 text-muted-foreground hover:border-primary/30 hover:bg-primary/10 hover:text-primary"
                )}
                onClick={(e) => {
                  e.stopPropagation();
                  if (isInCart) removeCartLeg(legId);
                  else onAddToCart(side);
                }}
              >
                {isInCart ? <Check className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
              </button>
            )}
            <button
              type="button"
              className="ml-auto flex shrink-0 items-center whitespace-nowrap text-xs text-muted-foreground"
              onClick={(e) => {
                e.stopPropagation();
                onLogBet(side);
              }}
            >
              Review <ChevronRight className="ml-0.5 h-3 w-3" />
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
