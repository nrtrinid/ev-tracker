import { ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { PrizePicksComparisonCard as PrizePicksComparisonCardType } from "@/lib/types";
import { formatOdds } from "@/lib/utils";
import { buildEventNicknameLabel } from "./event-nickname-label";

interface PrizePicksComparisonCardProps {
  card: PrizePicksComparisonCardType;
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

function bookAbbrev(name: string | null | undefined): string {
  const map: Record<string, string> = {
    DraftKings: "DK",
    FanDuel: "FD",
    BetMGM: "MGM",
    Caesars: "CZR",
    Bovada: "BVD",
    "BetOnline.ag": "BOL",
  };
  const label = String(name || "").trim();
  return map[label] || label || "Book";
}

function percentLabel(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function PrizePicksComparisonCard({
  card,
  bookColors,
  sportDisplayMap,
}: PrizePicksComparisonCardProps) {
  const lean = card.consensus_side === "over" ? "Over" : "Under";
  const leanProbability =
    card.consensus_side === "over" ? card.consensus_over_prob : card.consensus_under_prob;
  const confidenceDisplay = formatConfidenceLabel(card.confidence_label);

  return (
    <Card className="card-hover">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-foreground px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-background">
                PP
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {sportDisplayMap[card.sport] || card.sport}
              </span>
              <span className="rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {formatMarketLabel(card.market)}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold">{card.player_name}</p>
              <span className="rounded border border-border/70 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                PrizePicks {card.prizepicks_line}
              </span>
            </div>

            <p className="line-clamp-1 text-xs text-muted-foreground">{buildEventNicknameLabel(card.event)}</p>
            <p className="text-[11px] text-muted-foreground">
              Sportsbook consensus leans {lean} at {percentLabel(leanProbability)} on this exact line.
            </p>
          </div>

          <div className="shrink-0 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-left sm:min-w-[112px] sm:text-right">
            <p className="text-sm font-semibold">{confidenceDisplay}</p>
            <p className="text-[10px] text-muted-foreground">
              {card.exact_line_bookmaker_count} book{card.exact_line_bookmaker_count === 1 ? "" : "s"}
            </p>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-border/60 bg-background/80 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Consensus Over</p>
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{percentLabel(card.consensus_over_prob)}</span>
              <span className="text-xs text-muted-foreground">
                {card.best_over_sportsbook ? `${bookAbbrev(card.best_over_sportsbook)} ${formatOdds(card.best_over_odds ?? 0)}` : "No offer"}
              </span>
            </div>
          </div>

          <div className="rounded-lg border border-border/60 bg-background/80 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Consensus Under</p>
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{percentLabel(card.consensus_under_prob)}</span>
              <span className="text-xs text-muted-foreground">
                {card.best_under_sportsbook ? `${bookAbbrev(card.best_under_sportsbook)} ${formatOdds(card.best_under_odds ?? 0)}` : "No offer"}
              </span>
            </div>
          </div>
        </div>

        <div className="space-y-2 border-t border-border/60 pt-2">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span>Exact-line support:</span>
            {card.exact_line_bookmakers.map((book) => (
              <span
                key={book}
                className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white ${bookColors[book] || "bg-foreground"}`}
              >
                {bookAbbrev(book)}
              </span>
            ))}
            <span>{formatGameTime(card.commence_time)}</span>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row">
            {card.best_over_deeplink_url ? (
              <Button asChild variant="outline" className="h-10 flex-1 text-xs font-medium">
                <a href={card.best_over_deeplink_url} target="_blank" rel="noopener noreferrer">
                  Open Over at {bookAbbrev(card.best_over_sportsbook)}
                  <ExternalLink className="ml-1 h-3.5 w-3.5" />
                </a>
              </Button>
            ) : (
              <div className="flex h-10 flex-1 items-center justify-center rounded-md border border-border/60 px-3 text-xs text-muted-foreground">
                Best Over: {card.best_over_sportsbook ? `${bookAbbrev(card.best_over_sportsbook)} ${formatOdds(card.best_over_odds ?? 0)}` : "Unavailable"}
              </div>
            )}

            {card.best_under_deeplink_url ? (
              <Button asChild variant="outline" className="h-10 flex-1 text-xs font-medium">
                <a href={card.best_under_deeplink_url} target="_blank" rel="noopener noreferrer">
                  Open Under at {bookAbbrev(card.best_under_sportsbook)}
                  <ExternalLink className="ml-1 h-3.5 w-3.5" />
                </a>
              </Button>
            ) : (
              <div className="flex h-10 flex-1 items-center justify-center rounded-md border border-border/60 px-3 text-xs text-muted-foreground">
                Best Under: {card.best_under_sportsbook ? `${bookAbbrev(card.best_under_sportsbook)} ${formatOdds(card.best_under_odds ?? 0)}` : "Unavailable"}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
