import { useInfiniteQuery, useQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api";
import {
  markParlaySlipLoggedInCache,
  removeParlaySlipFromCache,
  upsertParlaySlipCache,
} from "@/lib/parlay-slip-cache";
import type {
  Balance,
  Bet,
  BetCreate,
  BetResult,
  BetUpdate,
  BoardPromosResponse,
  ParlaySlip,
  ParlaySlipCreate,
  ParlaySlipLogRequest,
  ParlaySlipUpdate,
  PlayerPropBoardDetail,
  PlayerPropBoardItem,
  PlayerPropBoardPageResponse,
  PlayerPropBoardPickEmCard,
  PromoType,
  ScannerSurface,
  Settings,
  OnboardingState,
  Summary,
  TransactionCreate,
} from "@/lib/types";
// BoardResponse / ScopedRefreshResponse used via api return types (inferred)

// Query keys
export const queryKeys = {
  bets: ["bets"] as const,
  bet: (id: string) => ["bets", id] as const,
  summary: ["summary"] as const,
  backendReadiness: ["backend-readiness"] as const,
  operatorStatus: ["operator-status"] as const,
  researchOpportunitySummary: ["research-opportunity-summary"] as const,
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
      market: string;
      search: string;
      tzOffsetMinutes: number;
    },
  ) => ["board_player_props", view, params] as const,
  boardPlayerPropDetail: (selectionKey: string, sportsbook: string) =>
    ["board_player_prop_detail", selectionKey, sportsbook] as const,
  boardPromos: (limit: number) => ["board_promos", limit] as const,
};

function invalidateBetDerivedQueries(queryClient: QueryClient, betId?: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.bets });
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

type BetListFilters = {
  sport?: string;
  sportsbook?: string;
  result?: BetResult;
};

let createBetInvalidateTimer: ReturnType<typeof setTimeout> | null = null;

function roundTo(value: number, digits: number = 2) {
  return Number(value.toFixed(digits));
}

function readBetListFilters(queryKey: readonly unknown[]): BetListFilters | null {
  if (queryKey.length !== 2) return null;

  const raw = queryKey[1];
  if (raw == null) return {};
  if (typeof raw !== "object" || Array.isArray(raw)) return null;

  const candidate = raw as {
    sport?: unknown;
    sportsbook?: unknown;
    result?: unknown;
  };

  return {
    sport: typeof candidate.sport === "string" ? candidate.sport : undefined,
    sportsbook: typeof candidate.sportsbook === "string" ? candidate.sportsbook : undefined,
    result: typeof candidate.result === "string" ? (candidate.result as BetResult) : undefined,
  };
}

function matchesBetListFilters(bet: Bet, filters: BetListFilters) {
  if (filters.sport && bet.sport !== filters.sport) return false;
  if (filters.sportsbook && bet.sportsbook !== filters.sportsbook) return false;
  if (filters.result && bet.result !== filters.result) return false;
  return true;
}

function applyCreatedBetToBetCaches(queryClient: QueryClient, createdBet: Bet) {
  queryClient.setQueryData(queryKeys.bet(createdBet.id), createdBet);

  for (const [queryKey, cached] of queryClient.getQueriesData<Bet[]>({ queryKey: queryKeys.bets })) {
    if (!Array.isArray(queryKey) || !Array.isArray(cached)) continue;
    const filters = readBetListFilters(queryKey);
    if (filters === null || !matchesBetListFilters(createdBet, filters)) continue;

    queryClient.setQueryData<Bet[]>(queryKey, (current) => {
      if (!Array.isArray(current)) return current;
      const withoutDuplicate = current.filter((bet) => bet.id !== createdBet.id);
      return [createdBet, ...withoutDuplicate];
    });
  }
}

function applyCreatedBetToSummaryCache(queryClient: QueryClient, createdBet: Bet) {
  queryClient.setQueryData<Summary>(queryKeys.summary, (current) => {
    if (!current) return current;

    const totalEv = roundTo(current.total_ev + createdBet.ev_total);
    const totalRealProfit = current.total_real_profit;

    return {
      ...current,
      total_bets: current.total_bets + 1,
      pending_bets: createdBet.result === "pending" ? current.pending_bets + 1 : current.pending_bets,
      total_ev: totalEv,
      total_real_profit: totalRealProfit,
      variance: roundTo(totalRealProfit - totalEv),
      ev_by_sportsbook: {
        ...current.ev_by_sportsbook,
        [createdBet.sportsbook]: roundTo((current.ev_by_sportsbook[createdBet.sportsbook] ?? 0) + createdBet.ev_total),
      },
      ev_by_sport: {
        ...current.ev_by_sport,
        [createdBet.sport]: roundTo((current.ev_by_sport[createdBet.sport] ?? 0) + createdBet.ev_total),
      },
    };
  });
}

