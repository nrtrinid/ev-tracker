"use client";

import { useState, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { getLatestScan, scanMarkets } from "@/lib/api";
import type { MarketSide, ScannedBetData } from "@/lib/types";
import { useKellySettings } from "@/lib/kelly-context";
import { useBalances, useBackendReadiness, useSettings } from "@/lib/hooks";
import { createClient } from "@/lib/supabase";
import { useQuery } from "@tanstack/react-query";
import {
  applyScannerResultFilters,
  defaultScannerResultFilters,
  describeScannerResultFilters,
  hasActiveScannerResultFilters,
  type ScannerRiskPreset,
  type ScannerTimePreset,
} from "@/lib/scanner-filters";
import {
  classifyScannerNullState,
  describeActiveResultFilters,
} from "@/lib/scanner-contract";
import { ScannerHeader } from "./components/ScannerHeader";
import { ScannerLensSelector } from "./components/ScannerLensSelector";
import { ScannerResultFilters } from "./components/ScannerResultFilters";
import { ScannerResultsPane } from "./components/ScannerResultsPane";
import { ScannerScopeBar } from "./components/ScannerScopeBar";
import { ScannerStatusBar } from "./components/ScannerStatusBar";
import { ScannerPreScanEmptyState } from "./components/ScannerPreScanEmptyState";
import { STRAIGHT_BETS_SURFACE } from "./scanner-surfaces";
import { rankScannerSidesByLens } from "./scanner-lenses";
import type { ScannerLens } from "./scanner-ui-model";
import {
  buildScannerLogBetInitialValues,
  parseScannerCustomBoostInput,
  toggleScannerBookSelection,
} from "./scanner-state-utils";

// ============ Constants ============

const SPORT_KEY_TO_DISPLAY: Record<string, string> = {
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
  mma_mixed_martial_arts: "UFC",
  soccer_usa_mls: "Soccer",
  tennis_atp_us_open: "Tennis",
};

const AVAILABLE_BOOKS = [
  "DraftKings",
  "FanDuel",
  "BetMGM",
  "Caesars",
  "ESPN Bet",
];

const DEFAULT_SELECTED_BOOKS = ["DraftKings", "FanDuel"];
const LONGSHOT_MAX_AMERICAN = 500;

const BOOST_PRESETS = [25, 30, 50];
const DEFAULT_RESULT_FILTERS = defaultScannerResultFilters();

const bookColors: Record<string, string> = {
  DraftKings: "bg-draftkings",
  FanDuel: "bg-fanduel",
  BetMGM: "bg-betmgm",
  Caesars: "bg-caesars",
  "ESPN Bet": "bg-espnbet",
};

// ============ Helpers ============

function calculateBoostedEV(side: MarketSide, boostPercent: number): number {
  const baseProfit = side.book_decimal - 1;
  const boostedProfit = baseProfit * (1 + boostPercent / 100);
  const boostedDecimal = 1 + boostedProfit;
  return (side.true_prob * boostedDecimal - 1) * 100;
}

function minutesAgo(isoString: string): number {
  if (!isoString) return 0;
  const then = new Date(isoString).getTime();
  return Math.max(0, Math.floor((Date.now() - then) / 60_000));
}

// ============ Page ============

export default function ScannerPage() {
  const queryClient = useQueryClient();
  const { data: balances } = useBalances();
  const { data: readiness } = useBackendReadiness();
  const { data: settings } = useSettings();
  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const computedBankroll = useMemo(() => {
    if (!balances || balances.length === 0) return 0;
    return balances.reduce((sum, b) => sum + (b.balance || 0), 0);
  }, [balances]);
  const bankroll = useComputedBankroll ? computedBankroll : bankrollOverride;
  const {
    data: scanData,
    isFetching: isFetchingLatest,
    error: scanErrorRaw,
  } = useQuery({
    queryKey: ["scan-markets"],
    queryFn: getLatestScan,
    enabled: true, // Load persisted cached scan if available
    staleTime: Infinity, // Never auto-refetch; manual scan button is the only way to refresh
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 1,
  });
  const scanError = scanErrorRaw instanceof Error ? scanErrorRaw.message : null;
  const [isRunningScan, setIsRunningScan] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [activeLens, setActiveLens] = useState<ScannerLens>("standard");
  const [boostPercent, setBoostPercent] = useState(30);
  const [customBoostInput, setCustomBoostInput] = useState("");
  const [selectedBooks, setSelectedBooks] = useState<string[]>(DEFAULT_SELECTED_BOOKS);
  const [visibleCount, setVisibleCount] = useState(10);
  const [searchQuery, setSearchQuery] = useState(DEFAULT_RESULT_FILTERS.searchQuery);
  const [timePreset, setTimePreset] = useState<ScannerTimePreset>(DEFAULT_RESULT_FILTERS.timePreset);
  const [edgeMinStandard, setEdgeMinStandard] = useState(DEFAULT_RESULT_FILTERS.edgeMinStandard);
  const [hideLongshots, setHideLongshots] = useState(DEFAULT_RESULT_FILTERS.hideLongshots);
  const [hideAlreadyLogged, setHideAlreadyLogged] = useState(DEFAULT_RESULT_FILTERS.hideAlreadyLogged);
  const [riskPreset, setRiskPreset] = useState<ScannerRiskPreset>(DEFAULT_RESULT_FILTERS.riskPreset);
  const [ageTick, setAgeTick] = useState(0);
  const showBackendHint = !!readiness && (readiness.status !== "ready" || !readiness.checks.scheduler_freshness);
  const backendHint = readiness?.status === "unreachable"
    ? "Scanner is reconnecting. Odds may be slightly delayed."
    : "Scanner data is refreshing. Prices may be a little behind.";

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const [drawerInitialValues, setDrawerInitialValues] = useState<
    ScannedBetData | undefined
  >();

  useEffect(() => {
    if (!scanData?.scanned_at) return;
    const timer = setInterval(() => {
      setAgeTick((tick) => tick + 1);
    }, 60_000);
    return () => clearInterval(timer);
  }, [scanData?.scanned_at]);

  const scanAgeMinutes = useMemo(() => {
    if (!scanData?.scanned_at) return null;
    return minutesAgo(scanData.scanned_at);
  }, [scanData?.scanned_at, ageTick]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem("scanner_hide_already_logged");
    if (stored === "true") {
      setHideAlreadyLogged(true);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      "scanner_hide_already_logged",
      hideAlreadyLogged ? "true" : "false"
    );
  }, [hideAlreadyLogged]);

  useEffect(() => {
    const supabase = createClient();
    const channel = supabase
      .channel("scan-latest-updates")
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "global_scan_cache",
          filter: "key=eq.latest",
        },
        () => {
          queryClient.invalidateQueries({ queryKey: ["scan-markets"] });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [queryClient]);

  // Cooldown timer
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((prev) => {
        if (prev <= 1) return 0;
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const handleScan = async () => {
    if (cooldown > 0 || isRunningScan) return;
    setIsRunningScan(true);
    try {
      const res = await scanMarkets();
      queryClient.setQueryData(["scan-markets"], res);
      setCooldown(60);
      // Piggyback just updated CLV snapshots in the DB — invalidate bets so
      // the dashboard/bet list shows fresh CLV badges without a manual refresh.
      queryClient.invalidateQueries({ queryKey: ["bets"] });
    } finally {
      setIsRunningScan(false);
    }
  };

  const toggleBook = (book: string) => {
    setSelectedBooks((prev) => toggleScannerBookSelection(prev, book));
  };

  // Effective k for Bonus Bet lens blending
  const kUser = settings?.k_factor_mode === "auto" ? (settings.k_factor_observed ?? undefined) : undefined;
  const kWeight = settings?.k_factor_mode === "auto" ? (settings.k_factor_weight ?? 0) : 0;

  // Filter by selected books then apply lens
  const fullResults = useMemo(() => {
    if (!scanData) return [];
    return rankScannerSidesByLens({
      sides: scanData.sides,
      selectedBooks,
      activeLens,
      boostPercent,
      kUser,
      kWeight,
    });
  }, [scanData, activeLens, boostPercent, selectedBooks, kUser, kWeight]);

  const filteredResults = useMemo(() => {
    return applyScannerResultFilters({
      sides: fullResults,
      activeLens,
      longshotMaxAmerican: LONGSHOT_MAX_AMERICAN,
      filters: {
        searchQuery,
        timePreset,
        edgeMinStandard,
        hideLongshots,
        hideAlreadyLogged,
        riskPreset,
      },
    });
  }, [
    fullResults,
    activeLens,
    searchQuery,
    timePreset,
    edgeMinStandard,
    hideLongshots,
    hideAlreadyLogged,
    riskPreset,
  ]);

  const activeResultFilterChips = useMemo(() => {
    return describeScannerResultFilters({
      activeLens,
      longshotMaxAmerican: LONGSHOT_MAX_AMERICAN,
      filters: {
        searchQuery,
        timePreset,
        edgeMinStandard,
        hideLongshots,
        hideAlreadyLogged,
        riskPreset,
      },
    });
  }, [
    activeLens,
    searchQuery,
    timePreset,
    edgeMinStandard,
    hideLongshots,
    hideAlreadyLogged,
    riskPreset,
  ]);

  const hasActiveResultFilters = useMemo(() => {
    return hasActiveScannerResultFilters({
      activeLens,
      filters: {
        searchQuery,
        timePreset,
        edgeMinStandard,
        hideLongshots,
        hideAlreadyLogged,
        riskPreset,
      },
    });
  }, [
    activeLens,
    searchQuery,
    timePreset,
    edgeMinStandard,
    hideLongshots,
    hideAlreadyLogged,
    riskPreset,
  ]);

  const nullState = useMemo(() => {
    return classifyScannerNullState({
      sourceCount: fullResults.length,
      filteredCount: filteredResults.length,
    });
  }, [fullResults.length, filteredResults.length]);

  useEffect(() => {
    setVisibleCount(10);
  }, [
    scanData,
    activeLens,
    boostPercent,
    selectedBooks,
    hideLongshots,
    hideAlreadyLogged,
    riskPreset,
    edgeMinStandard,
    timePreset,
    searchQuery,
  ]);

  const results = useMemo(() => {
    return filteredResults.slice(0, visibleCount);
  }, [filteredResults, visibleCount]);

  const secondaryActiveFilterChips = useMemo(() => {
    const chips: string[] = [];

    if (timePreset !== DEFAULT_RESULT_FILTERS.timePreset) {
      if (timePreset === "starting_soon") chips.push("Time: Starting Soon");
      if (timePreset === "today") chips.push("Time: Today");
      if (timePreset === "tomorrow") chips.push("Time: Tomorrow");
    }

    if (activeLens === "standard" && edgeMinStandard !== DEFAULT_RESULT_FILTERS.edgeMinStandard) {
      chips.push(edgeMinStandard === 0 ? "Edge: All +EV" : `Edge: ${edgeMinStandard.toFixed(1)}%+`);
    }

    if (hideLongshots !== DEFAULT_RESULT_FILTERS.hideLongshots) {
      chips.push(hideLongshots ? `Odds: <= +${LONGSHOT_MAX_AMERICAN}` : "Odds: All");
    }

    if (hideAlreadyLogged) {
      chips.push("Hide logged");
    }

    if (riskPreset !== DEFAULT_RESULT_FILTERS.riskPreset) {
      chips.push(riskPreset === "safer" ? "Risk: Safer" : "Risk: Balanced");
    }

    if (activeLens === "profit_boost" && customBoostInput.trim() !== "") {
      chips.push("Boost: Custom");
    }

    return chips;
  }, [
    timePreset,
    activeLens,
    edgeMinStandard,
    hideLongshots,
    hideAlreadyLogged,
    riskPreset,
    customBoostInput,
  ]);

  const hasActiveSecondaryFilters = useMemo(() => {
    return (
      timePreset !== DEFAULT_RESULT_FILTERS.timePreset ||
      (activeLens === "standard" && edgeMinStandard !== DEFAULT_RESULT_FILTERS.edgeMinStandard) ||
      hideLongshots !== DEFAULT_RESULT_FILTERS.hideLongshots ||
      hideAlreadyLogged !== DEFAULT_RESULT_FILTERS.hideAlreadyLogged ||
      riskPreset !== DEFAULT_RESULT_FILTERS.riskPreset ||
      (activeLens === "profit_boost" && customBoostInput.trim() !== "")
    );
  }, [
    timePreset,
    activeLens,
    edgeMinStandard,
    hideLongshots,
    hideAlreadyLogged,
    riskPreset,
    customBoostInput,
  ]);

  const resetSecondaryFilters = () => {
    setTimePreset(DEFAULT_RESULT_FILTERS.timePreset);
    setEdgeMinStandard(DEFAULT_RESULT_FILTERS.edgeMinStandard);
    setHideLongshots(DEFAULT_RESULT_FILTERS.hideLongshots);
    setHideAlreadyLogged(DEFAULT_RESULT_FILTERS.hideAlreadyLogged);
    setRiskPreset(DEFAULT_RESULT_FILTERS.riskPreset);
    setBoostPercent(30);
    setCustomBoostInput("");
  };

  const resetResultFilters = () => {
    setSearchQuery(DEFAULT_RESULT_FILTERS.searchQuery);
    setTimePreset(DEFAULT_RESULT_FILTERS.timePreset);
    setEdgeMinStandard(DEFAULT_RESULT_FILTERS.edgeMinStandard);
    setHideLongshots(DEFAULT_RESULT_FILTERS.hideLongshots);
    setHideAlreadyLogged(DEFAULT_RESULT_FILTERS.hideAlreadyLogged);
    setRiskPreset(DEFAULT_RESULT_FILTERS.riskPreset);
  };

  const handleLogBet = (side: MarketSide) => {
    setDrawerInitialValues(
      buildScannerLogBetInitialValues({
        side,
        activeLens,
        boostPercent,
        sportDisplayMap: SPORT_KEY_TO_DISPLAY,
        kellyMultiplier,
        bankroll,
      })
    );
    setDrawerKey(Date.now());
    setDrawerOpen(true);
  };

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-2xl space-y-2 px-4 py-6 pb-20 sm:pb-24">
        <ScannerHeader
          tagline={STRAIGHT_BETS_SURFACE.tagline}
        />

        <ScannerScopeBar
          books={AVAILABLE_BOOKS}
          selectedBooks={selectedBooks}
          onToggleBook={toggleBook}
          bookColors={bookColors}
        />

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

        {scanData && <ScannerLensSelector activeLens={activeLens} onLensChange={setActiveLens} />}

        {scanData && (
          <>
            <ScannerResultFilters
              filters={{
                searchQuery,
                timePreset,
                edgeMinStandard,
                hideLongshots,
                hideAlreadyLogged,
                riskPreset,
              }}
              showEdgeControl={activeLens === "standard"}
              onSearchChange={setSearchQuery}
              onTimePresetChange={setTimePreset}
              onEdgeMinChange={setEdgeMinStandard}
              onHideLongshotsChange={setHideLongshots}
              onHideAlreadyLoggedChange={setHideAlreadyLogged}
              onRiskPresetChange={setRiskPreset}
              activeLens={activeLens}
              boostPercent={boostPercent}
              customBoostInput={customBoostInput}
              boostPresets={BOOST_PRESETS}
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
              activeFilterChips={secondaryActiveFilterChips}
              hasActiveFilters={hasActiveSecondaryFilters}
              onResetFilters={resetSecondaryFilters}
            />
          </>
        )}

        {scanData && (
          <ScannerResultsPane
            activeLens={activeLens}
            results={results}
            filteredCount={filteredResults.length}
            nullState={nullState}
            activeResultFilterSummary={describeActiveResultFilters(activeResultFilterChips)}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            boostPercent={boostPercent}
            canLoadMore={filteredResults.length > results.length}
            onLoadMore={() => setVisibleCount((count) => count + 10)}
            onLogBet={handleLogBet}
            bookColors={bookColors}
            sportDisplayMap={SPORT_KEY_TO_DISPLAY}
          />
        )}

        {/* Pre-scan empty state */}
        {!scanData && !isFetchingLatest && !scanError && <ScannerPreScanEmptyState />}
      </div>

      <LogBetDrawer
        key={drawerKey}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        initialValues={drawerInitialValues}
      />
    </main>
  );
}
