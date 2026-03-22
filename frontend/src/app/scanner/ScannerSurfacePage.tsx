"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { LogBetDrawer } from "@/components/LogBetDrawer";
import { OnboardingBanner } from "@/components/OnboardingBanner";
import { getLatestScan, scanMarkets } from "@/lib/api";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useBalances, useBackendReadiness, useSettings, queryKeys } from "@/lib/hooks";
import {
  applyScannerResultFilters,
  defaultScannerResultFilters,
  describeScannerResultFilters,
  type ScannerRiskPreset,
  type ScannerTimePreset,
} from "@/lib/scanner-filters";
import { createClient } from "@/lib/supabase";
import type { MarketSide, ScannedBetData, ScannerSurface } from "@/lib/types";
import { useKellySettings } from "@/lib/kelly-context";
import {
  classifyScannerNullState,
  describeActiveResultFilters,
  isPlayerPropScanDiagnostics,
} from "@/lib/scanner-contract";

import { ScannerHeader } from "./components/ScannerHeader";
import { ScannerLensSelector } from "./components/ScannerLensSelector";
import { ScannerResultFilters } from "./components/ScannerResultFilters";
import { ScannerResultsPane } from "./components/ScannerResultsPane";
import { ScannerScopeBar } from "./components/ScannerScopeBar";
import { ScannerStatusBar } from "./components/ScannerStatusBar";
import { ScannerPreScanEmptyState } from "./components/ScannerPreScanEmptyState";
import { PlayerPropDiagnosticsPanel } from "./components/PlayerPropDiagnosticsPanel";
import { getScannerSurface } from "./scanner-surfaces";
import { rankScannerSidesByLens } from "./scanner-lenses";
import type { ScannerLens } from "./scanner-ui-model";
import {
  buildParlayCartLeg,
  buildScannerLogBetInitialValues,
  parseScannerCustomBoostInput,
  toggleScannerBookSelection,
} from "./scanner-state-utils";

const SPORT_KEY_TO_DISPLAY: Record<string, string> = {
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
};

const STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN Bet"];
const PLAYER_PROP_BOOKS = ["Bovada", "BetOnline.ag", "DraftKings", "FanDuel", "BetMGM", "Caesars"];
const DEFAULT_STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel"];
const DEFAULT_PLAYER_PROP_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Bovada", "BetOnline.ag"];
const LONGSHOT_MAX_AMERICAN = 500;
const BOOST_PRESETS = [25, 30, 50];
const DEFAULT_RESULT_FILTERS = defaultScannerResultFilters();

const bookColors: Record<string, string> = {
  Bovada: "bg-[#B85C38]",
  "BetOnline.ag": "bg-[#4A7C59]",
  DraftKings: "bg-draftkings",
  FanDuel: "bg-fanduel",
  BetMGM: "bg-betmgm",
  Caesars: "bg-caesars",
  "ESPN Bet": "bg-espnbet",
};

function minutesAgo(isoString: string): number {
  if (!isoString) return 0;
  const then = new Date(isoString).getTime();
  return Math.max(0, Math.floor((Date.now() - then) / 60_000));
}

