import { Card, CardContent } from "@/components/ui/card";
import type { ScannerNullState } from "@/lib/scanner-contract";
import type { MarketSide, ScannerSurface } from "@/lib/types";
import { getScannerSurface } from "../scanner-surfaces";
import type { PickEmBoardCard } from "../pickem-board";
import { PlayerPropList } from "./PlayerPropList";
import { PickEmBoardList } from "./PickEmBoardList";
import { StraightBetList } from "./StraightBetList";

interface ScannerResultsPaneProps {
  surface: ScannerSurface;
  playerPropsView?: "sportsbooks" | "pickem";
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  tutorialMode?: boolean;
  results: Array<MarketSide & { _retention?: number; _boostedEV?: number; _qualifierHold?: number }>;
  pickemCards?: PickEmBoardCard[];
  sourceCount: number;
  rawSourceCount: number;
  filteredCount: number;
  nullState: ScannerNullState;
  activeResultFilterSummary: string;
  pickemEmptyMessage?: string | null;
  pickemEmptySubMessage?: string | null;
  addedPickEmComparisonKeys?: string[];
  kellyMultiplier: number;
  bankroll: number;
  boostPercent: number;
  canLoadMore: boolean;
  isLoadingMore?: boolean;
  onLoadMore: () => void;
  onAddPickEmToSlip: (card: PickEmBoardCard) => void;
  onLogBet: (side: MarketSide) => void;
  onAddToCart: (side: MarketSide) => void;
  onStartPlaceFlow: (side: MarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function ScannerResultsPane({
  surface,
  playerPropsView = "sportsbooks",
  activeLens,
  tutorialMode = false,
  results,
  pickemCards = [],
  sourceCount,
  rawSourceCount,
  filteredCount,
  nullState,
  activeResultFilterSummary,
  pickemEmptyMessage = null,
  pickemEmptySubMessage = null,
  addedPickEmComparisonKeys = [],
  kellyMultiplier,
  bankroll,
  boostPercent,
  canLoadMore,
  isLoadingMore = false,
  onLoadMore,
  onAddPickEmToSlip,
  onLogBet,
  onAddToCart,
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: ScannerResultsPaneProps) {
  const surfaceConfig = getScannerSurface(surface);
  const isPropsSurface = surface === "player_props";
  const isPickEmView = isPropsSurface && playerPropsView === "pickem";
  const pregameExcludedCount = Math.max(0, rawSourceCount - sourceCount);
  const scanExpiredOutOfPregame = nullState === "backend_empty" && pregameExcludedCount > 0;

  return (
    <div className="space-y-2">
      {tutorialMode && (
        <p className="px-0.5 text-xs text-muted-foreground">
          Tutorial mode: the lines below are sample straight bets. Practice tickets stay local to this walkthrough and disappear when you finish it.
        </p>
      )}
      {isPickEmView && (
        <p className="px-0.5 text-xs text-muted-foreground">
          Pick&apos;em support uses all scanned books for exact-line consensus. My Books only affects the sportsbook card view.
        </p>
      )}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {isPropsSurface
          ? isPickEmView
            ? `${pickemCards.length} of ${filteredCount} pick'em lines`
            : `${results.length} of ${filteredCount} ${activeLens === "standard" ? "opportunities" : "props"}`
          : tutorialMode
            ? `${results.length} of ${filteredCount} tutorial lines`
            : `${results.length} of ${filteredCount} ${
              activeLens === "standard"
                ? "+EV lines"
                : activeLens === "bonus_bet"
                  ? "bonus bet targets"
                  : activeLens === "profit_boost"
                    ? "boost opportunities"
                    : "qualifier candidates"
            }`}
      </p>

      {(isPickEmView ? pickemCards.length === 0 : results.length === 0) ? (
        <Card className="border-dashed border-border/60 bg-muted/10">
          <CardContent className="py-10 text-center">
            <p className="text-sm font-medium text-foreground">
              {scanExpiredOutOfPregame
                ? isPickEmView
                  ? `${rawSourceCount} pick'em lines scanned — none still pregame.`
                  : isPropsSurface
                    ? `${rawSourceCount} props scanned — none still pregame.`
                    : `${rawSourceCount} plays scanned — none still pregame.`
                : isPickEmView && nullState === "backend_empty"
                ? pickemEmptyMessage ||
                  "No supported pick'em board lines are available for this scan yet."
                : nullState === "backend_empty"
                ? isPropsSurface
                  ? surfaceConfig.emptyLabel
                  : activeLens === "standard"
                    ? "No clear starter plays right now. Check back when lines move."
                    : activeLens === "bonus_bet"
                      ? "No bonus-bet targets are standing out right now."
                      : activeLens === "qualifier"
                        ? "No clean qualifier candidates are in range right now."
                        : "No strong boost opportunities are standing out at this percentage."
                : isPickEmView
                  ? `${sourceCount} pick'em lines available — filters hiding all of them.`
                  : isPropsSurface
                  ? `${sourceCount} props scanned — filters hiding all of them.`
                  : "Filters are hiding all available plays."}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {scanExpiredOutOfPregame
                ? "Started games are hidden by default. Refresh to load the current slate."
                : isPickEmView && nullState === "backend_empty"
                ? pickemEmptySubMessage ||
                  "Adjust your market filters or try a new scan later."
                : nullState === "backend_empty"
                ? "Try a refresh later, or switch books if you want a different slate."
                : "Try Reset, loosen Safer Odds, or turn off Hide Logged to see more options."}
            </p>
            {nullState === "filter_empty" && (
              <p className="mt-2 text-xs text-muted-foreground">{activeResultFilterSummary}</p>
            )}
          </CardContent>
        </Card>
      ) : (
        isPickEmView ? (
          <PickEmBoardList
            cards={pickemCards}
            canLoadMore={canLoadMore}
            isLoadingMore={isLoadingMore}
            onLoadMore={onLoadMore}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
            addedComparisonKeys={addedPickEmComparisonKeys}
            onAddToSlip={onAddPickEmToSlip}
          />
        ) : isPropsSurface ? (
          <PlayerPropList
            results={results as Array<Extract<MarketSide, { surface: "player_props" }> & { _retention?: number; _boostedEV?: number; _qualifierHold?: number }>}
            activeLens={activeLens}
            boostPercent={boostPercent}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            canLoadMore={canLoadMore}
            isLoadingMore={isLoadingMore}
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
            isLoadingMore={isLoadingMore}
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
