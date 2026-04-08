import { Check, ChevronRight, ExternalLink, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { PlayerPropMarketSide } from "@/lib/types";
import { calculateStealthStake, cn, formatCurrency, formatOdds } from "@/lib/utils";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import {
  calculateLensBoostedEV,
  calculateLensQualifierHold,
  calculateLensRetention,
} from "@/app/scanner/scanner-lenses";
import { buildScannerActionModel } from "../scanner-ui-model";
import { getStandardEdgeColorClass } from "./scanner-card-colors";

interface PlayerPropCardProps {
  side: PlayerPropMarketSide & { _retention?: number; _boostedEV?: number; _qualifierHold?: number };
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  boostPercent: number;
  kellyMultiplier: number;
  bankroll: number;
  onLogBet: (side: PlayerPropMarketSide) => void;
  onAddToCart: (side: PlayerPropMarketSide) => void;
  onStartPlaceFlow: (side: PlayerPropMarketSide) => void;
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
    Bovada: "BVD",
    "BetOnline.ag": "BOL",
  };
  return map[name] || name;
}

function getDuplicateBadge(duplicateState: PlayerPropMarketSide["scanner_duplicate_state"]) {
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
  if (!key) return "Prop";
  return key.replace(/^player_/, "").replaceAll("_", " ").toUpperCase();
}

export function PlayerPropCard({
  side,
  activeLens,
  boostPercent,
  kellyMultiplier,
  bankroll,
  onLogBet,
  onAddToCart,
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: PlayerPropCardProps) {
  const { cart, isHydrated, removeCartLeg } = useBettingPlatformStore();

  const actionModel = buildScannerActionModel({
    sportsbook: side.sportsbook,
    sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
    sportsbookDeeplinkLevel: side.sportsbook_deeplink_level,
  });

  const duplicateState = side.scanner_duplicate_state ?? "new";
  const duplicateBadge = getDuplicateBadge(duplicateState);
  const referenceBookCount = side.reference_bookmaker_count ?? side.reference_bookmakers?.length ?? 0;

  const boostedEV = side._boostedEV ?? calculateLensBoostedEV(side, boostPercent);
  const retention = side._retention ?? calculateLensRetention(side);
  const hold = side._qualifierHold ?? calculateLensQualifierHold(side);
  const rawKellyStake = Math.max(0, side.base_kelly_fraction * kellyMultiplier * bankroll);
  const stealthKellyStake = calculateStealthStake(rawKellyStake);

  const metric =
    activeLens === "bonus_bet"
      ? { label: "Retention", value: `${(retention * 100).toFixed(1)}%` }
      : activeLens === "profit_boost"
        ? { label: "Boost Edge", value: `${boostedEV >= 0 ? "+" : ""}${boostedEV.toFixed(1)}%` }
        : activeLens === "qualifier"
          ? { label: "Hold", value: `${hold.toFixed(1)}%` }
          : { label: "Edge", value: `${side.ev_percentage >= 0 ? "+" : ""}${side.ev_percentage.toFixed(1)}%` };

  let metricColorClass = "text-foreground";
  if (activeLens === "standard") {
    metricColorClass = getStandardEdgeColorClass(side.ev_percentage);
  } else if (activeLens === "profit_boost") {
    metricColorClass = boostedEV > 0 ? "text-primary" : "text-muted-foreground";
  } else if (activeLens === "bonus_bet") {
    metricColorClass = "text-[#0EA5A4]";
  } else if (activeLens === "qualifier") {
    metricColorClass = hold <= 3 ? "text-profit" : hold <= 6 ? "text-foreground" : "text-muted-foreground";
  }

  const legId = `${side.surface}:${side.selection_key}:${side.sportsbook}`;
  const isInCart = isHydrated && cart.some((leg) => leg.id === legId);

  return (
    <Card
      className="card-hover cursor-pointer transition-shadow hover:shadow-soft"
      onClick={() => onLogBet(side)}
    >
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
              {formatPropMarketLabel(side.market_key)}
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

        {/* Row 1: player name + suggested stake */}
        <div className="flex items-start justify-between gap-2">
          <p className="line-clamp-1 text-sm font-semibold leading-snug">{side.display_name}</p>
          {activeLens === "standard" && (
            <p className="shrink-0 whitespace-nowrap text-[10px] text-muted-foreground">
              Suggested: <span className="font-mono text-foreground">{formatCurrency(stealthKellyStake)}</span>
            </p>
          )}
        </div>

        {/* Row 2: matchup + game time */}
        <p className="mt-0.5 text-xs text-muted-foreground">
          {side.event} • {formatGameTime(side.commence_time)}
        </p>

        {/* Row 3: book odds, fair odds, trust signal */}
        <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[11px] font-medium">
          <span className="text-muted-foreground">
            Book <span className="text-foreground">{formatOdds(side.book_odds)}</span>
          </span>
          <span className="text-muted-foreground">
            Fair <span className="text-foreground">{formatOdds(side.reference_odds)}</span>
          </span>
          <span className="text-muted-foreground">· {referenceBookCount} books</span>
          {duplicateState === "better_now" && side.best_logged_odds_american != null && (
            <span className="text-[11px] text-profit">
              Logged at {formatOdds(side.best_logged_odds_american)} · now{" "}
              {formatOdds(side.current_odds_american ?? side.book_odds)}
            </span>
          )}
        </div>

        {/* Row 4: action row — Place + toggle grouped left, Review > pinned right */}
        {actionModel.primary.kind === "open" && actionModel.primary.href ? (
          <div className="mt-1.5 flex items-center gap-1.5 border-t border-border/60 pt-1.5">
            <Button
              asChild
              className="h-8 flex-[0.9] text-xs font-medium active:scale-[0.98] transition-transform"
              onClick={(e) => e.stopPropagation()}
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
            <button
              type="button"
              aria-label={isInCart ? "Remove from cart" : "Add to cart"}
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded border text-xs transition-all active:scale-90",
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
            <button
              type="button"
              className="ml-auto flex shrink-0 items-center whitespace-nowrap text-xs text-muted-foreground transition-colors hover:text-foreground active:scale-95"
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
              className="h-8 flex-[0.9] text-xs font-medium active:scale-[0.98] transition-transform"
              onClick={(e) => {
                e.stopPropagation();
                onLogBet(side);
              }}
            >
              {actionModel.primary.label}
              <ChevronRight className="ml-1 h-3 w-3" />
            </Button>
            <button
              type="button"
              aria-label={isInCart ? "Remove from cart" : "Add to cart"}
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded border text-xs transition-all active:scale-90",
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
            <button
              type="button"
              className="ml-auto flex shrink-0 items-center whitespace-nowrap text-xs text-muted-foreground transition-colors hover:text-foreground active:scale-95"
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
