import { Button } from "@/components/ui/button";
import type { PickEmBoardCard as PickEmBoardCardType } from "../pickem-board";

import { PickEmBoardCard } from "./PickEmBoardCard";

function formatMarketLabel(value: string) {
  return value.replaceAll("_", " ");
}

interface PickEmBoardListProps {
  cards: PickEmBoardCardType[];
  canLoadMore: boolean;
  onLoadMore: () => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
  addedComparisonKeys: string[];
  onAddToSlip: (card: PickEmBoardCardType) => void;
}

export function PickEmBoardList({
  cards,
  canLoadMore,
  onLoadMore,
  bookColors,
  sportDisplayMap,
  addedComparisonKeys,
  onAddToSlip,
}: PickEmBoardListProps) {
  const groupedCards = cards.reduce<Record<string, PickEmBoardCardType[]>>((groups, card) => {
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
              {marketCards.length} {marketCards.length === 1 ? "line" : "lines"}
            </span>
          </div>

          {marketCards.map((card) => (
            <PickEmBoardCard
              key={card.comparison_key}
              card={card}
              bookColors={bookColors}
              sportDisplayMap={sportDisplayMap}
              isAdded={addedComparisonKeys.includes(card.comparison_key)}
              onAddToSlip={onAddToSlip}
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