export function ScannerSurfacePage({ surface }: { surface: ScannerSurface }) {
  const surfaceConfig = getScannerSurface(surface);
  const availableBooks = surface === "player_props" ? PLAYER_PROP_BOOKS : STRAIGHT_BET_BOOKS;
  const defaultSelectedBooks = surface === "player_props" ? DEFAULT_PLAYER_PROP_BOOKS : DEFAULT_STRAIGHT_BET_BOOKS;
  const queryClient = useQueryClient();
  const { data: balances } = useBalances();
  const { data: readiness } = useBackendReadiness();
  const { data: settings } = useSettings();
  const { cart, addCartLeg, surfaceFilters, setSurfaceFilters } = useBettingPlatformStore();
  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const computedBankroll = useMemo(() => {
    if (!balances || balances.length === 0) return 0;
    return balances.reduce((sum, b) => sum + (b.balance || 0), 0);
  }, [balances]);
  const bankroll = useComputedBankroll ? computedBankroll : bankrollOverride;
  const persistedFilters = surfaceFilters[surface] as Partial<{
    selectedBooks: string[];
    activeLens: ScannerLens;
    boostPercent: number;
    customBoostInput: string;
    searchQuery: string;
    timePreset: ScannerTimePreset;
    edgeMinStandard: number;
    hideLongshots: boolean;
    hideAlreadyLogged: boolean;
    riskPreset: ScannerRiskPreset;
    propMarket: string;
    propSide: "all" | "over" | "under";
  }> | undefined;

  const {
    data: scanData,
    isFetching: isFetchingLatest,
    error: scanErrorRaw,
  } = useQuery({
    queryKey: queryKeys.scanMarkets(surface),
    queryFn: () => getLatestScan(surface),
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 1,
  });

  const scanError = scanErrorRaw instanceof Error ? scanErrorRaw.message : null;
  const [isRunningScan, setIsRunningScan] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [activeLens, setActiveLens] = useState<ScannerLens>(
    surface === "player_props" ? "standard" : persistedFilters?.activeLens ?? "standard"
  );
  const [boostPercent, setBoostPercent] = useState(persistedFilters?.boostPercent ?? 30);
  const [customBoostInput, setCustomBoostInput] = useState(persistedFilters?.customBoostInput ?? "");
  const [selectedBooks, setSelectedBooks] = useState<string[]>(persistedFilters?.selectedBooks ?? defaultSelectedBooks);
  const [visibleCount, setVisibleCount] = useState(10);
  const [searchQuery, setSearchQuery] = useState(persistedFilters?.searchQuery ?? DEFAULT_RESULT_FILTERS.searchQuery);
  const [timePreset, setTimePreset] = useState<ScannerTimePreset>(persistedFilters?.timePreset ?? DEFAULT_RESULT_FILTERS.timePreset);
  const [edgeMinStandard, setEdgeMinStandard] = useState(persistedFilters?.edgeMinStandard ?? DEFAULT_RESULT_FILTERS.edgeMinStandard);
  const [hideLongshots, setHideLongshots] = useState(persistedFilters?.hideLongshots ?? DEFAULT_RESULT_FILTERS.hideLongshots);
  const [hideAlreadyLogged, setHideAlreadyLogged] = useState(persistedFilters?.hideAlreadyLogged ?? DEFAULT_RESULT_FILTERS.hideAlreadyLogged);
  const [riskPreset, setRiskPreset] = useState<ScannerRiskPreset>(persistedFilters?.riskPreset ?? DEFAULT_RESULT_FILTERS.riskPreset);
  const [propMarket, setPropMarket] = useState(persistedFilters?.propMarket ?? DEFAULT_RESULT_FILTERS.propMarket);
  const [propSide, setPropSide] = useState<"all" | "over" | "under">(persistedFilters?.propSide ?? DEFAULT_RESULT_FILTERS.propSide);
  const [, setAgeTick] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const [drawerInitialValues, setDrawerInitialValues] = useState<ScannedBetData | undefined>();
  const showBackendHint = !!readiness && (readiness.status !== "ready" || !readiness.checks.scheduler_freshness);
  const backendHint =
    readiness?.status === "unreachable"
      ? "Scanner is reconnecting. Odds may be slightly delayed."
      : "Scanner data is refreshing. Prices may be a little behind.";

  useEffect(() => {
    setSurfaceFilters(surface, {
      selectedBooks,
      activeLens,
      boostPercent,
      customBoostInput,
      searchQuery,
      timePreset,
      edgeMinStandard,
      hideLongshots,
      hideAlreadyLogged,
      riskPreset,
      propMarket,
      propSide,
    });
  }, [
    activeLens,
    boostPercent,
    customBoostInput,
    edgeMinStandard,
    hideAlreadyLogged,
    hideLongshots,
    propMarket,
    propSide,
    riskPreset,
    searchQuery,
    selectedBooks,
    setSurfaceFilters,
    surface,
    timePreset,
  ]);

  useEffect(() => {
    if (!scanData?.scanned_at) return;
    const timer = setInterval(() => setAgeTick((tick) => tick + 1), 60_000);
    return () => clearInterval(timer);
  }, [scanData?.scanned_at]);

  useEffect(() => {
    const supabase = createClient();
    const channel = supabase
      .channel(`scan-latest-updates-${surface}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "global_scan_cache",
          filter: `surface=eq.${surface}`,
        },
        () => {
          queryClient.invalidateQueries({ queryKey: queryKeys.scanMarkets(surface) });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [queryClient, surface]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const handleScan = async () => {
    if (cooldown > 0 || isRunningScan) return;
    setIsRunningScan(true);
    try {
      const res = await scanMarkets(surface);
      queryClient.setQueryData(queryKeys.scanMarkets(surface), res);
      setCooldown(60);
      queryClient.invalidateQueries({ queryKey: queryKeys.bets });
    } finally {
      setIsRunningScan(false);
    }
  };

  const toggleBook = (book: string) => {
    setSelectedBooks((prev) => toggleScannerBookSelection(prev, book));
  };

  const kUser = settings?.k_factor_mode === "auto" ? (settings.k_factor_observed ?? undefined) : undefined;
  const kWeight = settings?.k_factor_mode === "auto" ? (settings.k_factor_weight ?? 0) : 0;

  const fullResults = useMemo(() => {
    if (!scanData) return [];
    if (surface === "player_props") {
      return scanData.sides.filter((side) => selectedBooks.includes(side.sportsbook));
    }
    return rankScannerSidesByLens({
      sides: scanData.sides,
      selectedBooks,
      activeLens,
      boostPercent,
      kUser,
      kWeight,
    });
  }, [activeLens, boostPercent, kUser, kWeight, scanData, selectedBooks, surface]);

  const effectiveLens: ScannerLens = surface === "player_props" ? "standard" : activeLens;

  const filteredResults = useMemo(() => {
    return applyScannerResultFilters({
      sides: fullResults,
      activeLens: effectiveLens,
      longshotMaxAmerican: LONGSHOT_MAX_AMERICAN,
      filters: {
        searchQuery,
        timePreset,
        edgeMinStandard,
        hideLongshots,
        hideAlreadyLogged,
        riskPreset,
        propMarket,
        propSide,
      },
    });
  }, [edgeMinStandard, effectiveLens, fullResults, hideAlreadyLogged, hideLongshots, propMarket, propSide, riskPreset, searchQuery, timePreset]);

  const activeResultFilterChips = useMemo(() => {
    return describeScannerResultFilters({
      activeLens: effectiveLens,
      longshotMaxAmerican: LONGSHOT_MAX_AMERICAN,
      showDefaultStandardEdge: surface === "player_props",
      filters: {
        searchQuery,
        timePreset,
        edgeMinStandard,
        hideLongshots,
        hideAlreadyLogged,
        riskPreset,
        propMarket,
        propSide,
      },
    });
  }, [edgeMinStandard, effectiveLens, hideAlreadyLogged, hideLongshots, propMarket, propSide, riskPreset, searchQuery, timePreset]);

  const nullState = useMemo(() => {
    return classifyScannerNullState({
      sourceCount: fullResults.length,
      filteredCount: filteredResults.length,
    });
  }, [filteredResults.length, fullResults.length]);

  useEffect(() => {
    setVisibleCount(10);
  }, [scanData, effectiveLens, boostPercent, selectedBooks, hideLongshots, hideAlreadyLogged, riskPreset, edgeMinStandard, timePreset, searchQuery, propMarket, propSide]);

  const results = useMemo(() => filteredResults.slice(0, visibleCount), [filteredResults, visibleCount]);
  const scanAgeMinutes = useMemo(() => (scanData?.scanned_at ? minutesAgo(scanData.scanned_at) : null), [scanData?.scanned_at]);

  const secondaryActiveFilterChips = activeResultFilterChips;
  const hasActiveSecondaryFilters = secondaryActiveFilterChips.length > 0;
  const availablePropMarkets = useMemo(() => {
    if (surface !== "player_props" || !scanData) return [];
    const markets = new Set(
      scanData.sides
        .filter((side): side is Extract<MarketSide, { surface: "player_props" }> => side.surface === "player_props")
        .map((side) => side.market_key)
    );
    return Array.from(markets).sort((left, right) => left.localeCompare(right));
  }, [scanData, surface]);
  const playerPropDiagnostics =
    surface === "player_props" && isPlayerPropScanDiagnostics(scanData?.diagnostics)
      ? scanData.diagnostics
      : null;

  const resetSecondaryFilters = () => {
    setTimePreset(DEFAULT_RESULT_FILTERS.timePreset);
    setEdgeMinStandard(DEFAULT_RESULT_FILTERS.edgeMinStandard);
    setHideLongshots(DEFAULT_RESULT_FILTERS.hideLongshots);
    setHideAlreadyLogged(DEFAULT_RESULT_FILTERS.hideAlreadyLogged);
    setRiskPreset(DEFAULT_RESULT_FILTERS.riskPreset);
    setPropMarket(DEFAULT_RESULT_FILTERS.propMarket);
    setPropSide(DEFAULT_RESULT_FILTERS.propSide);
    setBoostPercent(30);
    setCustomBoostInput("");
  };

  const handleLogBet = (side: MarketSide) => {
    setDrawerInitialValues(
      buildScannerLogBetInitialValues({
        side,
        activeLens: effectiveLens,
        boostPercent,
        sportDisplayMap: SPORT_KEY_TO_DISPLAY,
        kellyMultiplier,
        bankroll,
      })
    );
    setDrawerKey(Date.now());
    setDrawerOpen(true);
  };

  const handleAddToCart = (side: MarketSide) => {
    const result = addCartLeg(buildParlayCartLeg(side));
    if (!result.added) {
      toast.error(result.reason === "same_event_conflict" ? "Same-event legs are blocked for now." : "That leg is already in your cart.");
      return;
    }
    toast.success(`Added to parlay cart (${cart.length + 1})`);
  };

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-2xl space-y-2 px-4 py-6 pb-20 sm:pb-24">
        <OnboardingBanner
          step={`scanner_${surface}`}
          title={surface === "player_props" ? "Find your first playable prop" : "Scan and bank your first edge"}
          body={surface === "player_props"
            ? "Use player search, market filters, and line-aware cards to find one prop, add it to the cart, or log it straight from the scanner."
            : "Run a scan, pick one clean +EV spot, and either log it or add it to the parlay cart to start your V2 workflow."}
        />

        <ScannerHeader tagline={surfaceConfig.tagline} />

        <ScannerScopeBar books={availableBooks} selectedBooks={selectedBooks} onToggleBook={toggleBook} bookColors={bookColors} />

        <ScannerStatusBar
          hasScanData={Boolean(scanData)}
          isRunningScan={isRunningScan}
          cooldown={cooldown}
          onScan={handleScan}
          scanError={scanError}
          scanAgeMinutes={scanAgeMinutes}
          eventsFetched={scanData?.events_fetched ?? 0}
          showBackendHint={showBackendHint}
          backendHint={backendHint}
        />

        {playerPropDiagnostics && (
          <PlayerPropDiagnosticsPanel diagnostics={playerPropDiagnostics} />
        )}

        {scanData && surfaceConfig.supportsLensSelector && (
          <ScannerLensSelector activeLens={activeLens} onLensChange={setActiveLens} />
        )}

        {scanData && (
          <ScannerResultFilters
            filters={{
              searchQuery,
              timePreset,
              edgeMinStandard,
              hideLongshots,
              hideAlreadyLogged,
              riskPreset,
              propMarket,
              propSide,
            }}
            surface={surface}
            showEdgeControl={effectiveLens === "standard"}
            activeLens={effectiveLens}
            boostPercent={boostPercent}
            customBoostInput={customBoostInput}
            boostPresets={BOOST_PRESETS}
            activeFilterChips={secondaryActiveFilterChips}
            hasActiveFilters={hasActiveSecondaryFilters}
            searchPlaceholder={surfaceConfig.searchPlaceholder}
            availablePropMarkets={availablePropMarkets}
            onSearchChange={setSearchQuery}
            onTimePresetChange={setTimePreset}
            onEdgeMinChange={setEdgeMinStandard}
            onHideLongshotsChange={setHideLongshots}
            onHideAlreadyLoggedChange={setHideAlreadyLogged}
            onRiskPresetChange={setRiskPreset}
            onPropMarketChange={setPropMarket}
            onPropSideChange={setPropSide}
            onPresetSelect={(preset) => {
              setBoostPercent(preset);
              setCustomBoostInput("");
            }}
            onCustomBoostInputChange={(val) => {
              setCustomBoostInput(val);
              const n = parseScannerCustomBoostInput(val);
              if (n !== null) {
                setBoostPercent(n);
              }
            }}
            onResetFilters={resetSecondaryFilters}
          />
        )}

        {scanData && (
          <ScannerResultsPane
            surface={surface}
            activeLens={effectiveLens}
            results={results}
            sourceCount={fullResults.length}
            filteredCount={filteredResults.length}
            nullState={nullState}
            activeResultFilterSummary={describeActiveResultFilters(activeResultFilterChips)}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            boostPercent={boostPercent}
            canLoadMore={filteredResults.length > results.length}
            onLoadMore={() => setVisibleCount((count) => count + 10)}
            onLogBet={handleLogBet}
            onAddToCart={handleAddToCart}
            bookColors={bookColors}
            sportDisplayMap={SPORT_KEY_TO_DISPLAY}
          />
        )}

        {!scanData && !isFetchingLatest && !scanError && <ScannerPreScanEmptyState />}
      </div>

      <LogBetDrawer key={drawerKey} open={drawerOpen} onOpenChange={setDrawerOpen} initialValues={drawerInitialValues} />
    </main>
  );
}
