import { Button } from "@/components/ui/button";
import type { PlayerPropMarketSide } from "@/lib/types";

import { PlayerPropCard } from "./PlayerPropCard";

function formatMarketLabel(value: string) {
  return value.replaceAll("_", " ");
}

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
  const groupedResults = results.reduce<Record<string, PlayerPropListProps["results"]>>((groups, side) => {
    const key = side.market_key;
    groups[key] = groups[key] ? [...groups[key], side] : [side];
    return groups;
  }, {});

  return (
    <>
      {Object.entries(groupedResults).map(([marketKey, marketResults]) => (
        <section key={marketKey} className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              {formatMarketLabel(marketKey)}
            </h3>
            <span className="text-[10px] text-muted-foreground">
              {marketResults.length} {marketResults.length === 1 ? "prop" : "props"}
            </span>
          </div>

          {marketResults.map((side) => (
            <PlayerPropCard
              key={`${side.selection_key}-${side.sportsbook}`}
              side={side}
              onLogBet={onLogBet}
              onAddToCart={onAddToCart}
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
