import { Button } from "@/components/ui/button";
import type { PickEmBoardCard as PickEmBoardCardType } from "../pickem-board";

import { PickEmBoardCard } from "./PickEmBoardCard";

interface PickEmBoardListProps {
  cards: PickEmBoardCardType[];
  canLoadMore: boolean;
  isLoadingMore?: boolean;
  onLoadMore: () => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
  addedComparisonKeys: string[];
  onAddToSlip: (card: PickEmBoardCardType) => void;
}

export function PickEmBoardList({
  cards,
  canLoadMore,
  isLoadingMore = false,
  onLoadMore,
  bookColors,
  sportDisplayMap,
  addedComparisonKeys,
  onAddToSlip,
}: PickEmBoardListProps) {
  return (
    <>
      <div className="space-y-2">
        {cards.map((card, idx) => (
          <div
            key={card.comparison_key}
            className="animate-slide-up"
            style={{ animationDelay: `${idx * 40}ms` }}
          >
            <PickEmBoardCard
              card={card}
              bookColors={bookColors}
              sportDisplayMap={sportDisplayMap}
              isAdded={addedComparisonKeys.includes(card.comparison_key)}
              onAddToSlip={onAddToSlip}
            />
          </div>
        ))}
      </div>

      {canLoadMore && (
        <Button
          type="button"
          variant="secondary"
          className="w-full active:scale-[0.98] transition-transform"
          onClick={onLoadMore}
          disabled={isLoadingMore}
        >
          {isLoadingMore ? "Loading more..." : "Load more"}
        </Button>
      )}
    </>
  );
}
