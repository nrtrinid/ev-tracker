"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Clock, Gift, Layers, ShieldCheck, TrendingUp, Zap } from "lucide-react";

import { ScannerResultsPane } from "@/app/scanner/components/ScannerResultsPane";
import { buildPickEmBoardCards } from "@/app/scanner/pickem-board";
import type { PickEmBoardCard } from "@/app/scanner/pickem-board";
import { rankScannerSidesByLens } from "@/app/scanner/scanner-lenses";
import { getLatestScan } from "@/lib/api";
import {
  buildParlayCartLeg,
  buildParlayCartLegFromPickEmCard,
  buildScannerLogBetInitialValues,
} from "@/app/scanner/scanner-state-utils";
import { canAddScannerLensToParlayCart } from "@/app/scanner/scanner-ui-model";
import { classifyScannerNullState } from "@/lib/scanner-contract";
import { useBoard, useBoardSurface, useBalances, useSettings, queryKeys } from "@/lib/hooks";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useKellySettings } from "@/lib/kelly-context";
import { createClient } from "@/lib/supabase";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { cn } from "@/lib/utils";
import type { MarketSide, PlayerPropMarketSide, ScanResult, ScannedBetData } from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────────

type MarketsViewMode = "opportunities" | "browse" | "pickem";
type BoardTimeFilter = "today" | "upcoming" | "all_games" | "today_closed";
type PrimaryMode = "player_props" | "straight_bets" | "promos";
type PromosSubmode = "all" | "boosts" | "bonus_bets" | "qualifiers";

// Pick'em is filtered out when surface === "straight_bets" in the render
const VIEW_MODES: { id: MarketsViewMode; label: string; description: string }[] = [
  { id: "opportunities", label: "Opportunities", description: "+EV lines ranked by edge" },
  { id: "browse", label: "Browse", description: "All loaded lines, ordered by game time" },
  { id: "pickem", label: "Pick'em", description: "PrizePicks consensus board" },
];

const PROMOS_SUBMODES: Array<{
  id: PromosSubmode;
  label: string;
  description: string;
  icon: typeof TrendingUp;
  activeBg: string;
  activeBorder: string;
  activeText: string;
  iconText: string;
}> = [
  {
    id: "all",
    label: "All",
    description: "All promo-ready lines",
    icon: TrendingUp,
    activeBg: "bg-[#F3F7F5] dark:bg-[#1A2A22]",
    activeBorder: "border-[#B7D1C2] dark:border-[#2F5D45]",
    activeText: "text-[#2E5D39] dark:text-[#9FD6B7]",
    iconText: "text-[#2E5D39] dark:text-[#9FD6B7]",
  },
  {
    id: "boosts",
    label: "Boosts",
    description: "Rank by boosted EV",
    icon: Zap,
    activeBg: "bg-[#FCF7EC] dark:bg-[#2B2417]",
    activeBorder: "border-[#E9D7B9] dark:border-[#6D5A2A]",
    activeText: "text-[#8B7A3E] dark:text-[#E5CF94]",
    iconText: "text-[#8B7A3E] dark:text-[#E5CF94]",
  },
  {
    id: "bonus_bets",
    label: "Bonus Bets",
    description: "Rank by retention",
    icon: Gift,
    activeBg: "bg-[#F4F7F5] dark:bg-[#182723]",
    activeBorder: "border-[#B7CFC2] dark:border-[#2E6A55]",
    activeText: "text-[#3B6C4C] dark:text-[#9FD3BE]",
    iconText: "text-[#3B6C4C] dark:text-[#9FD3BE]",
  },
  {
    id: "qualifiers",
    label: "Qualifiers",
    description: "Rank by lowest hold",
    icon: ShieldCheck,
    activeBg: "bg-[#FDF6F3] dark:bg-[#2A1D18]",
    activeBorder: "border-[#E9C7B9] dark:border-[#6E3A2A]",
    activeText: "text-[#8B3D20] dark:text-[#E2A58F]",
    iconText: "text-[#8B3D20] dark:text-[#E2A58F]",
  },
];

const PLAYER_PROP_BOOKS = ["Bovada", "BetOnline.ag", "DraftKings", "FanDuel", "BetMGM", "Caesars"];
const STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN Bet"];
const DEFAULT_PLAYER_PROP_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Bovada", "BetOnline.ag"];
const DEFAULT_STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel"];
const PLAYER_PROP_MARKET_OPTIONS = [
  "player_points",
  "player_rebounds",
  "player_assists",
  "player_points_rebounds_assists",
  "player_threes",
];

const SPORT_KEY_TO_DISPLAY: Record<string, string> = {
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
  baseball_mlb: "MLB",
};

const BOOK_COLORS: Record<string, string> = {
  Bovada: "bg-[#B85C38]",
  "BetOnline.ag": "bg-[#4A7C59]",
  DraftKings: "bg-draftkings",
  FanDuel: "bg-fanduel",
  BetMGM: "bg-betmgm",
  Caesars: "bg-caesars",
  "ESPN Bet": "bg-espnbet",
};

const SCANNER_BOOKS_STORAGE_KEY = "ev-tracker-scanner-books";

type StoredScannerBooks = {
  player_props?: unknown;
  straight_bets?: unknown;
};

function buildPromoDedupeKey(side: MarketSide): string {
  // Promos merges `player_props` + `straight_bets`; this key attempts to identify the underlying selection.
  const playerName = side.surface === "player_props" ? side.player_name : "";
  const lineValue = side.surface === "player_props" ? side.line_value : null;
  const opponent = side.surface === "player_props" ? side.opponent ?? "" : "";
  const selectionSide = side.surface === "player_props" ? side.selection_side : "";
  return [
    side.surface,
    side.sportsbook,
    side.event_id ?? "",
    side.market_key ?? "",
    side.selection_key ?? "",
    side.team ?? "",
    playerName,
    lineValue == null ? "" : String(lineValue),
    side.commence_time,
    opponent,
    selectionSide,
  ].join("|");
}

