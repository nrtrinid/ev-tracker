import { useInfiniteQuery, useQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api";
import { sendAnalyticsEvent } from "@/lib/analytics";
import {
  markParlaySlipLoggedInCache,
  removeParlaySlipFromCache,
  upsertParlaySlipCache,
} from "@/lib/parlay-slip-cache";
import type {
  BetCreate,
  BetUpdate,
  BetResult,
  OnboardingEventRequest,
  OnboardingState,
  PlayerPropBoardItem,
  PlayerPropBoardPageResponse,
  PlayerPropBoardPickEmCard,
  ParlaySlip,
  ParlaySlipCreate,
  ParlaySlipLogRequest,
  ParlaySlipUpdate,
  PromoType,
  Settings,
  ScannerSurface,
  TransactionCreate,
  AnalyticsAudience,
} from "@/lib/types";

// Query keys
export const queryKeys = {
  bets: ["bets"] as const,
  bet: (id: string) => ["bets", id] as const,
  betLiveSnapshots: ["bets", "live"] as const,
  summary: ["summary"] as const,
  backendReadiness: ["backend-readiness"] as const,
  operatorStatus: ["operator-status"] as const,
  altPitcherKLookup: (params: {
    player_name: string;
    team?: string | null;
    opponent?: string | null;
    line_value: number;
    game_date?: string | null;
  }) => ["alt-pitcher-k-lookup", params] as const,
  analyticsSummary: (windowDays: number, audience: AnalyticsAudience) =>
    ["analytics-summary", windowDays, audience] as const,
  analyticsUserDrilldown: (
    windowDays: number,
    maxUsers: number,
    timelineLimit: number,
    audience: AnalyticsAudience,
  ) => ["analytics-user-drilldown", windowDays, maxUsers, timelineLimit, audience] as const,
  researchOpportunitySummary: (scope: "all" | "board_default") => ["research-opportunity-summary", scope] as const,
  modelCalibrationSummary: ["model-calibration-summary"] as const,
  pickEmResearchSummary: ["pickem-research-summary"] as const,
  parlaySlips: ["parlay-slips"] as const,
  onboardingState: ["onboarding-state"] as const,
  settings: ["settings"] as const,
  transactions: ["transactions"] as const,
  balances: ["balances"] as const,
  scanMarkets: (surface: ScannerSurface) => ["scan-markets", surface] as const,
  board: ["board"] as const,
  boardSurface: (surface: ScannerSurface) => ["board_surface", surface] as const,
  boardPlayerProps: (
    view: "opportunities" | "browse" | "pickem",
    params: {
      pageSize: number;
      books: string[];
      timeFilter: string;
      sport: string;
      market: string;
      search: string;
      tzOffsetMinutes: number;
    },
  ) => ["board_player_props", view, params] as const,
  boardPlayerPropDetail: (selectionKey: string, sportsbook: string) =>
    ["board_player_prop_detail", selectionKey, sportsbook] as const,
};

function invalidateBetDerivedQueries(queryClient: QueryClient, betId?: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.bets });
  queryClient.invalidateQueries({ queryKey: queryKeys.betLiveSnapshots });
  if (betId) {
    queryClient.invalidateQueries({ queryKey: queryKeys.bet(betId) });
  }
  queryClient.invalidateQueries({ queryKey: queryKeys.summary });
  queryClient.invalidateQueries({ queryKey: queryKeys.balances });
}

function invalidateTransactionDerivedQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: queryKeys.transactions });
  queryClient.invalidateQueries({ queryKey: queryKeys.balances });
}

// ============ Bets Hooks ============

export function useBets(filters?: {
  sport?: string;
  sportsbook?: string;
  result?: BetResult;
}) {
  return useQuery({
    queryKey: [...queryKeys.bets, filters],
    queryFn: () => api.getBets(filters),
  });
}

export function useBet(id: string) {
  return useQuery({
    queryKey: queryKeys.bet(id),
    queryFn: () => api.getBet(id),
    enabled: !!id,
  });
}

export function useBetLiveSnapshots(options?: {
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: queryKeys.betLiveSnapshots,
    queryFn: () => api.getBetLiveSnapshots(),
    enabled: options?.enabled ?? true,
    refetchInterval: 60_000,
  });
}

