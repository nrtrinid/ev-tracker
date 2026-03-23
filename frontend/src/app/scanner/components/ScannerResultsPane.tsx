import { Card, CardContent } from "@/components/ui/card";
import type { ScannerNullState } from "@/lib/scanner-contract";
import type { MarketSide, ScannerSurface } from "@/lib/types";
import { getScannerSurface } from "../scanner-surfaces";
import { PlayerPropList } from "./PlayerPropList";
import { StraightBetList } from "./StraightBetList";

interface ScannerResultsPaneProps {
  surface: ScannerSurface;
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  tutorialMode?: boolean;
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
  onStartPlaceFlow: (side: MarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function ScannerResultsPane({
  surface,
  activeLens,
  tutorialMode = false,
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
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: ScannerResultsPaneProps) {
  const surfaceConfig = getScannerSurface(surface);
  const isPropsSurface = surface === "player_props";

  return (
    <div className="space-y-2">
      {tutorialMode && (
        <p className="px-0.5 text-xs text-muted-foreground">
          Tutorial mode: the lines below are sample straight bets. Practice tickets stay local to this walkthrough and disappear when you finish it.
        </p>
      )}
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
        {isPropsSurface
          ? `Showing ${results.length} of ${sourceCount} raw props`
          : tutorialMode
            ? `Showing ${results.length} of ${filteredCount} Tutorial Lines`
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
                    ? "No clear starter plays right now. Check back when lines move."
                    : activeLens === "bonus_bet"
                      ? "No bonus-bet targets are standing out right now."
                      : activeLens === "qualifier"
                        ? "No clean qualifier candidates are in range right now."
                        : "No strong boost opportunities are standing out at this percentage."
                : isPropsSurface
                  ? `${sourceCount} props were scanned, but your current filters hid all of them.`
                  : "Your current filters are hiding all of the available plays."}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {nullState === "backend_empty"
                ? "Try a refresh later, or switch books if you want a different slate."
                : "Try Reset, loosen Safer Odds, or turn off Hide Logged to see more options."}
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
            onStartPlaceFlow={(side) => onStartPlaceFlow(side)}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
          />
        ) : (
          <StraightBetList
            activeLens={activeLens}
            tutorialMode={tutorialMode}
            results={results}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            boostPercent={boostPercent}
            canLoadMore={canLoadMore}
            onLoadMore={onLoadMore}
            onLogBet={onLogBet}
            onAddToCart={onAddToCart}
            onStartPlaceFlow={onStartPlaceFlow}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
          />
        )
      )}
    </div>
  );
}
