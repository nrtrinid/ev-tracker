import { Card, CardContent } from "@/components/ui/card";
import type { ScannerNullState } from "@/lib/scanner-contract";
import type { MarketSide, ScannerSurface } from "@/lib/types";
import { getScannerSurface } from "../scanner-surfaces";
import { PlayerPropList } from "./PlayerPropList";
import { StraightBetList } from "./StraightBetList";

interface ScannerResultsPaneProps {
  surface: ScannerSurface;
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  results: Array<MarketSide & { _retention?: number; _boostedEV?: number }>;
  sourceCount: number;
  filteredCount: number;
  nullState: ScannerNullState;
  activeResultFilterSummary: string;
  kellyMultiplier: number;
  bankroll: number;
  boostPercent: number;
  canLoadMore: boolean;
  onLoadMore: () => void;
  onLogBet: (side: MarketSide) => void;
  onAddToCart: (side: MarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function ScannerResultsPane({
  surface,
  activeLens,
  results,
  sourceCount,
  filteredCount,
  nullState,
  activeResultFilterSummary,
  kellyMultiplier,
  bankroll,
  boostPercent,
  canLoadMore,
  onLoadMore,
  onLogBet,
  onAddToCart,
  bookColors,
  sportDisplayMap,
}: ScannerResultsPaneProps) {
  const surfaceConfig = getScannerSurface(surface);
  const isPropsSurface = surface === "player_props";

  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
        {isPropsSurface
          ? `Showing ${results.length} of ${sourceCount} raw props`
          : `Showing ${results.length} of ${filteredCount} ${
              activeLens === "standard"
                ? "+EV Lines"
                : activeLens === "bonus_bet"
                  ? "Bonus Bet Targets"
                  : activeLens === "profit_boost"
                    ? "Boost Opportunities"
                    : "Qualifier Candidates"
            }`}
      </h2>

      {results.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center">
            <p className="text-sm text-muted-foreground">
              {nullState === "backend_empty"
                ? isPropsSurface
                  ? surfaceConfig.emptyLabel
                  : activeLens === "standard"
                    ? "No +EV lines right now. Check back when lines move."
                    : activeLens === "bonus_bet"
                      ? "No bonus bet targets above 60% retention."
                      : activeLens === "qualifier"
                        ? "No qualifier candidates in the target odds range right now."
                        : "No profitable boost opportunities at this percentage."
                : isPropsSurface
                  ? `${sourceCount} props scanned, 0 passed your current visibility filters.`
                  : "No results match your current filters."}
            </p>
            {nullState === "filter_empty" && (
              <p className="mt-2 text-xs text-muted-foreground">{activeResultFilterSummary}</p>
            )}
          </CardContent>
        </Card>
      ) : (
        isPropsSurface ? (
          <PlayerPropList
            results={results as Array<Extract<MarketSide, { surface: "player_props" }> & { _retention?: number; _boostedEV?: number }>}
            canLoadMore={canLoadMore}
            onLoadMore={onLoadMore}
            onLogBet={(side) => onLogBet(side)}
            onAddToCart={(side) => onAddToCart(side)}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
          />
        ) : (
          <StraightBetList
            activeLens={activeLens}
            results={results}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            boostPercent={boostPercent}
            canLoadMore={canLoadMore}
            onLoadMore={onLoadMore}
            onLogBet={onLogBet}
            onAddToCart={onAddToCart}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
          />
        )
      )}
    </div>
  );
}