export function useCreateBet() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (bet: BetCreate) => api.createBet(bet),
    onSuccess: (createdBet) => {
      const route = typeof window !== "undefined" ? window.location.pathname : "/";
      const betId = typeof createdBet?.id === "string" ? createdBet.id : null;
      void sendAnalyticsEvent({
        eventName: "bet_logged",
        route,
        appArea: "tracker",
        properties: {
          surface: createdBet?.surface,
          sport: createdBet?.sport,
          market: createdBet?.market,
          sportsbook: createdBet?.sportsbook,
          source_market_key: createdBet?.source_market_key,
          source_selection_key: createdBet?.source_selection_key,
          selection_side: createdBet?.selection_side,
          line_value: createdBet?.line_value,
          scan_ev_percent_at_log: createdBet?.scan_ev_percent_at_log,
        },
        ...(betId ? { dedupeKey: `bet-logged:${betId}` } : {}),
      });

      invalidateBetDerivedQueries(queryClient);
    },
  });
}

export function useUpdateBet() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: BetUpdate }) =>
      api.updateBet(id, data),
    onSuccess: (_, { id }) => {
      invalidateBetDerivedQueries(queryClient, id);
    },
  });
}

export function useUpdateBetResult() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, result }: { id: string; result: BetResult }) =>
      api.updateBetResult(id, result),
    // Optimistic update for instant feedback
    onMutate: async ({ result }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.bets });

      const previousBets = queryClient.getQueryData(queryKeys.bets);

      // Optimistically update the bet result
      queryClient.setQueryData(queryKeys.bets, (old: unknown) => {
        if (!Array.isArray(old)) return old;
        return old.map((bet) =>
          typeof bet === 'object' && bet !== null ? { ...bet, result } : bet
        );
      });

      return { previousBets };
    },
    onError: (_, __, context) => {
      // Rollback on error
      if (context?.previousBets) {
        queryClient.setQueryData(queryKeys.bets, context.previousBets);
      }
    },
    onSettled: () => {
      invalidateBetDerivedQueries(queryClient);
    },
  });
}

export function useDeleteBet() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.deleteBet(id),
    onSuccess: () => {
      invalidateBetDerivedQueries(queryClient);
    },
  });
}

// ============ Summary Hook ============

export function useSummary() {
  return useQuery({
    queryKey: queryKeys.summary,
    queryFn: api.getSummary,
  });
}

export function useBackendReadiness() {
  return useQuery({
    queryKey: queryKeys.backendReadiness,
    queryFn: api.getBackendReadiness,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 0,
  });
}

export function useOperatorStatus() {
  return useQuery({
    queryKey: queryKeys.operatorStatus,
    queryFn: api.getOperatorStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function useAltPitcherKLookup(
  params: {
    player_name: string;
    team?: string | null;
    opponent?: string | null;
    line_value: number;
    game_date?: string | null;
  } | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: queryKeys.altPitcherKLookup(
      params ?? {
        player_name: "",
        line_value: 0,
      },
    ),
    queryFn: () => {
      if (!params) {
        throw new Error("Lookup parameters are required");
      }
      return api.getAltPitcherKLookup(params);
    },
    enabled: enabled && !!params,
    staleTime: 0,
    retry: 0,
  });
}

export function useAnalyticsSummary(
  windowDays: number = 7,
  audience: AnalyticsAudience = "external",
) {
  return useQuery({
    queryKey: queryKeys.analyticsSummary(windowDays, audience),
    queryFn: () => api.getAnalyticsSummary(windowDays, audience),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function useAnalyticsUserDrilldown(
  windowDays: number = 7,
  maxUsers: number = 25,
  timelineLimit: number = 12,
  audience: AnalyticsAudience = "external",
) {
  return useQuery({
    queryKey: queryKeys.analyticsUserDrilldown(windowDays, maxUsers, timelineLimit, audience),
    queryFn: () => api.getAnalyticsUserDrilldown(windowDays, maxUsers, timelineLimit, audience),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function useResearchOpportunitySummary(options?: {
  enabled?: boolean;
  scope?: "all" | "board_default";
}) {
  const enabled = options?.enabled ?? true;
  const scope = options?.scope ?? "all";

  return useQuery({
    queryKey: queryKeys.researchOpportunitySummary(scope),
    queryFn: () => api.getResearchOpportunitySummary({ scope }),
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function useModelCalibrationSummary(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.modelCalibrationSummary,
    queryFn: api.getModelCalibrationSummary,
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function usePickEmResearchSummary(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.pickEmResearchSummary,
    queryFn: api.getPickEmResearchSummary,
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function useParlaySlips() {
  return useQuery({
    queryKey: queryKeys.parlaySlips,
    queryFn: api.getParlaySlips,
  });
}

export function useCreateParlaySlip() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: ParlaySlipCreate) => api.createParlaySlip(payload),
    onSuccess: (savedSlip) => {
      queryClient.setQueryData(queryKeys.parlaySlips, (current: ParlaySlip[] | undefined) => (
        upsertParlaySlipCache(current, savedSlip)
      ));
      queryClient.invalidateQueries({ queryKey: queryKeys.parlaySlips });
    },
  });
}

export function useUpdateParlaySlip() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ParlaySlipUpdate }) => api.updateParlaySlip(id, data),
    onSuccess: (savedSlip) => {
      queryClient.setQueryData(queryKeys.parlaySlips, (current: ParlaySlip[] | undefined) => (
        upsertParlaySlipCache(current, savedSlip)
      ));
      queryClient.invalidateQueries({ queryKey: queryKeys.parlaySlips });
    },
  });
}

export function useDeleteParlaySlip() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.deleteParlaySlip(id),
    onSuccess: (_, slipId) => {
      queryClient.setQueryData(queryKeys.parlaySlips, (current: ParlaySlip[] | undefined) => (
        removeParlaySlipFromCache(current, slipId)
      ));
      queryClient.invalidateQueries({ queryKey: queryKeys.parlaySlips });
    },
  });
}

