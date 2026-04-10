import { Check, ChevronRight, ExternalLink, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { ONBOARDING_HIGHLIGHT_TARGETS } from "@/lib/onboarding-guidance";
import type { MarketSide } from "@/lib/types";
import { calculateStealthStake, cn, formatCurrency, formatOdds } from "@/lib/utils";
import { buildScannerActionModel, canAddScannerLensToParlayCart } from "../scanner-ui-model";
import { buildEventNicknameLabel } from "./event-nickname-label";
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
        "rounded border border-[#4A7C59]/35 bg-[#4A7C59]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#2E5D39]",
    };
  }
  if (duplicateState === "already_logged") {
    return {
      label: "Already Placed",
      className:
        "rounded border border-[#B85C38]/35 bg-[#B85C38]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#8B3D20]",
    };
  }
  if (duplicateState === "logged_elsewhere") {
    return {
      label: "Logged Elsewhere",
      className:
        "rounded border border-[#C4A35A]/35 bg-[#C4A35A]/12 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#6B5E4F]",
    };
  }
  return null;
}

function formatLineToken(value: number, options?: { includePlus?: boolean }): string {
  const includePlus = options?.includePlus ?? false;
  const normalized = Number.parseFloat(value.toFixed(2));
  const token = `${normalized}`.replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
  if (includePlus && normalized > 0 && !token.startsWith("+")) return `+${token}`;
  return token;
}

function formatMarketBadge(marketKey: string): string {
  if (marketKey === "spreads") return "SPR";
  if (marketKey === "totals") return "TOT";
  return "ML";
}

function buildStraightCardTitle(side: MarketSide): string {
  const marketKey = String(side.market_key || "h2h").toLowerCase();
  const selectionSide = String(side.selection_side || "").toLowerCase();

  if (marketKey === "totals") {
    const sideLabel = selectionSide === "under" ? "Under" : selectionSide === "over" ? "Over" : side.team || "Total";
    if (typeof side.line_value === "number" && Number.isFinite(side.line_value)) {
      return `${sideLabel} ${formatLineToken(side.line_value)}`;
    }
    return sideLabel;
  }

  if (marketKey === "spreads") {
    const teamLabel = side.team || (selectionSide === "home" ? "Home" : selectionSide === "away" ? "Away" : "Team");
    if (typeof side.line_value === "number" && Number.isFinite(side.line_value)) {
      return `${teamLabel} ${formatLineToken(side.line_value, { includePlus: true })}`;
    }
    return teamLabel;
  }

  return side.team || side.event;
}