function applyCreatedBetToBalancesCache(queryClient: QueryClient, createdBet: Bet) {
  const pendingDelta = createdBet.result === "pending" && createdBet.promo_type !== "bonus_bet"
    ? createdBet.stake
    : 0;
  if (pendingDelta === 0) return;

  queryClient.setQueryData<Balance[]>(queryKeys.balances, (current) => {
    if (!Array.isArray(current)) return current;

    let found = false;
    const next = current.map((balance) => {
      if (balance.sportsbook !== createdBet.sportsbook) return balance;
      found = true;
      const pending = roundTo(balance.pending + pendingDelta);
      return {
        ...balance,
        pending,
        balance: roundTo(balance.net_deposits + balance.profit - pending),
      };
    });

    if (!found) {
      next.push({
        sportsbook: createdBet.sportsbook,
        deposits: 0,
        withdrawals: 0,
        net_deposits: 0,
        profit: 0,
        pending: roundTo(pendingDelta),
        balance: roundTo(-pendingDelta),
      });
      next.sort((a, b) => a.sportsbook.localeCompare(b.sportsbook));
    }

    return next;
  });
}

function scheduleCreateBetRevalidation(queryClient: QueryClient, betId: string) {
  if (createBetInvalidateTimer) {
    clearTimeout(createBetInvalidateTimer);
  }

  createBetInvalidateTimer = setTimeout(() => {
    invalidateBetDerivedQueries(queryClient, betId);
    createBetInvalidateTimer = null;
  }, 1200);
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

export function useCreateBet() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (bet: BetCreate) => api.createBet(bet),
    onSuccess: (createdBet) => {
      applyCreatedBetToBetCaches(queryClient, createdBet);
      applyCreatedBetToSummaryCache(queryClient, createdBet);
      applyCreatedBetToBalancesCache(queryClient, createdBet);
      scheduleCreateBetRevalidation(queryClient, createdBet.id);
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

export function useResearchOpportunitySummary(filters?: {
  model_version?: string;
  capture_class?: string;
  cohort_mode?: string;
}) {
  return useQuery({
    queryKey: [
      ...queryKeys.researchOpportunitySummary,
      filters?.model_version ?? null,
      filters?.capture_class ?? null,
      filters?.cohort_mode ?? null,
    ],
    queryFn: () => api.getResearchOpportunitySummary(filters),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function useModelCalibrationSummary() {
  return useQuery({
    queryKey: queryKeys.modelCalibrationSummary,
    queryFn: api.getModelCalibrationSummary,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });
}

export function usePickEmResearchSummary() {
  return useQuery({
    queryKey: queryKeys.pickEmResearchSummary,
    queryFn: api.getPickEmResearchSummary,
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

export function useSettings(enabled: boolean = true) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: api.getSettings,
    enabled: enabled && backendOk,
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

export function useOnboardingState(enabled: boolean = true) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  return useQuery<OnboardingState>({
    queryKey: queryKeys.onboardingState,
    queryFn: api.getOnboardingState,
    enabled: enabled && backendOk,
  });
}

export function useApplyOnboardingEvent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.applyOnboardingEvent,
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

export function useTransactions(sportsbook?: string) {
  return useQuery({
    queryKey: [...queryKeys.transactions, sportsbook],
    queryFn: () => api.getTransactions(sportsbook),
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

export function useBalances(enabled: boolean = true) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  return useQuery({
    queryKey: queryKeys.balances,
    queryFn: api.getBalances,
    enabled: enabled && backendOk,
  });
}

// ============ Board Hooks ============

/** Load the canonical board snapshot. staleTime: Infinity — invalidated by Supabase realtime or explicit refresh. */
export function useBoard(enabled: boolean = true) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  return useQuery({
    queryKey: queryKeys.board,
    queryFn: api.getBoard,
    enabled: enabled && backendOk,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });
}

export function useBoardSurface(surface: ScannerSurface, enabled: boolean) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  return useQuery({
    queryKey: queryKeys.boardSurface(surface),
    queryFn: () => api.getBoardSurface(surface),
    enabled: enabled && backendOk,
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
  market: string;
  search: string;
  tzOffsetMinutes: number;
  enabled: boolean;
}) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  const queryParams = {
    pageSize: params.pageSize,
    books: [...params.books].sort(),
    timeFilter: params.timeFilter,
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
    enabled: params.enabled && backendOk,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    placeholderData: (previousData) => previousData,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });
}

export function useBoardPromos(limit: number, enabled: boolean = true) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  return useQuery<BoardPromosResponse>({
    queryKey: queryKeys.boardPromos(limit),
    queryFn: () => api.getBoardPromos(limit),
    enabled: enabled && backendOk,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });
}

export function useBoardPlayerPropDetail(
  selectionKey: string,
  sportsbook: string,
  enabled: boolean = true,
) {
  const readiness = useBackendReadiness();
  const backendOk = readiness.data?.status === "ready";
  return useQuery<PlayerPropBoardDetail>({
    queryKey: queryKeys.boardPlayerPropDetail(selectionKey, sportsbook),
    queryFn: () => api.getBoardPlayerPropDetail({ selectionKey, sportsbook }),
    enabled: enabled && backendOk && !!selectionKey && !!sportsbook,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });
}

/** Scoped manual refresh - does NOT overwrite the canonical board:latest. */
export function useRefreshBoard() {
  return useMutation({
    mutationFn: (scope: ScannerSurface) => api.refreshBoard(scope),
  });
}



