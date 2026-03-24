"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { JourneyCoach } from "@/components/JourneyCoach";
import { LogBetDrawer } from "@/components/LogBetDrawer";
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
import type {
  MarketSide,
  ScannedBetData,
  ScannerSurface,
  TutorialPracticeBet,
} from "@/lib/types";
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
import { buildPickEmBoardCards } from "./pickem-board";
import type { PickEmBoardCard } from "./pickem-board";
import { getScannerSurface } from "./scanner-surfaces";
import { rankScannerSidesByLens } from "./scanner-lenses";
import {
  isStraightBetsTutorialActive,
  STRAIGHT_BETS_TUTORIAL_SCAN,
} from "./scanner-tutorial";
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
const TUTORIAL_SELECTED_BOOKS = Array.from(
  new Set(STRAIGHT_BETS_TUTORIAL_SCAN.sides.map((side) => side.sportsbook))
);

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

function normalizeScannerSearch(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function isSameCalendarDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

function matchesScannerComparisonTimePreset(
  commenceTime: string,
  preset: ScannerTimePreset,
  now: Date
): boolean {
  const start = new Date(commenceTime);
  if (Number.isNaN(start.getTime())) return false;

  const deltaMs = start.getTime() - now.getTime();
  if (deltaMs < 0) return false;
  if (preset === "all") return true;
  if (preset === "starting_soon") return deltaMs < 2 * 60 * 60 * 1000;
  if (preset === "today") return isSameCalendarDay(start, now);

  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  return isSameCalendarDay(start, tomorrow);
}

function filterPickEmBoardCards(params: {
  cards: PickEmBoardCard[];
  searchQuery: string;
  timePreset: ScannerTimePreset;
  propMarket: string;
  now?: Date;
}): PickEmBoardCard[] {
  const { cards, searchQuery, timePreset, propMarket } = params;
  const now = params.now ?? new Date();
  const normalizedQuery = normalizeScannerSearch(searchQuery);

  return cards.filter((card) => {
    if (propMarket !== "all" && card.market_key !== propMarket) return false;
    if (!matchesScannerComparisonTimePreset(card.commence_time, timePreset, now)) return false;
    if (normalizedQuery) {
      const haystack = normalizeScannerSearch(
        `${card.player_name} ${card.market} ${card.event} ${card.team ?? ""} ${card.opponent ?? ""} ${
          card.best_over_sportsbook ?? ""
        } ${card.best_under_sportsbook ?? ""} ${card.exact_line_bookmakers.join(" ")}`
      );
      if (!haystack.includes(normalizedQuery)) return false;
    }
    return true;
  });
}

function sortPickEmBoardCards(cards: PickEmBoardCard[]): PickEmBoardCard[] {
  const confidenceRank: Record<string, number> = {
    elite: 4,
    high: 3,
    solid: 2,
    thin: 1,
  };
  return [...cards].sort((left, right) => {
    const confidenceDiff =
      (confidenceRank[right.confidence_label?.toLowerCase() ?? "thin"] ?? 0) -
      (confidenceRank[left.confidence_label?.toLowerCase() ?? "thin"] ?? 0);
    if (confidenceDiff !== 0) return confidenceDiff;

    const supportDiff = right.exact_line_bookmaker_count - left.exact_line_bookmaker_count;
    if (supportDiff !== 0) return supportDiff;

    const leftLean = Math.abs(left.consensus_over_prob - 0.5);
    const rightLean = Math.abs(right.consensus_over_prob - 0.5);
    if (rightLean !== leftLean) return rightLean - leftLean;

    return left.player_name.localeCompare(right.player_name);
  });
}

export function ScannerSurfacePage({ surface }: { surface: ScannerSurface }) {
  const surfaceConfig = getScannerSurface(surface);
  const availableBooks = surface === "player_props" ? PLAYER_PROP_BOOKS : STRAIGHT_BET_BOOKS;
  const defaultSelectedBooks = surface === "player_props" ? DEFAULT_PLAYER_PROP_BOOKS : DEFAULT_STRAIGHT_BET_BOOKS;
  const queryClient = useQueryClient();
  const { data: balances } = useBalances();
  const { data: readiness } = useBackendReadiness();
  const { data: settings } = useSettings();
  const {
    isHydrated,
    cart,
    addCartLeg,
    surfaceFilters,
    setSurfaceFilters,
    scannerReviewCandidate,
    setScannerReviewCandidate,
    clearScannerReviewCandidate,
    tutorialSession,
    startTutorialSession,
    markTutorialScanSeeded,
    saveTutorialPracticeBet,
    onboardingCompleted,
    onboardingDismissed,
  } = useBettingPlatformStore();
  const tutorialMode = isHydrated && isStraightBetsTutorialActive({
    surface,
    completed: onboardingCompleted,
    dismissed: onboardingDismissed,
  });
  const tutorialStep = tutorialSession?.step ?? "scanner_empty";
  const tutorialScannerActive = tutorialMode && surface === "straight_bets";
  const hasTutorialScan = tutorialScannerActive && (tutorialSession?.has_seeded_scan ?? false);
  const showScannerCoach = !tutorialScannerActive || tutorialStep === "home_review";
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
    enabled: !tutorialScannerActive,
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 1,
  });

  const scanError = scanErrorRaw instanceof Error ? scanErrorRaw.message : null;
  const [isRunningScan, setIsRunningScan] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [playerPropsView, setPlayerPropsView] = useState<"sportsbooks" | "pickem">("sportsbooks");
  const isPickEmSubview = surface === "player_props" && playerPropsView === "pickem";
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
  const [drawerMode, setDrawerMode] = useState<"standard" | "tutorial_practice">("standard");
  const effectiveScanData = tutorialScannerActive
    ? hasTutorialScan
      ? STRAIGHT_BETS_TUTORIAL_SCAN
      : null
    : scanData;
  const showBackendHint = !!readiness && (readiness.status !== "ready" || !readiness.checks.scheduler_freshness);
  const backendHint =
    readiness?.status === "unreachable"
      ? "Scanner is reconnecting. Odds may be slightly delayed."
      : "Scanner data is refreshing. Prices may be a little behind.";

  const applyTutorialScannerDefaults = useCallback(() => {
    setSelectedBooks(TUTORIAL_SELECTED_BOOKS.filter((book) => availableBooks.includes(book)));
    setActiveLens("standard");
    setSearchQuery("");
    setTimePreset("all");
    setEdgeMinStandard(0);
    setHideLongshots(false);
    setHideAlreadyLogged(false);
    setRiskPreset("any");
    setBoostPercent(30);
    setCustomBoostInput("");
    setPropMarket("all");
    setPropSide("all");
  }, [availableBooks]);

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
    if (!isHydrated || !tutorialScannerActive || tutorialSession) return;
    startTutorialSession(surface);
  }, [isHydrated, surface, startTutorialSession, tutorialScannerActive, tutorialSession]);

  useEffect(() => {
    if (!tutorialScannerActive) return;
    applyTutorialScannerDefaults();
  }, [applyTutorialScannerDefaults, tutorialScannerActive, tutorialSession?.started_at]);

  useEffect(() => {
    if (!effectiveScanData?.scanned_at) return;
    const timer = setInterval(() => setAgeTick((tick) => tick + 1), 60_000);
    return () => clearInterval(timer);
  }, [effectiveScanData?.scanned_at]);

  useEffect(() => {
    if (tutorialScannerActive) return;
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
  }, [queryClient, surface, tutorialScannerActive]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const handleScan = async () => {
    if (cooldown > 0 || isRunningScan) return;
    if (tutorialScannerActive) {
      if (tutorialSession?.step === "home_review") {
        toast("Practice ticket ready on Home", {
          description: "Use the Home prompt when you are ready to review and finish the tutorial.",
        });
        return;
      }
      applyTutorialScannerDefaults();
      startTutorialSession(surface);
      markTutorialScanSeeded();
      toast("Tutorial scan loaded", {
        description: "Sample straight bets are ready. Pick one practice line and we will walk it back to Home.",
      });
      return;
    }
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

  const rankingLens: ScannerLens = activeLens;

  const fullResults = useMemo(() => {
    if (!effectiveScanData) return [];
    if (surface === "player_props") {
      return effectiveScanData.sides.filter((side) => selectedBooks.includes(side.sportsbook));
    }
    return rankScannerSidesByLens({
      sides: effectiveScanData.sides,
      selectedBooks,
      activeLens: rankingLens,
      boostPercent,
      kUser,
      kWeight,
    });
  }, [boostPercent, effectiveScanData, kUser, kWeight, rankingLens, selectedBooks, surface]);

  const effectiveLens: ScannerLens =
    surface === "player_props" ? "standard" : activeLens;

  const pickEmSourceCards = useMemo(() => {
    if (surface !== "player_props" || !effectiveScanData) return [];
    return buildPickEmBoardCards(
      effectiveScanData.sides.filter(
        (side): side is Extract<MarketSide, { surface: "player_props" }> => side.surface === "player_props"
      )
    );
  }, [effectiveScanData, surface]);

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

  const filteredPickEmCards = useMemo(() => {
    return sortPickEmBoardCards(
      filterPickEmBoardCards({
        cards: pickEmSourceCards,
        searchQuery,
        timePreset,
        propMarket,
      })
    );
  }, [pickEmSourceCards, propMarket, searchQuery, timePreset]);

  const activeResultFilterChips = useMemo(() => {
    return describeScannerResultFilters({
      activeLens: effectiveLens,
      longshotMaxAmerican: LONGSHOT_MAX_AMERICAN,
      showDefaultStandardEdge: surface === "player_props" && !isPickEmSubview,
      filters: {
        searchQuery,
        timePreset,
        edgeMinStandard: isPickEmSubview ? DEFAULT_RESULT_FILTERS.edgeMinStandard : edgeMinStandard,
        hideLongshots: isPickEmSubview ? false : hideLongshots,
        hideAlreadyLogged: isPickEmSubview ? false : hideAlreadyLogged,
        riskPreset: isPickEmSubview ? "any" : riskPreset,
        propMarket,
        propSide: isPickEmSubview ? "all" : propSide,
      },
    });
  }, [edgeMinStandard, effectiveLens, hideAlreadyLogged, hideLongshots, isPickEmSubview, propMarket, propSide, riskPreset, searchQuery, surface, timePreset]);

  const nullState = useMemo(() => {
    return classifyScannerNullState({
      sourceCount: isPickEmSubview ? pickEmSourceCards.length : fullResults.length,
      filteredCount: isPickEmSubview ? filteredPickEmCards.length : filteredResults.length,
    });
  }, [filteredPickEmCards.length, filteredResults.length, fullResults.length, isPickEmSubview, pickEmSourceCards.length]);

  useEffect(() => {
    setVisibleCount(10);
  }, [effectiveScanData, effectiveLens, boostPercent, selectedBooks, hideLongshots, hideAlreadyLogged, riskPreset, edgeMinStandard, timePreset, searchQuery, propMarket, propSide, playerPropsView]);

  const results = useMemo(() => filteredResults.slice(0, visibleCount), [filteredResults, visibleCount]);
  const visiblePickEmCards = useMemo(
    () => filteredPickEmCards.slice(0, visibleCount),
    [filteredPickEmCards, visibleCount]
  );
  const scanAgeMinutes = useMemo(() => (effectiveScanData?.scanned_at ? minutesAgo(effectiveScanData.scanned_at) : null), [effectiveScanData?.scanned_at]);

  const secondaryActiveFilterChips = activeResultFilterChips;
  const hasActiveSecondaryFilters = secondaryActiveFilterChips.length > 0;
  const availablePropMarkets = useMemo(() => {
    if (surface !== "player_props" || !effectiveScanData) return [];
    const markets = new Set<string>();
    effectiveScanData.sides
      .filter((side): side is Extract<MarketSide, { surface: "player_props" }> => side.surface === "player_props")
      .forEach((side) => markets.add(side.market_key));
    return Array.from(markets).sort((left, right) => left.localeCompare(right));
  }, [effectiveScanData, surface]);
  const playerPropDiagnostics =
    surface === "player_props" && isPlayerPropScanDiagnostics(effectiveScanData?.diagnostics)
      ? effectiveScanData.diagnostics
      : null;
  const pickEmEmptyMessage =
    isPickEmSubview && pickEmSourceCards.length === 0
      ? "No pick'em board lines were available from the current sportsbook scan."
      : null;
  const pickEmEmptySubMessage =
    pickEmEmptyMessage
      ? "This board only shows supported NBA points, rebounds, assists, and threes lines when at least one sportsbook has both sides posted on the same number."
      : null;
  const activeReviewCandidate = scannerReviewCandidate?.surface === surface ? scannerReviewCandidate : null;

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

  const buildReviewCandidate = (side: MarketSide) =>
    buildScannerLogBetInitialValues({
      side,
      activeLens: effectiveLens,
      boostPercent,
      sportDisplayMap: SPORT_KEY_TO_DISPLAY,
      kellyMultiplier,
      bankroll,
    });

  const openLogDrawer = (betData: ScannedBetData, mode: "standard" | "tutorial_practice" = "standard") => {
    setDrawerInitialValues(betData);
    setDrawerMode(mode);
    setDrawerKey(Date.now());
    setDrawerOpen(true);
  };

  const handleLogBet = (side: MarketSide) => {
    const betData = buildReviewCandidate(side);
    if (tutorialScannerActive) {
      openLogDrawer(betData, "tutorial_practice");
      return;
    }
    setScannerReviewCandidate({
      surface,
      bet: betData,
      createdAt: new Date().toISOString(),
    });
    openLogDrawer(betData);
  };

  const handleStartPlaceFlow = (side: MarketSide) => {
    const betData = buildReviewCandidate(side);
    setScannerReviewCandidate({
      surface,
      bet: betData,
      createdAt: new Date().toISOString(),
    });
    toast("Step 2 of 3 saved", {
      description: `Place it at ${side.sportsbook}, then come back here to review and log it.`,
    });
  };

  const handleReviewSavedCandidate = () => {
    if (!activeReviewCandidate) return;
    openLogDrawer(activeReviewCandidate.bet);
  };

  const handlePracticeLogged = (bet: TutorialPracticeBet) => {
    saveTutorialPracticeBet(bet);
    clearScannerReviewCandidate();
  };

  const handleDrawerOpenChange = (open: boolean) => {
    setDrawerOpen(open);
    if (!open) {
      setDrawerMode("standard");
    }
  };

  const handleAddToCart = (side: MarketSide) => {
    const result = addCartLeg(buildParlayCartLeg(side));
    if (!result.added) {
      toast.error(
        result.reason === "sportsbook_mismatch"
          ? "Parlay Builder only supports one sportsbook per slip."
          : "That leg is already in your cart."
      );
      return;
    }
    toast.success(`Added to parlay cart (${cart.length + 1})`);
  };

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-2xl space-y-2 px-4 py-6 pb-20 sm:pb-24">
        {showScannerCoach && (
          <JourneyCoach
            route="scanner"
            scannerSurface={surface}
            scannerDrawerOpen={drawerOpen}
            tutorialMode={tutorialMode}
            onReviewScannerPick={handleReviewSavedCandidate}
          />
        )}

        <ScannerHeader tagline={surfaceConfig.tagline} />

        {surface === "player_props" && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPlayerPropsView("sportsbooks")}
              className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                playerPropsView === "sportsbooks"
                  ? "border-[#4A7C59]/45 bg-[#4A7C59]/12 text-[#2E5D39]"
                  : "border-border bg-background text-muted-foreground hover:text-foreground"
              }`}
            >
              Sportsbooks
            </button>
            <button
              type="button"
              onClick={() => setPlayerPropsView("pickem")}
              className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                playerPropsView === "pickem"
                  ? "border-[#C4A35A]/40 bg-[#C4A35A]/15 text-[#5C4D2E]"
                  : "border-border bg-background text-muted-foreground hover:text-foreground"
              }`}
            >
              Pick&apos;em
            </button>
          </div>
        )}

        <ScannerScopeBar books={availableBooks} selectedBooks={selectedBooks} onToggleBook={toggleBook} bookColors={bookColors} />

        <ScannerStatusBar
          hasScanData={Boolean(effectiveScanData)}
          isRunningScan={isRunningScan}
          cooldown={cooldown}
          onScan={handleScan}
          scanError={scanError}
          scanAgeMinutes={scanAgeMinutes}
          eventsFetched={effectiveScanData?.events_fetched ?? 0}
          tutorialMode={tutorialScannerActive}
          showBackendHint={!tutorialScannerActive && showBackendHint}
          backendHint={backendHint}
        />

        {playerPropDiagnostics && (
          <PlayerPropDiagnosticsPanel diagnostics={playerPropDiagnostics} />
        )}

        {surfaceConfig.supportsLensSelector && (effectiveScanData || tutorialScannerActive) && (
          <ScannerLensSelector
            activeLens={activeLens}
            onLensChange={setActiveLens}
            tutorialMode={tutorialScannerActive}
          />
        )}

        {(effectiveScanData || tutorialScannerActive) && (
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
            hidePropSideControl={isPickEmSubview}
            sharedPropsOnly={isPickEmSubview}
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

        {effectiveScanData && (
          <ScannerResultsPane
            surface={surface}
            playerPropsView={playerPropsView}
            activeLens={effectiveLens}
            tutorialMode={tutorialScannerActive}
            results={results}
            pickemCards={visiblePickEmCards}
            sourceCount={isPickEmSubview ? pickEmSourceCards.length : fullResults.length}
            filteredCount={isPickEmSubview ? filteredPickEmCards.length : filteredResults.length}
            nullState={nullState}
            activeResultFilterSummary={describeActiveResultFilters(activeResultFilterChips)}
            pickemEmptyMessage={pickEmEmptyMessage}
            pickemEmptySubMessage={pickEmEmptySubMessage}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            boostPercent={boostPercent}
            canLoadMore={isPickEmSubview ? filteredPickEmCards.length > visiblePickEmCards.length : filteredResults.length > results.length}
            onLoadMore={() => setVisibleCount((count) => count + 10)}
            onLogBet={handleLogBet}
            onAddToCart={handleAddToCart}
            onStartPlaceFlow={handleStartPlaceFlow}
            bookColors={bookColors}
            sportDisplayMap={SPORT_KEY_TO_DISPLAY}
          />
        )}

        {!effectiveScanData && !isFetchingLatest && !scanError && (
          <ScannerPreScanEmptyState tutorialMode={tutorialScannerActive} />
        )}
      </div>

      <LogBetDrawer
        key={drawerKey}
        open={drawerOpen}
        onOpenChange={handleDrawerOpenChange}
        initialValues={drawerInitialValues}
        practiceMode={drawerMode === "tutorial_practice"}
        onPracticeLogged={handlePracticeLogged}
        onLogged={clearScannerReviewCandidate}
      />
    </main>
  );
}
