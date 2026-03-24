import { useQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api";
import {
  markParlaySlipLoggedInCache,
  removeParlaySlipFromCache,
  upsertParlaySlipCache,
} from "@/lib/parlay-slip-cache";
import type {
  BetCreate,
  BetUpdate,
  BetResult,
  ParlaySlip,
  ParlaySlipCreate,
  ParlaySlipLogRequest,
  ParlaySlipUpdate,
  PromoType,
  ScannerSurface,
  TransactionCreate,
} from "@/lib/types";

// Query keys
export const queryKeys = {
  bets: ["bets"] as const,
  bet: (id: string) => ["bets", id] as const,
  summary: ["summary"] as const,
  backendReadiness: ["backend-readiness"] as const,
  operatorStatus: ["operator-status"] as const,
  researchOpportunitySummary: ["research-opportunity-summary"] as const,
  parlaySlips: ["parlay-slips"] as const,
  settings: ["settings"] as const,
  transactions: ["transactions"] as const,
  balances: ["balances"] as const,
  scanMarkets: (surface: ScannerSurface) => ["scan-markets", surface] as const,
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
    onSuccess: () => {
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

export function useResearchOpportunitySummary() {
  return useQuery({
    queryKey: queryKeys.researchOpportunitySummary,
    queryFn: api.getResearchOpportunitySummary,
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

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: api.getSettings,
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

export function useBalances() {
  return useQuery({
    queryKey: queryKeys.balances,
    queryFn: api.getBalances,
  });
}