function formatPropMarketLabel(marketKey: string | undefined | null): string {
  const key = (marketKey ?? "").trim();
  const map: Record<string, string> = {
    player_points: "PTS",
    player_rebounds: "REB",
    player_assists: "AST",
    player_threes: "3PM",
    player_points_rebounds_assists: "PRA",
  };
  if (map[key]) return map[key];
  if (!key) return "PROP";
  return key.replace(/^player_/, "").replaceAll("_", " ").toUpperCase();
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
  const isPlayerProp = side.surface === "player_props";
  const straightMarketKey = String(side.market_key || "h2h").toLowerCase();
  const cardTitle = isPlayerProp
    ? (side.display_name || side.player_name || side.team || "Player prop")
    : buildStraightCardTitle(side);
  const marketLabel = isPlayerProp
    ? formatPropMarketLabel(side.market_key)
    : formatMarketBadge(straightMarketKey);
  const canAddToCart = canAddScannerLensToParlayCart(activeLens);
  const selectionKey = side.selection_key ?? `${side.event_id ?? side.commence_time}:${side.team}`;
  const legId = `${side.surface}:${selectionKey}:${side.sportsbook}`;
  const isInCart = isHydrated && cart.some((leg) => leg.id === legId);

  const boostedEV = side._boostedEV ?? calculateBoostedEV(side, boostPercent);
  const retention = side._retention ?? calculateRetention(side);
  const fairAmerican = decimalToAmerican(1 / side.true_prob);

  const rawKellyStake = Math.max(0, side.base_kelly_fraction * kellyMultiplier * bankroll);
  const stealthKellyStake = calculateStealthStake(rawKellyStake);

  const metric =
    activeLens === "bonus_bet"
      ? {
          label: "Retention",
          value: `${(retention * 100).toFixed(1)}%`,
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
    if (side.ev_percentage < -2) metricColorClass = "text-[#B85C38]";
    else if (side.ev_percentage >= 0) metricColorClass = "text-[#4A7C59]";
  }

  return (
    <Card
      className={cn("card-hover transition-shadow hover:shadow-soft", !tutorialMode && "cursor-pointer")}
      onClick={!tutorialMode ? () => onLogBet(side) : undefined}
    >
      <CardContent className="px-3 py-2.5">
        {/* Row 0: badges left, metric right */}
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

        {/* Row 1: team + suggested stake */}
        <div className="flex items-start justify-between gap-2">
          <p className="line-clamp-1 text-sm font-semibold leading-snug">{cardTitle}</p>
          {activeLens === "standard" && (
            <p className="shrink-0 whitespace-nowrap text-[10px] text-muted-foreground">
              Suggested: <span className="font-mono text-foreground">{formatCurrency(stealthKellyStake)}</span>
            </p>
          )}
        </div>

        {/* Row 2: matchup + game time */}
        <p className="mt-0.5 text-xs text-muted-foreground">
          {buildEventNicknameLabel(side.event)} • {formatGameTime(side.commence_time)}
        </p>

        {/* Row 3: book odds + fair odds + duplicate context */}
        <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[11px] font-medium">
          {activeLens === "profit_boost" ? (
            <span className="text-muted-foreground">
              Book <span className="text-muted-foreground/70 line-through">{formatOdds(side.book_odds)}</span>{" "}
              <span className="text-foreground">
                {formatOdds(decimalToAmerican(boostedDecimalOdds(side, boostPercent)))}
              </span>
            </span>
          ) : (
            <span className="text-muted-foreground">
              Book <span className="text-foreground">{formatOdds(side.book_odds)}</span>
            </span>
          )}

          <span className="text-muted-foreground">
            Fair <span className="text-foreground">{formatOdds(fairAmerican)}</span>
          </span>

          {duplicateState === "better_now" && side.best_logged_odds_american != null && (
            <span className="text-[11px] text-profit">
              Logged at {formatOdds(side.best_logged_odds_american)} · now{" "}
              {formatOdds(side.current_odds_american ?? side.book_odds)}
            </span>
          )}
        </div>

        {/* Row 4: action row */}
        {tutorialMode ? (
          <div className="mt-1.5 border-t border-border/60 pt-1.5">
            <p className="mb-2 rounded border border-sky-300/45 bg-sky-100/45 px-2 py-1.5 text-[11px] text-sky-900">
              Simulated tutorial line. Normally you would place this at {bookAbbrev(side.sportsbook)} first. For now, just open a practice log.
            </p>
            <Button
              type="button"
              className="h-8 w-full text-xs font-semibold"
              data-onboarding-target={ONBOARDING_HIGHLIGHT_TARGETS.MARKETS_PRACTICE_PLACE}
              onClick={(event) => {
                event.stopPropagation();
                onLogBet(side);
              }}
            >
              Practice Log Ticket
              <ChevronRight className="ml-1 h-3 w-3" />
            </Button>
          </div>
        ) : actionModel.primary.kind === "open" && actionModel.primary.href ? (
          <div className="mt-1.5 flex items-center gap-1.5 border-t border-border/60 pt-1.5">
            <Button
              asChild
              className={cn(
                "h-8 text-xs font-medium active:scale-[0.98] transition-transform",
                canAddToCart ? "flex-[0.9]" : "flex-1"
              )}
              onClick={(event) => event.stopPropagation()}
            >
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
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded border text-xs transition-all active:scale-90",
                  isInCart
                    ? "border-primary/30 bg-primary/15 text-primary"
                    : "border-border bg-muted/40 text-muted-foreground hover:border-primary/30 hover:bg-primary/10 hover:text-primary"
                )}
                onClick={(event) => {
                  event.stopPropagation();
                  if (isInCart) removeCartLeg(legId);
                  else onAddToCart(side);
                }}
              >
                {isInCart ? <Check className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
              </button>
            )}

            <button
              type="button"
              className="ml-auto flex shrink-0 items-center whitespace-nowrap text-xs text-muted-foreground transition-colors hover:text-foreground active:scale-95"
              onClick={(event) => {
                event.stopPropagation();
                onLogBet(side);
              }}
            >
              Review
              <ChevronRight className="ml-0.5 h-3 w-3" />
            </button>
          </div>
        ) : (
          <div className="mt-1.5 flex items-center gap-1.5 border-t border-border/60 pt-1.5">
            <Button
              type="button"
              className={cn(
                "h-8 text-xs font-medium active:scale-[0.98] transition-transform",
                canAddToCart ? "flex-[0.9]" : "flex-1"
              )}
              onClick={(event) => {
                event.stopPropagation();
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
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded border text-xs transition-all active:scale-90",
                  isInCart
                    ? "border-primary/30 bg-primary/15 text-primary"
                    : "border-border bg-muted/40 text-muted-foreground hover:border-primary/30 hover:bg-primary/10 hover:text-primary"
                )}
                onClick={(event) => {
                  event.stopPropagation();
                  if (isInCart) removeCartLeg(legId);
                  else onAddToCart(side);
                }}
              >
                {isInCart ? <Check className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
              </button>
            )}

            <button
              type="button"
              className="ml-auto flex shrink-0 items-center whitespace-nowrap text-xs text-muted-foreground transition-colors hover:text-foreground active:scale-95"
              onClick={(event) => {
                event.stopPropagation();
                onLogBet(side);
              }}
            >
              Review
              <ChevronRight className="ml-0.5 h-3 w-3" />
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
