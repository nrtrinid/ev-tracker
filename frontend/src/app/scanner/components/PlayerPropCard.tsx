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

function decimalToAmerican(decimal: number): number {
  if (decimal >= 2.0) return Math.round((decimal - 1) * 100);
  return Math.round(-100 / (decimal - 1));
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
  const fairAmerican = decimalToAmerican(1 / side.true_prob);
  const fairPct = (side.true_prob * 100).toFixed(1);
  const duplicateState = side.scanner_duplicate_state ?? "new";

  return (
    <Card className="card-hover overflow-hidden border-border/80">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white",
                  bookColors[side.sportsbook] || "bg-foreground"
                )}
              >
                {side.sportsbook}
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {sportDisplayMap[side.sport] || side.sport}
              </span>
              <span className="rounded bg-[#EDE4D0] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[#6D5431]">
                {side.market.replaceAll("_", " ")}
              </span>
              {duplicateState !== "new" && (
                <span className="rounded border border-[#B85C38]/35 bg-[#B85C38]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#8B3D20]">
                  Already Logged
                </span>
              )}
            </div>

            <div className="space-y-1">
              <p className="text-sm font-semibold">{side.display_name}</p>
              <p className="text-xs text-muted-foreground">
                {side.player_name}
                {side.team ? ` • ${side.team}` : ""}
                {side.opponent ? ` vs ${side.opponent}` : ""}
              </p>
              <p className="text-xs text-muted-foreground">{side.event}</p>
            </div>
          </div>

          <div className="text-right">
            <p className="text-lg font-mono font-bold text-[#3B6C8E]">
              {side.ev_percentage >= 0 ? "+" : ""}
              {side.ev_percentage.toFixed(1)}%
            </p>
            <p className="text-[10px] text-muted-foreground">EV</p>
          </div>
        </div>

        <div className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-xs">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono text-foreground">Book: {formatOdds(side.book_odds)}</span>
            <span className="font-mono text-muted-foreground">
              Fair: {formatOdds(fairAmerican)} ({fairPct}%)
            </span>
            {side.line_value != null && (
              <span className="text-muted-foreground">Line: {side.line_value}</span>
            )}
            <span className="text-muted-foreground">{formatGameTime(side.commence_time)}</span>
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
                Log Bet
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        ) : (
          <div className="border-t border-border/60 pt-2">
            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={() => onAddToCart(side)}
                className="inline-flex h-9 flex-1 items-center justify-center gap-1 rounded-lg border border-[#C4A35A]/35 bg-[#C4A35A]/10 px-3 text-xs font-semibold text-[#5C4D2E] transition-colors hover:bg-[#C4A35A]/20"
              >
                Add to Cart
              </button>
              <button
                type="button"
                onClick={() => onLogBet(side)}
                className="inline-flex h-9 flex-1 items-center justify-center gap-1 rounded-lg bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
              >
                Log Bet
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