function duplicateStatePriority(state: MarketSide["scanner_duplicate_state"]): number {
  if (state === "already_logged") return 3;
  if (state === "better_now") return 2;
  if (state === "logged_elsewhere") return 1;
  return 0;
}

function dedupePromoSidesByDuplicateState(sides: MarketSide[]): MarketSide[] {
  const byKey = new Map<string, MarketSide>();
  for (const side of sides) {
    const key = buildPromoDedupeKey(side);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, side);
      continue;
    }

    const incomingPriority = duplicateStatePriority(side.scanner_duplicate_state ?? "new");
    const existingPriority = duplicateStatePriority(existing.scanner_duplicate_state ?? "new");
    if (incomingPriority > existingPriority) {
      byKey.set(key, side);
    }
  }
  return Array.from(byKey.values());
}

function sanitizeStoredBooks(stored: unknown, allowed: readonly string[], fallback: string[]): string[] {
  if (!Array.isArray(stored)) return fallback;
  const allow = new Set(allowed);
  const next = stored.filter((b): b is string => typeof b === "string" && allow.has(b));
  return next.length > 0 ? next : fallback;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function minutesAgo(iso: string): number {
  const then = new Date(iso).getTime();
  return Math.max(0, Math.floor((Date.now() - then) / 60_000));
}

function formatBoardAge(minutes: number): string {
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h ago` : `${h}h ${m}m ago`;
}

type TotalsOffer = {
  sportsbook: string;
  total: number;
  over_odds: number;
  under_odds: number;
};

type GameContextGame = {
  event: string;
  event_short?: string;
  commence_time: string;
  totals_offers: TotalsOffer[];
};

type FeaturedLineGame = {
  event: string;
  event_short?: string;
  sport: string;
  commence_time: string;
  h2h_offers: Array<{ sportsbook: string; home_odds: number; away_odds: number }>;
  spreads_offers: Array<{
    sportsbook: string;
    home_spread: number;
    away_spread: number;
    home_odds: number;
    away_odds: number;
  }>;
  totals_offers: TotalsOffer[];
};

type FeaturedSportBucket = {
  sport: string;
  games: FeaturedLineGame[];
};

function parseGameContextGames(gameContext: unknown): GameContextGame[] {
  if (!gameContext || typeof gameContext !== "object") return [];
  const gc = gameContext as { games?: unknown };
  if (!Array.isArray(gc.games)) return [];

  const out: GameContextGame[] = [];
  for (const rawGame of gc.games) {
    if (!rawGame || typeof rawGame !== "object") continue;
    const g = rawGame as Partial<GameContextGame> & { totals_offers?: unknown };
    if (typeof g.event !== "string" || typeof g.commence_time !== "string") continue;
    if (!Array.isArray(g.totals_offers)) continue;
    const offers: TotalsOffer[] = [];
    for (const rawOffer of g.totals_offers) {
      if (!rawOffer || typeof rawOffer !== "object") continue;
      const o = rawOffer as Partial<TotalsOffer>;
      if (typeof o.sportsbook !== "string") continue;
      if (typeof o.total !== "number") continue;
      if (typeof o.over_odds !== "number") continue;
      if (typeof o.under_odds !== "number") continue;
      offers.push({ sportsbook: o.sportsbook, total: o.total, over_odds: o.over_odds, under_odds: o.under_odds });
    }
    if (offers.length === 0) continue;
    out.push({ event: g.event, event_short: typeof g.event_short === "string" ? g.event_short : undefined, commence_time: g.commence_time, totals_offers: offers });
  }

  return out;
}

function matchesBoardTimeFilter(commenceTime: string, filter: BoardTimeFilter, now: Date = new Date()): boolean {
  const start = new Date(commenceTime);
  if (Number.isNaN(start.getTime())) return false;
  if (filter === "all_games") return true;
  if (filter === "upcoming") return start.getTime() >= now.getTime();
  if (filter === "today") {
    return (
      start.getFullYear() === now.getFullYear() &&
      start.getMonth() === now.getMonth() &&
      start.getDate() === now.getDate() &&
      start.getTime() >= now.getTime()
    );
  }
  return (
    start.getFullYear() === now.getFullYear() &&
    start.getMonth() === now.getMonth() &&
    start.getDate() === now.getDate() &&
    start.getTime() < now.getTime()
  );
}

function sameStringSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const left = [...a].sort();
  const right = [...b].sort();
  return left.every((value, index) => value === right[index]);
}

function formatMarketTypeLabel(market: string): string {
  const normalized = market.startsWith("player_") ? market.slice("player_".length) : market;
  const labels: Record<string, string> = {
    points: "Points",
    rebounds: "Rebounds",
    assists: "Assists",
    points_rebounds_assists: "PRA",
    threes: "Threes",
  };
  return labels[normalized] ?? normalized.replaceAll("_", " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function parseFeaturedLines(gameContext: unknown): FeaturedSportBucket[] {
  if (!gameContext || typeof gameContext !== "object") return [];
  const gc = gameContext as { featured_lines?: unknown };
  if (!gc.featured_lines || typeof gc.featured_lines !== "object") return [];

  const buckets: FeaturedSportBucket[] = [];
  for (const [sport, rawGames] of Object.entries(gc.featured_lines as Record<string, unknown>)) {
    if (!Array.isArray(rawGames)) continue;
    const games: FeaturedLineGame[] = [];
    for (const rawGame of rawGames) {
      if (!rawGame || typeof rawGame !== "object") continue;
      const g = rawGame as Partial<FeaturedLineGame>;
      if (typeof g.event !== "string" || typeof g.commence_time !== "string") continue;
      const h2h = Array.isArray(g.h2h_offers) ? g.h2h_offers.filter((o) => o && typeof o.sportsbook === "string") : [];
      const spreads = Array.isArray(g.spreads_offers) ? g.spreads_offers.filter((o) => o && typeof o.sportsbook === "string") : [];
      const totals = Array.isArray(g.totals_offers) ? g.totals_offers.filter((o) => o && typeof o.sportsbook === "string") : [];
      if (h2h.length === 0 && spreads.length === 0 && totals.length === 0) continue;
      games.push({
        event: g.event,
        event_short: typeof g.event_short === "string" ? g.event_short : undefined,
        sport,
        commence_time: g.commence_time,
        h2h_offers: h2h as FeaturedLineGame["h2h_offers"],
        spreads_offers: spreads as FeaturedLineGame["spreads_offers"],
        totals_offers: totals as FeaturedLineGame["totals_offers"],
      });
    }
    if (games.length > 0) buckets.push({ sport, games });
  }
  return buckets;
}

const PHOENIX_TZ = "America/Phoenix";

function getTimeZoneOffsetMs(date: Date, timeZone: string): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const parts = dtf.formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value;
  const year = Number(get("year"));
  const month = Number(get("month"));
  const day = Number(get("day"));
  const hour = Number(get("hour"));
  const minute = Number(get("minute"));
  const second = Number(get("second"));
  const asUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  return asUtc - date.getTime();
}

function zonedTimeToUtcMs(
  year: number,
  month1: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string,
): number {
  // Initial UTC guess for the intended wall time, then correct by zone offset at that instant.
  const utcGuess = Date.UTC(year, month1 - 1, day, hour, minute, 0);
  const guessDate = new Date(utcGuess);
  const offset = getTimeZoneOffsetMs(guessDate, timeZone);
  return utcGuess - offset;
}

function getNextPhoenixDropUtcMs(now: Date): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: PHOENIX_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = dtf.formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value;
  const year = Number(get("year"));
  const month = Number(get("month"));
  const day = Number(get("day"));

  const dailyWindows: Array<{ hour: number; minute: number }> = [
    { hour: 10, minute: 30 },
    { hour: 15, minute: 30 },
  ];
  const todaysDropsUtc = dailyWindows.map(({ hour, minute }) =>
    zonedTimeToUtcMs(year, month, day, hour, minute, PHOENIX_TZ),
  );
  const nextToday = todaysDropsUtc.find((dropUtc) => now.getTime() < dropUtc);
  if (typeof nextToday === "number") return nextToday;
  return todaysDropsUtc[0] + 24 * 60 * 60 * 1000; // Phoenix does not observe DST
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function MarketsPage() {
  const queryClient = useQueryClient();
  const { data: board, isLoading: isBoardLoading, error: boardError } = useBoard();
  const { data: balances } = useBalances();
  useSettings(); // ensure settings are warmed in cache for LogBetDrawer

  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const { cart, addCartLeg } = useBettingPlatformStore();

  // ── UI state ─────────────────────────────────────────────────────────────
  const [primaryMode, setPrimaryMode] = useState<PrimaryMode>("player_props");
  const [viewMode, setViewMode] = useState<MarketsViewMode>("opportunities");
  const [promosSubmode, setPromosSubmode] = useState<PromosSubmode>("all");

  const propsSurface = useBoardSurface(
    "player_props",
    primaryMode === "player_props" || primaryMode === "promos",
  );
  const straightSurface = useBoardSurface(
    "straight_bets",
    primaryMode === "straight_bets" || primaryMode === "promos",
  );
  // Per-surface book selections — persisted in localStorage (see hydrate / persist effects below)
  const [selectedPropBooks, setSelectedPropBooks] = useState<string[]>(DEFAULT_PLAYER_PROP_BOOKS);
  const [selectedGameLineBooks, setSelectedGameLineBooks] = useState<string[]>(DEFAULT_STRAIGHT_BET_BOOKS);
  const [booksHydrated, setBooksHydrated] = useState(false);
  const selectedBooks = primaryMode === "straight_bets" ? selectedGameLineBooks : selectedPropBooks;
  const setSelectedBooks = primaryMode === "straight_bets" ? setSelectedGameLineBooks : setSelectedPropBooks;

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SCANNER_BOOKS_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as StoredScannerBooks;
        setSelectedPropBooks(
          sanitizeStoredBooks(parsed.player_props, PLAYER_PROP_BOOKS, DEFAULT_PLAYER_PROP_BOOKS),
        );
        setSelectedGameLineBooks(
          sanitizeStoredBooks(parsed.straight_bets, STRAIGHT_BET_BOOKS, DEFAULT_STRAIGHT_BET_BOOKS),
        );
      }
    } catch {
      // ignore malformed storage
    }
    setBooksHydrated(true);
  }, []);

  useEffect(() => {
    if (!booksHydrated) return;
    try {
      localStorage.setItem(
        SCANNER_BOOKS_STORAGE_KEY,
        JSON.stringify({ player_props: selectedPropBooks, straight_bets: selectedGameLineBooks }),
      );
    } catch {
      // ignore quota / private mode
    }
  }, [booksHydrated, selectedPropBooks, selectedGameLineBooks]);
  const [visibleCount, setVisibleCount] = useState(10);
  const [searchQuery, setSearchQuery] = useState("");
  const [showMoreFeaturedLines, setShowMoreFeaturedLines] = useState(false);
  const [timeFilter, setTimeFilter] = useState<BoardTimeFilter>("today");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [propMarketFilter, setPropMarketFilter] = useState<string>("all");

  // ── Board freshness: realtime invalidation ───────────────────────────────
  // Subscribe to Supabase realtime for canonical board changes (surface=board)
  useEffect(() => {
    const supabase = createClient();
    const channel = supabase
      .channel("markets-board-latest")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "global_scan_cache", filter: "surface=eq.board" },
        () => {
          queryClient.invalidateQueries({ queryKey: queryKeys.board });
        },
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [queryClient]);

  // Log drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const [drawerInitialValues, setDrawerInitialValues] = useState<ScannedBetData | undefined>();

  // Pick'em slip state
  const [pickEmSlipKeys, setPickEmSlipKeys] = useState<string[]>([]);

  // ── Derived values ────────────────────────────────────────────────────────
  const bankroll = useMemo(() => {
    if (useComputedBankroll) {
      if (!balances || balances.length === 0) return 0;
      return balances.reduce((sum, b) => sum + (b.balance || 0), 0);
    }
    return bankrollOverride;
  }, [useComputedBankroll, balances, bankrollOverride]);

  const boardMeta = board?.meta;
  const isEmptyBoard = !boardMeta || boardMeta.snapshot_id === "none";

  // After logging, we want duplicate-state tags ("already_logged"/"logged_elsewhere") to update immediately.
  // Board snapshots are persisted and do not re-annotate duplicate state per request, so we temporarily
  // override the sides we display using /api/scan-latest (annotated with duplicate state for the user).
  const [scanLatestOverride, setScanLatestOverride] = useState<{
    player_props?: ScanResult | null;
    straight_bets?: ScanResult | null;
  } | null>(null);

  useEffect(() => {
    // When a new daily drop arrives, discard overrides so we show the new snapshot's sides.
    setScanLatestOverride(null);
  }, [boardMeta?.snapshot_id]);

  // Active scan data:
  // - player_props mode: player props snapshot
  // - straight_bets mode: straight bets snapshot
  // - promos mode: merged sides from both surfaces
  const activeScanData: ScanResult | null = useMemo(() => {
    const propsScan = scanLatestOverride?.player_props ?? propsSurface.data ?? null;
    const straightScan = scanLatestOverride?.straight_bets ?? straightSurface.data ?? null;

    if (primaryMode === "player_props") return propsScan;
    if (primaryMode === "straight_bets") return straightScan;

    // Promos: combine both surfaces so boosts/bonus/qualifier lenses can rank across all cards.
    if (!propsScan && !straightScan) return null;
    const base = propsScan ?? straightScan;
    if (!base) return null;
    return {
      ...base,
      sides: [...(propsScan?.sides ?? []), ...(straightScan?.sides ?? [])],
    };
  }, [primaryMode, scanLatestOverride, propsSurface.data, straightSurface.data]);
  const gameContextGames = useMemo(() => parseGameContextGames(board?.game_context), [board?.game_context]);
  const featuredLineBuckets = useMemo(() => parseFeaturedLines(board?.game_context), [board?.game_context]);

  const boardAgeMinutes = useMemo(() => {
    if (boardMeta?.scanned_at) return minutesAgo(boardMeta.scanned_at);
    return null;
  }, [boardMeta?.scanned_at]);

  const nextDropLabel = useMemo(() => {
    try {
      const nextDropUtcMs = getNextPhoenixDropUtcMs(new Date());
      const nextDropLocal = new Date(nextDropUtcMs);
      const localTime = nextDropLocal.toLocaleString(undefined, {
        weekday: "short",
        hour: "numeric",
        minute: "2-digit",
      });
      return `Next scan: ${localTime}`;
    } catch {
      return "Next scan: 10:30 AM / 3:30 PM";
    }
  }, []);

  const scanWindowLabel = useMemo(() => {
    const gc = board?.game_context as Record<string, unknown> | undefined;
    const scanLabel = typeof gc?.scan_label === "string" ? gc.scan_label : null;
    const mstAnchor = typeof gc?.scan_anchor_time_mst === "string" ? gc.scan_anchor_time_mst : null;
    if (!scanLabel || !mstAnchor) return null;
    const [hourRaw, minuteRaw] = mstAnchor.split(":");
    const hour = Number(hourRaw);
    const minute = Number(minuteRaw);
    if (!Number.isFinite(hour) || !Number.isFinite(minute)) return scanLabel;

    const now = new Date();
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: PHOENIX_TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    const parts = fmt.formatToParts(now);
    const get = (type: string) => parts.find((p) => p.type === type)?.value;
    const y = Number(get("year"));
    const m = Number(get("month"));
    const d = Number(get("day"));
    const utcMs = zonedTimeToUtcMs(y, m, d, hour, minute, PHOENIX_TZ);
    const local = new Date(utcMs).toLocaleString(undefined, { hour: "numeric", minute: "2-digit" });
    return `${scanLabel} • ${local} local`;
  }, [board?.game_context]);

  const featuredGames = useMemo(() => {
    const perSportCap = showMoreFeaturedLines ? 4 : 2;
    const globalCap = showMoreFeaturedLines ? 12 : 6;
    const flat: FeaturedLineGame[] = [];
    for (const bucket of featuredLineBuckets) {
      const sorted = bucket.games
        .slice()
        .filter((g) => matchesBoardTimeFilter(g.commence_time, timeFilter))
        .sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime());
      flat.push(...sorted.slice(0, perSportCap));
    }
    return flat
      .sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime())
      .slice(0, globalCap);
  }, [featuredLineBuckets, showMoreFeaturedLines, timeFilter]);

  const allSides = useMemo(() => activeScanData?.sides ?? [], [activeScanData]);

  const activeLens = useMemo(() => {
    if (primaryMode !== "promos") return "standard";
    if (promosSubmode === "boosts") return "profit_boost";
    if (promosSubmode === "bonus_bets") return "bonus_bet";
    if (promosSubmode === "qualifiers") return "qualifier";
    return "standard";
  }, [primaryMode, promosSubmode]);

  const rankedSides = useMemo(() => {
    if (viewMode === "browse") {
      // Browse: all sides for selected books, ordered by game start
      return allSides
        .filter((s) => selectedBooks.includes(s.sportsbook))
        .sort((a, b) => {
          const ta = a.commence_time ? new Date(a.commence_time).getTime() : 0;
          const tb = b.commence_time ? new Date(b.commence_time).getTime() : 0;
          return ta - tb;
        });
    }

    const sidesForRanking = primaryMode === "promos" ? dedupePromoSidesByDuplicateState(allSides) : allSides;
    const ranked = rankScannerSidesByLens({
      sides: sidesForRanking,
      selectedBooks,
      activeLens,
      boostPercent: 30,
    });
    // Opportunities view guardrail: keep board quality high by hiding very small edges.
    // This is display-only and does not alter backend scan/research capture.
    if (activeLens === "standard") {
      return ranked.filter((s) => Number(s.ev_percentage || 0) > 1);
    }
    return ranked;
  }, [allSides, selectedBooks, viewMode, activeLens, primaryMode]);

  const filteredSides = useMemo(() => {
    const timeFiltered = rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, timeFilter));
    const marketFiltered =
      primaryMode === "player_props" && propMarketFilter !== "all"
        ? timeFiltered.filter(
            (s) => s.surface === "player_props" && (s as PlayerPropMarketSide).market_key === propMarketFilter,
          )
        : timeFiltered;
    if (!searchQuery.trim()) return marketFiltered;
    const q = searchQuery.toLowerCase();
    return marketFiltered.filter((s) => {
      const haystack = [
        s.event,
        s.event_short ?? "",
        s.sport,
        s.sportsbook,
        "player_name" in s ? (s as { player_name?: string }).player_name : "",
        "team" in s ? (s as { team?: string }).team : "",
        "team_short" in s ? (s as { team_short?: string }).team_short : "",
        "opponent" in s ? (s as { opponent?: string }).opponent : "",
        "opponent_short" in s ? (s as { opponent_short?: string }).opponent_short : "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [rankedSides, searchQuery, timeFilter, primaryMode, propMarketFilter]);

  const todayOpenCount = useMemo(
    () => rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, "today")).length,
    [rankedSides],
  );
  const todayClosedCount = useMemo(
    () => rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, "today_closed")).length,
    [rankedSides],
  );

  const filteredGameContextGames = useMemo(
    () => gameContextGames.filter((g) => matchesBoardTimeFilter(g.commence_time, timeFilter)),
    [gameContextGames, timeFilter],
  );
  const gameTodayOpenCount = useMemo(
    () => gameContextGames.filter((g) => matchesBoardTimeFilter(g.commence_time, "today")).length,
    [gameContextGames],
  );
  const gameTodayClosedCount = useMemo(
    () => gameContextGames.filter((g) => matchesBoardTimeFilter(g.commence_time, "today_closed")).length,
    [gameContextGames],
  );

  // Pick'em cards are derived from PlayerPropMarketSide sides (not prizepicks_cards).
  // buildPickEmBoardCards groups by player/market/line across books to build consensus cards.
  const pickEmCards = useMemo(() => {
    const propSides = allSides.filter(
      (s): s is PlayerPropMarketSide => s.surface === "player_props",
    ) as Array<PlayerPropMarketSide & { _retention?: number; _boostedEV?: number }>;
    return buildPickEmBoardCards(propSides);
  }, [allSides]);
  const filteredPickEmCards = useMemo(
    () => pickEmCards.filter((card) => matchesBoardTimeFilter(card.commence_time, timeFilter)),
    [pickEmCards, timeFilter],
  );
  const availablePropMarkets = useMemo(() => {
    const markets = new Set<string>();
    for (const market of PLAYER_PROP_MARKET_OPTIONS) {
      markets.add(market);
    }
    for (const side of allSides) {
      if (side.surface === "player_props") markets.add((side as PlayerPropMarketSide).market_key);
    }
    return Array.from(markets).sort();
  }, [allSides]);
  const activeFilterChips = useMemo(() => {
    const chips: string[] = [];
    if (timeFilter !== "today") {
      const label =
        timeFilter === "upcoming"
          ? "Upcoming"
          : timeFilter === "all_games"
            ? "All Games"
            : "Closed Today";
      chips.push(`Time: ${label}`);
    }
    const defaultBooks = primaryMode === "straight_bets" ? DEFAULT_STRAIGHT_BET_BOOKS : DEFAULT_PLAYER_PROP_BOOKS;
    if (!sameStringSet(selectedBooks, defaultBooks)) {
      chips.push(`Books: ${selectedBooks.length}`);
    }
    if (primaryMode === "player_props" && propMarketFilter !== "all") {
      chips.push(`Market: ${propMarketFilter.replaceAll("_", " ")}`);
    }
    return chips;
  }, [timeFilter, primaryMode, selectedBooks, propMarketFilter]);

  const resetFilters = () => {
    setTimeFilter("today");
    setPropMarketFilter("all");
    if (primaryMode === "straight_bets") {
      setSelectedGameLineBooks(DEFAULT_STRAIGHT_BET_BOOKS);
    } else {
      setSelectedPropBooks(DEFAULT_PLAYER_PROP_BOOKS);
    }
  };

  const isPickEmView = primaryMode === "player_props" && viewMode === "pickem";
  // rawSourceCount: keep aligned with ranked/source set so empty-state copy does not
  // misclassify "no opportunities" as "not pregame".
  const rawSourceCount = isPickEmView ? filteredPickEmCards.length : rankedSides.length;
  const sourceCount = isPickEmView ? filteredPickEmCards.length : rankedSides.length;
  const filteredCount = isPickEmView ? filteredPickEmCards.length : filteredSides.length;

  const nullState = useMemo(
    () => classifyScannerNullState({ sourceCount, filteredCount }),
    [sourceCount, filteredCount],
  );

  const results = useMemo(
    () => filteredSides.slice(0, visibleCount),
    [filteredSides, visibleCount],
  );
  const visiblePickEmCards = useMemo(
    () => filteredPickEmCards.slice(0, visibleCount),
    [filteredPickEmCards, visibleCount],
  );

  const canLoadMore = isPickEmView
    ? visiblePickEmCards.length < filteredPickEmCards.length
    : results.length < filteredSides.length;

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleViewModeChange = (mode: MarketsViewMode) => {
    setViewMode(mode);
    setVisibleCount(10);
    setSearchQuery("");
    if (mode === "opportunities" && timeFilter === "all_games") {
      setTimeFilter("today");
    }
    // Pick'em is only meaningful for player props — auto-switch surface
    if (mode === "pickem" && primaryMode === "straight_bets") {
      setPrimaryMode("player_props");
    }
  };

  const handleSurfaceModeChange = (newSurface: Exclude<PrimaryMode, "promos">) => {
    setPrimaryMode(newSurface);
    setVisibleCount(10);
    setSearchQuery("");
    if (newSurface === "straight_bets" && viewMode === "pickem") {
      setViewMode("opportunities");
    }
  };

  const handlePrimaryModeChange = (mode: PrimaryMode) => {
    setPrimaryMode(mode);
    setVisibleCount(10);
    setSearchQuery("");
    if (mode === "promos") {
      setViewMode("opportunities");
      return;
    }
    handleSurfaceModeChange(mode);
  };

  const handleLogBet = (side: MarketSide) => {
    const betData = buildScannerLogBetInitialValues({
      side,
      activeLens,
      boostPercent: 30,
      sportDisplayMap: SPORT_KEY_TO_DISPLAY,
      kellyMultiplier,
      bankroll,
    });
    setDrawerInitialValues(betData);
    setDrawerKey(Date.now());
    setDrawerOpen(true);
  };

  const handleBetLogged = () => {
    // Refresh duplicate-state tags without requiring a board refresh/rescan.
    // /api/scan-latest re-annotates sides for the current user, so "already_logged" updates immediately.
    void (async () => {
      try {
        if (primaryMode === "promos") {
          const [playerProps, straightBets] = await Promise.all([
            getLatestScan("player_props"),
            getLatestScan("straight_bets"),
          ]);
          setScanLatestOverride({
            player_props: playerProps,
            straight_bets: straightBets,
          });
          return;
        }

        if (primaryMode === "player_props") {
          const playerProps = await getLatestScan("player_props");
          setScanLatestOverride((prev) => ({
            player_props: playerProps,
            straight_bets: prev?.straight_bets ?? board?.straight_bets ?? null,
          }));
          return;
        }

        // straight_bets
        const straightBets = await getLatestScan("straight_bets");
        setScanLatestOverride((prev) => ({
          straight_bets: straightBets,
          player_props: prev?.player_props ?? board?.player_props ?? null,
        }));
      } catch {
        // Non-blocking: if refresh fails, user can still refresh later.
      }
    })();
  };

  const handleAddToCart = (side: MarketSide) => {
    if (!canAddScannerLensToParlayCart(activeLens)) {
      toast.error("Slip building is available from Opportunities and Browse lines.");
      return;
    }
    const result = addCartLeg(buildParlayCartLeg(side));
    if (!result.added) {
      const msg =
        result.reason === "sportsbook_mismatch"
          ? "All legs in a parlay slip must be from the same sportsbook."
          : result.reason === "slip_kind_mismatch"
            ? "Pick'em slips and priced parlay slips can't be mixed. Clear your slip to switch."
            : "That leg is already in your slip.";
      toast.error(msg);
      return;
    }
    toast.success(`Added to slip (${cart.length + 1} ${cart.length + 1 === 1 ? "leg" : "legs"})`);
  };

  const handleAddPickEmToSlip = (card: PickEmBoardCard) => {
    if (!canAddScannerLensToParlayCart(activeLens)) {
      toast.error("Slip building is available from Opportunities and Browse lines.");
      return;
    }
    const leg = buildParlayCartLegFromPickEmCard(card);
    if (!leg) {
      toast.error("Could not add this pick — missing best price for the consensus side.");
      return;
    }
    const result = addCartLeg(leg);
    if (!result.added) {
      const msg =
        result.reason === "sportsbook_mismatch"
          ? "All legs in a parlay slip must be from the same sportsbook."
          : result.reason === "slip_kind_mismatch"
            ? "Pick'em slips and priced parlay slips can't be mixed. Clear your slip to switch."
            : "That leg is already in your slip.";
      toast.error(msg);
      return;
    }
    setPickEmSlipKeys((prev) =>
      prev.includes(card.comparison_key) ? prev : [...prev, card.comparison_key],
    );
    const sideLabel = card.consensus_side === "over" ? "Over" : "Under";
    const pct = Math.round(
      (card.consensus_side === "over" ? card.consensus_over_prob : card.consensus_under_prob) * 100,
    );
    toast.success(`Added to slip (${cart.length + 1} ${cart.length + 1 === 1 ? "leg" : "legs"})`, {
      description: `${card.player_name} ${sideLabel} ${card.line_value} (${pct}%)`,
    });
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="container mx-auto max-w-2xl space-y-3 px-4 py-4">

      {/* ── Board header ─────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-col gap-0.5">
        <h1 className="text-base font-semibold text-foreground">Markets</h1>
        {isBoardLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading board…</p>
        ) : boardAgeMinutes !== null ? (
          <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <Clock className="h-3 w-3 shrink-0" />
            <span>
              Lines from {formatBoardAge(boardAgeMinutes)}
              {scanWindowLabel ? ` • ${scanWindowLabel}` : ""}
              {!scanWindowLabel ? ` • ${nextDropLabel}` : ""}
            </span>
          </p>
        ) : isEmptyBoard && !isBoardLoading ? (
          <p className="text-[11px] text-muted-foreground">
            No lines yet · scans daily ~10:30 AM / 3:30 PM AZ
          </p>
        ) : null}
      </div>

      {/* ── Row 1: Primary mode ───────────────────────────────────── */}
      <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
        {([
          { id: "player_props", label: "Player Props" },
          { id: "straight_bets", label: "Game Lines" },
          { id: "promos", label: "Promos" },
        ] as const).map((item) => (
          <button
            key={item.id}
            onClick={() => handlePrimaryModeChange(item.id)}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              primaryMode === item.id
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* ── Row 2: Contextual submode ─────────────────────────────── */}
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 no-scrollbar">
        {primaryMode !== "promos" &&
          VIEW_MODES
            .filter((mode) => mode.id !== "pickem" || primaryMode === "player_props")
            .map((mode) => (
              <button
                key={mode.id}
                onClick={() => handleViewModeChange(mode.id)}
                className={cn(
                  "shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                  viewMode === mode.id
                    ? "border-primary/40 bg-primary/10 text-foreground"
                    : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                )}
              >
                {mode.label}
              </button>
            ))}
        {primaryMode === "promos" && (
          <div className="w-full space-y-2">
            <p className="pl-0.5 text-xs font-medium text-muted-foreground">Lens</p>
            <div className="grid grid-cols-2 gap-2">
              {PROMOS_SUBMODES.map((mode) => {
                const Icon = mode.icon;
                const isActive = promosSubmode === mode.id;
                return (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => setPromosSubmode(mode.id)}
                    aria-pressed={isActive}
                    className={cn(
                      "rounded-lg border px-3 py-2.5 text-left transition-colors",
                      isActive
                        ? `${mode.activeBg} ${mode.activeBorder} ${mode.activeText}`
                        : "border-border bg-background text-foreground hover:bg-muted dark:bg-card dark:hover:bg-muted/60",
                    )}
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                        {mode.id === "all" ? "Core View" : "Specialty"}
                      </span>
                      {isActive && (
                        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          Active
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "inline-flex h-6 w-6 items-center justify-center rounded-md bg-background/70 dark:bg-background/40",
                          isActive ? mode.iconText : "text-muted-foreground",
                        )}
                      >
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="text-xs font-semibold leading-tight md:text-sm">{mode.label}</span>
                    </div>
                    <p className="mt-1 text-[11px] leading-tight text-muted-foreground">{mode.description}</p>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* ── Search + single Filters control ───────────────────────── */}
      {activeScanData !== null && !isPickEmView && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <input
              type="search"
              placeholder={
                primaryMode === "player_props"
                  ? "Search players, teams, events…"
                  : "Search teams, events…"
              }
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <button
              type="button"
              onClick={() => setFiltersOpen((prev) => !prev)}
              className={cn(
                "shrink-0 rounded-md border px-3 py-2 text-xs font-medium transition-colors",
                filtersOpen
                  ? "border-primary/40 bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
              )}
            >
              Filters
            </button>
          </div>
          {filtersOpen && (
            <div className="rounded-md border border-border bg-card p-3 space-y-3">
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Books</p>
                <div className="flex flex-wrap gap-1.5">
                  {(primaryMode === "straight_bets" ? STRAIGHT_BET_BOOKS : PLAYER_PROP_BOOKS).map((book) => {
                    const selected = selectedBooks.includes(book);
                    return (
                      <button
                        key={book}
                        type="button"
                        onClick={() =>
                          setSelectedBooks((prev) =>
                            prev.includes(book) ? prev.filter((b) => b !== book) : [...prev, book],
                          )
                        }
                        className={cn(
                          "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                          selected
                            ? `${BOOK_COLORS[book] || "bg-foreground"} text-white`
                            : "bg-muted text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {book}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Time</p>
                <div className="flex flex-wrap gap-1.5">
                  {(
                    viewMode === "browse"
                      ? [
                          { id: "today", label: "Today" },
                          { id: "upcoming", label: "Upcoming" },
                          { id: "all_games", label: "All Games" },
                        ]
                      : [
                          { id: "today", label: "Today" },
                          { id: "upcoming", label: "Upcoming" },
                        ]
                  ).map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => setTimeFilter(option.id as BoardTimeFilter)}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                        timeFilter === option.id
                          ? "border-primary/40 bg-primary/10 text-foreground"
                          : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              {primaryMode === "player_props" && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Market Type</p>
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => setPropMarketFilter("all")}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                        propMarketFilter === "all"
                          ? "border-primary/40 bg-primary/10 text-foreground"
                          : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                      )}
                    >
                      All
                    </button>
                    {availablePropMarkets.map((market) => (
                      <button
                        key={market}
                        type="button"
                        onClick={() => setPropMarketFilter(market)}
                        className={cn(
                          "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                          propMarketFilter === market
                            ? "border-primary/40 bg-primary/10 text-foreground"
                            : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                        )}
                      >
                        {formatMarketTypeLabel(market)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="pt-1">
                <button
                  type="button"
                  onClick={resetFilters}
                  className="text-xs font-medium text-muted-foreground hover:text-foreground underline underline-offset-2"
                >
                  Reset filters
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {!filtersOpen && activeFilterChips.length > 0 && (
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1.5">
            {activeFilterChips.map((chip) => (
              <span
                key={chip}
                className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] text-foreground"
              >
                {chip}
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={resetFilters}
            className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2"
          >
            Reset
          </button>
        </div>
      )}

      {/* ── Board error ───────────────────────────────────────────── */}
      {boardError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs text-destructive">
          Failed to load board:{" "}
          {boardError instanceof Error ? boardError.message : "Unknown error"}
        </div>
      )}

      {/*
       * ── Content area: mutually exclusive three-way guard ────────────────
       *
       *  1. Empty board  — no snapshot at all AND no scoped data to fall back on
       *  2. Surface empty — board exists but this surface (props vs game lines) has no data
       *  3. Results pane  — activated whenever any scan data is present (scoped or canonical)
       *
       * This prevents: (a) empty state + cards showing simultaneously,
       *                (b) blank page when board exists but surface field is null.
       */}

      {/* 1. No board snapshot yet */}
      {!isBoardLoading && isEmptyBoard && !boardError && activeScanData === null && (
        <div className="rounded-lg border border-border bg-card px-4 py-10 text-center">
          <Layers className="mx-auto mb-3 h-8 w-8 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">No lines loaded yet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Lines are loaded daily around 10:30 AM and 3:30 PM Arizona time.
          </p>
        </div>
      )}

      {/* 2. Board exists but this surface has no data in today's snapshot */}
      {!isBoardLoading && !isEmptyBoard && !boardError && activeScanData === null && (
        <div className="rounded-lg border border-border bg-card px-4 py-8 text-center">
          <p className="text-sm font-medium text-foreground">
            No {primaryMode === "promos" ? "Promos" : primaryMode === "straight_bets" ? "Game Lines" : "Player Props"} in today&apos;s board
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Today&apos;s scan did not include this market. Check back after the next daily drop.
          </p>
        </div>
      )}

      {/* 3. Results pane — any scan data present (scoped overlay or canonical) */}
      {activeScanData !== null && (
        <>
          {(primaryMode !== "straight_bets" || allSides.length > 0) && (
            <ScannerResultsPane
              surface={primaryMode === "player_props" ? "player_props" : "straight_bets"}
              playerPropsView={isPickEmView ? "pickem" : "sportsbooks"}
              activeLens={activeLens}
              results={results}
              pickemCards={isPickEmView ? visiblePickEmCards : []}
              sourceCount={sourceCount}
              rawSourceCount={rawSourceCount}
              filteredCount={filteredCount}
              nullState={nullState}
              activeResultFilterSummary=""
              kellyMultiplier={kellyMultiplier}
              bankroll={bankroll}
              boostPercent={30}
              addedPickEmComparisonKeys={pickEmSlipKeys}
              canLoadMore={canLoadMore}
              onLoadMore={() => setVisibleCount((v) => v + 10)}
              onLogBet={handleLogBet}
              onAddToCart={handleAddToCart}
              onStartPlaceFlow={handleLogBet}
              onAddPickEmToSlip={handleAddPickEmToSlip}
              bookColors={BOOK_COLORS}
              sportDisplayMap={SPORT_KEY_TO_DISPLAY}
            />
          )}
          {timeFilter === "today" && todayOpenCount === 0 && todayClosedCount > 0 && (
            <div className="rounded-md border border-border bg-card px-3 py-2 text-center">
              <p className="text-xs text-muted-foreground">No still-open markets today.</p>
              <button
                type="button"
                onClick={() => setTimeFilter("today_closed")}
                className="mt-1 text-xs font-medium text-foreground underline underline-offset-2"
              >
                View Closed Today
              </button>
            </div>
          )}
          {false && (
            <div className="rounded-lg border border-border bg-card px-4 py-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Featured Game Lines
                </p>
                <button
                  type="button"
                  onClick={() => setShowMoreFeaturedLines((prev) => !prev)}
                  className="text-[11px] text-muted-foreground hover:text-foreground"
                >
                  {showMoreFeaturedLines ? "Show less" : "Show more"}
                </button>
              </div>
              <div className="space-y-2">
                {featuredGames.map((game) => {
                  const kickoff = new Date(game.commence_time);
                  const kickoffLabel = Number.isNaN(kickoff.getTime())
                    ? ""
                    : kickoff.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
                  return (
                    <div key={`${game.sport}|${game.event}|${game.commence_time}`} className="rounded-md border border-border/70 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{game.event_short || game.event}</p>
                          <p className="text-[11px] text-muted-foreground">
                            {SPORT_KEY_TO_DISPLAY[game.sport] ?? game.sport}
                            {kickoffLabel ? ` • ${kickoffLabel}` : ""}
                          </p>
                        </div>
                        <div className="text-right text-[11px] text-muted-foreground">
                          <p>ML {game.h2h_offers.length}</p>
                          <p>Spr {game.spreads_offers.length} · Tot {game.totals_offers.length}</p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}

      {/* 3b. Game Lines — rendered from board.game_context (totals context) */}
      {primaryMode === "straight_bets" && !isBoardLoading && !boardError && allSides.length === 0 && (
        <div className="space-y-2">
          {filteredGameContextGames.length === 0 ? (
            <div className="rounded-lg border border-border bg-card px-4 py-8 text-center">
              <p className="text-sm font-medium text-foreground">No Game Lines in today&apos;s board</p>
              <p className="mt-1 text-xs text-muted-foreground">
                The daily drop did not include totals context yet. Check back after the next daily drop.
              </p>
              {timeFilter === "today" && gameTodayOpenCount === 0 && gameTodayClosedCount > 0 && (
                <button
                  type="button"
                  onClick={() => setTimeFilter("today_closed")}
                  className="mt-2 text-xs font-medium text-foreground underline underline-offset-2"
                >
                  View Closed Today
                </button>
              )}
            </div>
          ) : (
            filteredGameContextGames
              .slice()
              .sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime())
              .map((game) => {
                const kickoff = game.commence_time ? new Date(game.commence_time) : null;
                const kickoffLabel = kickoff && !Number.isNaN(kickoff.getTime())
                  ? kickoff.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })
                  : "";

                const offersByBook = new Map(game.totals_offers.map((o) => [o.sportsbook, o] as const));
                const pinnacle = offersByBook.get("Pinnacle") ?? null;
                const visibleOffers = selectedGameLineBooks
                  .map((book) => offersByBook.get(book))
                  .filter((o): o is TotalsOffer => Boolean(o));

                const totalLabel = (o: TotalsOffer | null) =>
                  o ? `${o.total}` : (pinnacle ? `${pinnacle.total}` : "");

                return (
                  <div key={`${game.event}|${game.commence_time}`} className="rounded-lg border border-border bg-card px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">{game.event_short || game.event}</p>
                        {kickoffLabel ? (
                          <p className="mt-0.5 text-[11px] text-muted-foreground">{kickoffLabel}</p>
                        ) : null}
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[11px] text-muted-foreground">Total</p>
                        <p className="text-sm font-semibold text-foreground">{totalLabel(pinnacle)}</p>
                      </div>
                    </div>

                    <div className="mt-3 space-y-2">
                      {pinnacle ? (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">Pinnacle</span>
                          <span className="text-muted-foreground">O {pinnacle.over_odds} · U {pinnacle.under_odds}</span>
                        </div>
                      ) : null}

                      {visibleOffers.map((o) => (
                        <div key={o.sportsbook} className="flex items-center justify-between text-xs">
                          <span className="text-foreground">{o.sportsbook}</span>
                          <span className="text-muted-foreground">O {o.over_odds} · U {o.under_odds}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })
          )}
        </div>
      )}

      <LogBetDrawer
        key={drawerKey}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        initialValues={drawerInitialValues}
        onLogged={handleBetLogged}
      />
    </div>
  );
}
