import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { PickEmBoardCard as PickEmBoardCardType, PickEmSlipPick } from "../pickem-board";

interface PickEmBoardCardProps {
  card: PickEmBoardCardType;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
  isAdded: boolean;
  onAddToSlip: (pick: PickEmSlipPick) => void;
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

function formatMarketLabel(value: string) {
  return value.replaceAll("_", " ").replace(/^player\s+/i, "");
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

function formatLineValue(value: number): string {
  if (Number.isInteger(value)) {
    return `${value}`;
  }
  return `${Number.parseFloat(value.toFixed(2))}`;
}

export function PickEmBoardCard({
  card,
  bookColors,
  sportDisplayMap,
  isAdded,
  onAddToSlip,
}: PickEmBoardCardProps) {
  const winningSide = card.consensus_side === "over" ? "Over" : "Under";
  const winningProbability =
    card.consensus_side === "over" ? card.consensus_over_prob : card.consensus_under_prob;
  const marketLabel = formatMarketLabel(card.market);
  const overIsWinner = card.consensus_over_prob >= card.consensus_under_prob;
  const underIsWinner = card.consensus_under_prob > card.consensus_over_prob;

  const handleAddToSlip = () => {
    onAddToSlip({
      comparisonKey: card.comparison_key,
      playerName: card.player_name,
      market: card.market,
      marketKey: card.market_key,
      lineValue: card.line_value,
      selectedSide: card.consensus_side,
      selectedPercentage: winningProbability,
      event: card.event,
    });
  };

  return (
    <Card className="card-hover">
      <CardContent className="space-y-2.5 p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-foreground px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-background">
                Pick&apos;em
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {sportDisplayMap[card.sport] || card.sport}
              </span>
            </div>

            <p className="text-sm font-semibold">{card.player_name}</p>
            <p className="line-clamp-1 text-xs text-muted-foreground">
              {card.event}
              <span className="ml-2 whitespace-nowrap">&bull; {formatGameTime(card.commence_time)}</span>
            </p>
            <p className="text-[11px] text-muted-foreground">
              Based on {card.exact_line_bookmaker_count} book{card.exact_line_bookmaker_count === 1 ? "" : "s"}, the
              {" "}market gives the {winningSide} a {percentLabel(winningProbability)} chance.
            </p>
          </div>

          <div className="shrink-0 rounded-lg border border-[#E9D7B9] bg-[#FCF7EC] px-3 py-1.5 text-left sm:min-w-[118px] sm:text-right">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8B7355]">{marketLabel}</p>
            <p className="mt-0.5 text-xl font-mono font-bold leading-none text-[#5C4D2E]">
              {formatLineValue(card.line_value)}
            </p>
            <p className="mt-1 text-[10px] text-[#8B7355]">
              {card.exact_line_bookmaker_count} book{card.exact_line_bookmaker_count === 1 ? "" : "s"} match
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div
            className={`flex items-center justify-between rounded-lg bg-background/80 px-3 py-2 ${
              overIsWinner
                ? "border border-[#B7D1C2]"
                : "border border-border/60"
            }`}
          >
            <span className={`text-xs font-medium uppercase tracking-wide ${overIsWinner ? "text-[#2E5D39]" : "text-muted-foreground"}`}>
              Over
            </span>
            <span className={`text-sm font-semibold ${overIsWinner ? "text-[#2E5D39]" : "text-muted-foreground"}`}>
              {percentLabel(card.consensus_over_prob)}
            </span>
          </div>

          <div
            className={`flex items-center justify-between rounded-lg bg-background/80 px-3 py-2 ${
              underIsWinner
                ? "border border-[#B7D1C2]"
                : "border border-border/60"
            }`}
          >
            <span className={`text-xs font-medium uppercase tracking-wide ${underIsWinner ? "text-[#2E5D39]" : "text-muted-foreground"}`}>
              Under
            </span>
            <span className={`text-sm font-semibold ${underIsWinner ? "text-[#2E5D39]" : "text-muted-foreground"}`}>
              {percentLabel(card.consensus_under_prob)}
            </span>
          </div>
        </div>

        <div className="space-y-2 border-t border-border/60 pt-2">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            {card.exact_line_bookmakers.map((book) => (
              <span
                key={book}
                className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white ${bookColors[book] || "bg-foreground"}`}
              >
                {bookAbbrev(book)}
              </span>
            ))}
          </div>

          <Button
            type="button"
            variant={isAdded ? "outline" : "default"}
            className={isAdded ? "h-10 w-full border-[#B7D1C2] bg-[#F3F7F5] text-[#2E5D39] hover:bg-[#F3F7F5]" : "h-10 w-full"}
            disabled={isAdded}
            onClick={handleAddToSlip}
          >
            {isAdded ? "✓ Added" : "Add to Slip"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
