import { ChevronRight, ExternalLink, Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { PlayerPropMarketSide } from "@/lib/types";
import { calculateStealthStake, cn, formatCurrency, formatOdds } from "@/lib/utils";
import { buildScannerActionModel } from "../scanner-ui-model";
import { getStandardEdgeColorClass } from "./scanner-card-colors";

interface PlayerPropCardProps {
  side: PlayerPropMarketSide & { _retention?: number; _boostedEV?: number };
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

function formatMarketLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function formatConfidenceLabel(label: string | null | undefined): string {
  const normalized = (label || "thin").trim().toLowerCase();
  return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : "Thin";
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

export function PlayerPropCard({
  side,
  kellyMultiplier,
  bankroll,
  onLogBet,
  onAddToCart,
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: PlayerPropCardProps) {
  const actionModel = buildScannerActionModel({
    sportsbook: side.sportsbook,
    sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
    sportsbookDeeplinkLevel: side.sportsbook_deeplink_level,
  });
  const duplicateState = side.scanner_duplicate_state ?? "new";
  const duplicateBadge = getDuplicateBadge(duplicateState);
  const referenceBookCount = side.reference_bookmaker_count ?? side.reference_bookmakers.length;
  const confidenceLabel = side.confidence_label ?? (referenceBookCount >= 2 ? "solid" : "thin");
  const confidenceDisplay = formatConfidenceLabel(confidenceLabel);
  const rawKellyStake = Math.max(0, side.base_kelly_fraction * kellyMultiplier * bankroll);
  const stealthKellyStake = calculateStealthStake(rawKellyStake);
  const edgeColorClass = getStandardEdgeColorClass(side.ev_percentage);

  return (
    <Card className="card-hover">
      <CardContent className="space-y-2.5 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
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
              {duplicateBadge && (
                <span className={duplicateBadge.className}>
                  {duplicateBadge.label}
                </span>
              )}
            </div>

            <div className="mb-2 flex items-center gap-2">
              <p className="line-clamp-2 text-sm font-semibold">{side.display_name}</p>
              <span className="shrink-0 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {formatMarketLabel(side.market)}
              </span>
            </div>

            <p className="line-clamp-1 mt-0.5 text-xs text-muted-foreground">{side.event}</p>

            <div className="mt-2 flex flex-col gap-1 text-xs">
              <div className="flex flex-wrap items-center gap-3">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono font-medium">
                  <span className="text-[11px] text-muted-foreground">Book</span>
                  <span className="text-foreground">{formatOdds(side.book_odds)}</span>
                  <span className="text-[11px] text-muted-foreground">
                    Fair {formatOdds(side.reference_odds)}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    Backed by {referenceBookCount} books
                  </span>
                </span>

                {duplicateState === "better_now" && side.best_logged_odds_american != null && (
                  <span className="text-[11px] text-profit">
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
              <p className={cn("text-lg font-mono font-bold leading-tight", edgeColorClass)}>
                {side.ev_percentage >= 0 ? "+" : ""}
                {side.ev_percentage.toFixed(1)}%
              </p>
              <p className="text-[10px] text-muted-foreground">Edge</p>
              </div>
              <div className="sm:mt-0.5">
                <p className="text-[10px] text-muted-foreground">
                  Confidence: {confidenceDisplay}
                </p>
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
              </div>
            </div>
          </div>
        </div>

        {actionModel.primary.kind === "open" && actionModel.primary.href ? (
          <div className="space-y-2 border-t border-border/60 pt-2">
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
