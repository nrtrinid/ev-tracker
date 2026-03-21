import { Button } from "@/components/ui/button";
import type { PlayerPropMarketSide } from "@/lib/types";

import { PlayerPropCard } from "./PlayerPropCard";

interface PlayerPropListProps {
  results: Array<PlayerPropMarketSide & { _retention?: number; _boostedEV?: number }>;
  canLoadMore: boolean;
  onLoadMore: () => void;
  onLogBet: (side: PlayerPropMarketSide) => void;
  onAddToCart: (side: PlayerPropMarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function PlayerPropList({
  results,
  canLoadMore,
  onLoadMore,
  onLogBet,
  onAddToCart,
  bookColors,
  sportDisplayMap,
}: PlayerPropListProps) {
  return (
    <>
      {results.map((side) => (
        <PlayerPropCard
          key={`${side.selection_key}-${side.sportsbook}`}
          side={side}
          onLogBet={onLogBet}
          onAddToCart={onAddToCart}
          bookColors={bookColors}
          sportDisplayMap={sportDisplayMap}
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