export function useLogParlaySlip() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ParlaySlipLogRequest }) => api.logParlaySlip(id, data),
    onSuccess: (loggedBet, { id }) => {
      queryClient.setQueryData(queryKeys.parlaySlips, (current: ParlaySlip[] | undefined) => (
        markParlaySlipLoggedInCache(current, {
          slipId: id,
          loggedBetId: loggedBet.id,
        })
      ));
      queryClient.invalidateQueries({ queryKey: queryKeys.parlaySlips });
      invalidateBetDerivedQueries(queryClient);
    },
  });
}

// ============ Settings Hooks ============

export function useSettings(options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true;

  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: api.getSettings,
    enabled,
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings });
      // Also invalidate bets since EV calculations depend on settings
      queryClient.invalidateQueries({ queryKey: queryKeys.bets });
      queryClient.invalidateQueries({ queryKey: queryKeys.summary });
    },
  });
}

export function useOnboardingState() {
  return useQuery({
    queryKey: queryKeys.onboardingState,
    queryFn: api.getOnboardingState,
  });
}

function applyOptimisticOnboardingEvent(
  current: OnboardingState | null | undefined,
  payload: OnboardingEventRequest,
): OnboardingState {
  const nowIso = new Date().toISOString();
  const completed = current?.completed ?? [];
  const dismissed = current?.dismissed ?? [];
  const version = current?.version ?? 2;

  if (payload.event === "reset") {
    return {
      version,
      completed: [],
      dismissed: [],
      last_seen_at: nowIso,
    };
  }

  if (!payload.step) {
    return {
      version,
      completed,
      dismissed,
      last_seen_at: nowIso,
    };
  }

  if (payload.event === "complete_step") {
    const nextCompleted = completed.includes(payload.step)
      ? completed
      : [...completed, payload.step];
    return {
      version,
      completed: nextCompleted,
      dismissed: dismissed.filter((step) => step !== payload.step),
      last_seen_at: nowIso,
    };
  }

  if (payload.event === "dismiss_step") {
    if (completed.includes(payload.step) || dismissed.includes(payload.step)) {
      return {
        version,
        completed,
        dismissed,
        last_seen_at: nowIso,
      };
    }

    return {
      version,
      completed,
      dismissed: [...dismissed, payload.step],
      last_seen_at: nowIso,
    };
  }

  return {
    version,
    completed,
    dismissed,
    last_seen_at: nowIso,
  };
}

export function useApplyOnboardingEvent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.applyOnboardingEvent,
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.onboardingState });
      await queryClient.cancelQueries({ queryKey: queryKeys.settings });

      const previousOnboardingState = queryClient.getQueryData<OnboardingState>(queryKeys.onboardingState);
      const previousSettings = queryClient.getQueryData<Settings>(queryKeys.settings);
      const baselineState = previousOnboardingState ?? previousSettings?.onboarding_state ?? null;
      const optimisticState = applyOptimisticOnboardingEvent(baselineState, payload);

      queryClient.setQueryData(queryKeys.onboardingState, optimisticState);
      queryClient.setQueryData(queryKeys.settings, (current: Settings | undefined) => {
        if (!current) return current;
        return {
          ...current,
          onboarding_state: optimisticState,
        };
      });

      return {
        previousOnboardingState,
        previousSettings,
      };
    },
    onError: (_error, _payload, context) => {
      if (!context) return;

      queryClient.setQueryData(queryKeys.onboardingState, context.previousOnboardingState);
      queryClient.setQueryData(queryKeys.settings, context.previousSettings);
    },
    onSuccess: (nextState) => {
      queryClient.setQueryData(queryKeys.onboardingState, nextState);
      queryClient.setQueryData(queryKeys.settings, (current: Settings | undefined) => {
        if (!current) return current;
        return {
          ...current,
          onboarding_state: nextState,
        };
      });
    },
  });
}

