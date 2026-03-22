import { ChevronRight, ExternalLink } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { PlayerPropMarketSide } from "@/lib/types";
import { cn, formatOdds } from "@/lib/utils";
import { buildScannerActionModel } from "../scanner-ui-model";

interface PlayerPropCardProps {
  side: PlayerPropMarketSide & { _retention?: number; _boostedEV?: number };
  onLogBet: (side: PlayerPropMarketSide) => void;
  onAddToCart: (side: PlayerPropMarketSide) => void;
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

export function PlayerPropCard({
  side,
  onLogBet,
  onAddToCart,
  bookColors,
  sportDisplayMap,
}: PlayerPropCardProps) {
  const actionModel = buildScannerActionModel({
    sportsbook: side.sportsbook,
    sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
  });
  const fairPct = (side.true_prob * 100).toFixed(1);
  const duplicateState = side.scanner_duplicate_state ?? "new";
  const referenceBookCount = side.reference_bookmaker_count ?? side.reference_bookmakers.length;
  const confidenceLabel = side.confidence_label ?? (referenceBookCount >= 2 ? "solid" : "thin");
  const confidenceDisplay = formatConfidenceLabel(confidenceLabel);
  const evColorClass =
    side.ev_percentage > 0
      ? "text-green-600"
      : side.ev_percentage < 0
        ? "text-red-500"
        : "text-[#3B6C8E]";

  return (
    <Card className="card-hover">
      <CardContent className="space-y-2.5 p-4">
        <div className="flex items-start justify-between gap-3">
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
              {duplicateState !== "new" && (
                <span
                  className="rounded border border-[#B85C38]/35 bg-[#B85C38]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#8B3D20]"
                >
                  Already Logged
                </span>
              )}
              {duplicateState === "better_now" && (
                <span className="rounded border border-[#4A7C59]/35 bg-[#4A7C59]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#2E5D39]">
                  Better Now
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
                <span className="font-mono font-medium">
                  <span className="text-foreground">{formatOdds(side.book_odds)}</span>
                  <span className="mx-1 text-muted-foreground">|</span>
                  <span className="text-muted-foreground">
                    Fair: {formatOdds(side.reference_odds)} ({fairPct}%)
                  </span>
                  <span className="mx-1 text-muted-foreground">|</span>
                  <span className="text-muted-foreground">
                    Consensus: {confidenceDisplay} ({referenceBookCount})
                  </span>
                </span>

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

          <div className="shrink-0">
            <div className="text-right">
              <p className={cn("text-lg font-mono font-bold leading-tight", evColorClass)}>
                {side.ev_percentage >= 0 ? "+" : ""}
                {side.ev_percentage.toFixed(1)}%
              </p>
              <p className="text-[10px] text-muted-foreground">EV</p>
            </div>
          </div>
        </div>

        {actionModel.primary.kind === "open" && actionModel.primary.href ? (
          <div className="space-y-1.5 border-t border-border/60 pt-2">
            <div className="flex flex-col gap-2 sm:flex-row">
              <a
                href={actionModel.primary.href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-9 flex-1 items-center justify-center gap-1 rounded-lg bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
              >
                {actionModel.primary.label}
                <ExternalLink className="h-3 w-3" />
              </a>
              <button
                type="button"
                onClick={() => onAddToCart(side)}
                className="inline-flex h-9 items-center justify-center gap-1 rounded-lg border border-[#C4A35A]/35 bg-[#C4A35A]/10 px-3 text-xs font-medium text-[#5C4D2E] transition-colors hover:bg-[#C4A35A]/20"
              >
                Add to Cart
              </button>
              <button
                type="button"
                onClick={() => onLogBet(side)}
                className="inline-flex h-9 items-center justify-center gap-1 rounded-lg border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                {actionModel.secondary?.label ?? "Log Bet"}
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
            {actionModel.trustHint && (
              <p className="text-[10px] text-muted-foreground">{actionModel.trustHint}</p>
            )}
          </div>
        ) : (
          <div className="border-t border-border/60 pt-2">
            <button
              type="button"
              onClick={() => onAddToCart(side)}
              className="inline-flex h-9 w-full items-center justify-center gap-1 rounded-lg border border-[#C4A35A]/35 bg-[#C4A35A]/10 px-3 text-xs font-semibold text-[#5C4D2E] transition-colors hover:bg-[#C4A35A]/20"
            >
              Add to Cart
            </button>
            <button
              type="button"
              onClick={() => onLogBet(side)}
              className="mt-2 inline-flex h-9 w-full items-center justify-center gap-1 rounded-lg bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
            >
              Log Bet
              <ChevronRight className="h-3 w-3" />
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
