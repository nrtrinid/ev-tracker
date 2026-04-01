import { Button } from "@/components/ui/button";
import type { PickEmBoardCard as PickEmBoardCardType } from "../pickem-board";

import { PickEmBoardCard } from "./PickEmBoardCard";

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
  return (
    <>
      {cards.map((card) => (
        <PickEmBoardCard
          key={card.comparison_key}
          card={card}
          bookColors={bookColors}
          sportDisplayMap={sportDisplayMap}
          isAdded={addedComparisonKeys.includes(card.comparison_key)}
          onAddToSlip={onAddToSlip}
        />
      ))}

      {canLoadMore && (
        <Button type="button" variant="secondary" className="w-full" onClick={onLoadMore}>
          Load more
        </Button>
      )}
    </>
  );
}