// ============ EV Calculator Hook ============

export function useEVCalculation(params: {
  odds_american: number;
  stake: number;
  promo_type: PromoType;
  boost_percent?: number;
  winnings_cap?: number;
} | null) {
  return useQuery({
    queryKey: ["ev-calculation", params],
    queryFn: () => api.calculateEV(params!),
    enabled: !!params && params.odds_american !== 0 && params.stake > 0,
    staleTime: Infinity, // EV calculations are deterministic
  });
}

// ============ Transactions Hooks ============

export function useTransactions(sportsbook?: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: [...queryKeys.transactions, sportsbook],
    queryFn: () => api.getTransactions(sportsbook),
    enabled: options?.enabled ?? true,
  });
}

export function useCreateTransaction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (transaction: TransactionCreate) => api.createTransaction(transaction),
    onSuccess: () => {
      invalidateTransactionDerivedQueries(queryClient);
    },
  });
}

export function useDeleteTransaction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.deleteTransaction(id),
    // Optimistic update for instant feedback
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.transactions });
      await queryClient.cancelQueries({ queryKey: queryKeys.balances });

      const previousTransactions = queryClient.getQueryData(queryKeys.transactions);
      const previousBalances = queryClient.getQueryData(queryKeys.balances);

      // Optimistically remove the transaction
      queryClient.setQueryData(queryKeys.transactions, (old: unknown) => {
        if (!Array.isArray(old)) return old;
        return old.filter((tx) => typeof tx === 'object' && tx !== null && 'id' in tx && tx.id !== id);
      });

      return { previousTransactions, previousBalances };
    },
    onError: (_, __, context) => {
      // Rollback on error
      if (context?.previousTransactions) {
        queryClient.setQueryData(queryKeys.transactions, context.previousTransactions);
      }
      if (context?.previousBalances) {
        queryClient.setQueryData(queryKeys.balances, context.previousBalances);
      }
    },
    onSettled: () => {
      // Refetch to ensure consistency
      invalidateTransactionDerivedQueries(queryClient);
    },
  });
}

// ============ Balances Hook ============

export function useBalances(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.balances,
    queryFn: api.getBalances,
    enabled: options?.enabled ?? true,
  });
}

// ============ Board Hooks ============

/** Load the canonical board snapshot. staleTime: Infinity - invalidated by explicit refresh/realtime. */
export function useBoard(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.board,
    queryFn: api.getBoard,
    enabled,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });
}

export function useBoardSurface(surface: ScannerSurface, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.boardSurface(surface),
    queryFn: () => api.getBoardSurface(surface),
    enabled,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });
}

export function useInfiniteBoardPlayerPropsView(params: {
  view: "opportunities" | "browse" | "pickem";
  pageSize: number;
  books: string[];
  timeFilter: string;
  sport: string;
  market: string;
  search: string;
  tzOffsetMinutes: number;
  enabled: boolean;
}) {
  const queryParams = {
    pageSize: params.pageSize,
    books: [...params.books].sort(),
    timeFilter: params.timeFilter,
    sport: params.sport,
    market: params.market,
    search: params.search,
    tzOffsetMinutes: params.tzOffsetMinutes,
  };

  return useInfiniteQuery<
    PlayerPropBoardPageResponse<PlayerPropBoardItem> | PlayerPropBoardPageResponse<PlayerPropBoardPickEmCard> | null
  >({
    queryKey: queryKeys.boardPlayerProps(params.view, queryParams),
    queryFn: ({ pageParam }) => {
      const requestParams = {
        ...queryParams,
        page: Number(pageParam),
      };
      if (params.view === "opportunities") {
        return api.getBoardPlayerPropOpportunities(requestParams);
      }
      if (params.view === "browse") {
        return api.getBoardPlayerPropBrowse(requestParams);
      }
      return api.getBoardPlayerPropPickem(requestParams);
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage?.has_more) return undefined;
      return allPages.length + 1;
    },
    enabled: params.enabled,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    placeholderData: (previousData) => previousData,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });
}
