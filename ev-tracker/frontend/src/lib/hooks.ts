import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api";
import type { BetCreate, BetUpdate, BetResult, PromoType, TransactionCreate } from "@/lib/types";

// Query keys
export const queryKeys = {
  bets: ["bets"] as const,
  bet: (id: string) => ["bets", id] as const,
  summary: ["summary"] as const,
  settings: ["settings"] as const,
  transactions: ["transactions"] as const,
  balances: ["balances"] as const,
};

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
      // Invalidate and refetch bets list and summary
      queryClient.invalidateQueries({ queryKey: queryKeys.bets });
      queryClient.invalidateQueries({ queryKey: queryKeys.summary });
    },
  });
}

export function useUpdateBet() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: BetUpdate }) =>
      api.updateBet(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.bets });
      queryClient.invalidateQueries({ queryKey: queryKeys.bet(id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.summary });
    },
  });
}

export function useUpdateBetResult() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, result }: { id: string; result: BetResult }) =>
      api.updateBetResult(id, result),
    // Optimistic update for instant feedback
    onMutate: async ({ id, result }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.bets });

      const previousBets = queryClient.getQueryData(queryKeys.bets);

      // Optimistically update the bet result
      queryClient.setQueryData(queryKeys.bets, (old: any) => {
        if (!old) return old;
        return old.map((bet: any) =>
          bet.id === id ? { ...bet, result } : bet
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
      queryClient.invalidateQueries({ queryKey: queryKeys.bets });
      queryClient.invalidateQueries({ queryKey: queryKeys.summary });
    },
  });
}

export function useDeleteBet() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.deleteBet(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.bets });
      queryClient.invalidateQueries({ queryKey: queryKeys.summary });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.transactions });
      queryClient.invalidateQueries({ queryKey: queryKeys.balances });
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
      queryClient.setQueryData(queryKeys.transactions, (old: any) => {
        if (!old) return old;
        return old.filter((tx: any) => tx.id !== id);
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
      queryClient.invalidateQueries({ queryKey: queryKeys.transactions });
      queryClient.invalidateQueries({ queryKey: queryKeys.balances });
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
