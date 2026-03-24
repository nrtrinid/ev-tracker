import { Button } from "@/components/ui/button";
import type { PrizePicksComparisonCard as PrizePicksComparisonCardType } from "@/lib/types";

import { PrizePicksComparisonCard } from "./PrizePicksComparisonCard";

function formatMarketLabel(value: string) {
  return value.replaceAll("_", " ");
}

interface PrizePicksComparisonListProps {
  cards: PrizePicksComparisonCardType[];
  canLoadMore: boolean;
  onLoadMore: () => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function PrizePicksComparisonList({
  cards,
  canLoadMore,
  onLoadMore,
  bookColors,
  sportDisplayMap,
}: PrizePicksComparisonListProps) {
  const groupedCards = cards.reduce<Record<string, PrizePicksComparisonCardType[]>>((groups, card) => {
    const key = card.market_key;
    groups[key] = groups[key] ? [...groups[key], card] : [card];
    return groups;
  }, {});

  return (
    <>
      {Object.entries(groupedCards).map(([marketKey, marketCards]) => (
        <section key={marketKey} className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              {formatMarketLabel(marketKey)}
            </h3>
            <span className="text-[10px] text-muted-foreground">
              {marketCards.length} {marketCards.length === 1 ? "comparison" : "comparisons"}
            </span>
          </div>

          {marketCards.map((card) => (
            <PrizePicksComparisonCard
              key={card.comparison_key}
              card={card}
              bookColors={bookColors}
              sportDisplayMap={sportDisplayMap}
            />
          ))}
        </section>
      ))}

      {canLoadMore && (
        <Button type="button" variant="secondary" className="w-full" onClick={onLoadMore}>
          Load more
        </Button>
      )}
    </>
  );
}
