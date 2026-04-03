import type { Balance, Bet, Settings } from "@/lib/types";
import { getTrackerSource, type TrackerSource } from "@/lib/tracker-source";

export type StatsSourceCategory = TrackerSource;
export type StatsChartFilter = "all" | TrackerSource;
export type VerdictState = "hot" | "on_track" | "cold_but_okay" | "worth_reviewing";

export type VerdictSummary = {
  state: VerdictState;
  label: string;
  copy: string;
};

export type SourceTotals = {
  ev: number;
  profit: number;
};

export type StatsChartPoint = {
  dateKey: string;
  dateLabel: string;
  cumulativeEv: number;
  cumulativeProfit: number;
  varianceLow: number;
  varianceHigh: number;
  bandBase: number;
  bandSize: number;
};

export type ProcessStatsModel = {
  beatClosePct: number | null;
  avgClvPct: number | null;
  trackedCloseCount: number;
  validCloseCount: number;
  closeCoveragePct: number | null;
  avgEdgePct: number | null;
  actualWinRatePct: number | null;
  expectedWinRatePct: number | null;
  winRateSampleCount: number;
};

export type BankrollDetailsBook = {
  sportsbook: string;
  deposits: number;
  withdrawals: number;
  pending: number;
  balance: number;
};

export type BankrollDetailsModel = {
  total: number | null;
  books: BankrollDetailsBook[];
  sizingMode: "computed" | "override" | null;
  bankrollOverride: number | null;
};

export type StatsPageModel = {
  bankroll: number | null;
  totalBetsLogged: number;
  settledBetsCount: number;
  profit: number;
  sevenDayProfitChange: number;
  atRisk: number;
  pendingEv: number;
  evEarned: number;
  normalSwing: number;
  verdict: VerdictSummary;
  chartSeriesByFilter: Record<StatsChartFilter, StatsChartPoint[]>;
  sourceBreakdown: Record<TrackerSource, SourceTotals>;
  processStats: ProcessStatsModel;
  bankrollDetails: BankrollDetailsModel;
  hasSettledData: boolean;
  showProcessStatsRow: boolean;
};

export const STATS_VERDICT_CONSTANTS = {
  varianceBandSigma: 1,
  hotBufferFraction: 0.15,
  reviewBufferFraction: 0.15,
  coldGapFraction: 0.2,
  minimumMeaningfulGap: 10,
} as const;

function roundCurrency(value: number): number {
  return Number(value.toFixed(2));
}

function roundPercent(value: number): number {
  return Number(value.toFixed(1));
}

function resolveBetTimestamp(bet: Bet): Date {
  return new Date(bet.settled_at ?? bet.created_at);
}

function buildDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function buildDateLabel(dateKey: string): string {
  const [year, month, day] = dateKey.split("-").map((part) => Number(part));
  return new Date(year, (month || 1) - 1, day || 1).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function getWinProfit(bet: Bet): number {
  return bet.promo_type === "bonus_bet" ? bet.win_payout : bet.win_payout - bet.stake;
}

function getLossProfit(bet: Bet): number {
  return bet.promo_type === "bonus_bet" ? 0 : -bet.stake;
}

function getBetVariance(bet: Bet): number {
  const winProfit = getWinProfit(bet);
  const lossProfit = getLossProfit(bet);
  const expectedProfit = bet.ev_total;
  const rawProbability = bet.true_prob_at_entry ?? (bet.odds_decimal > 0 ? 1 / bet.odds_decimal : 0.5);
  const winProbability = Math.min(1, Math.max(0, rawProbability));
  const lossProbability = 1 - winProbability;

  const winDistance = winProfit - expectedProfit;
  const lossDistance = lossProfit - expectedProfit;
  return (winProbability * (winDistance ** 2)) + (lossProbability * (lossDistance ** 2));
}

export function classifyStatsSource(bet: Bet): StatsSourceCategory {
  return getTrackerSource(bet);
}

export function buildVerdictSummary(input: {
  actualProfit: number;
  expectedProfit: number;
  normalSwing: number;
}): VerdictSummary {
  const { actualProfit, expectedProfit, normalSwing } = input;
  const lowerBound = expectedProfit - normalSwing;
  const upperBound = expectedProfit + normalSwing;
  const minimumGap = STATS_VERDICT_CONSTANTS.minimumMeaningfulGap;
  const hotBuffer = Math.max(minimumGap, normalSwing * STATS_VERDICT_CONSTANTS.hotBufferFraction);
  const reviewBuffer = Math.max(minimumGap, normalSwing * STATS_VERDICT_CONSTANTS.reviewBufferFraction);
  const coldGap = Math.max(minimumGap, normalSwing * STATS_VERDICT_CONSTANTS.coldGapFraction);

  if (actualProfit > upperBound + hotBuffer) {
    return {
      state: "hot",
      label: "HOT",
      copy: "You’re running ahead of expectation right now. Enjoy it, but let the process stay the same.",
    };
  }

  if (actualProfit < lowerBound - reviewBuffer) {
    return {
      state: "worth_reviewing",
      label: "WORTH REVIEWING",
      copy: "Results are trailing what this sample would usually expect. Worth a closer look before you make any big changes.",
    };
  }

  if ((expectedProfit - actualProfit) > coldGap) {
    return {
      state: "cold_but_okay",
      label: "COLD, BUT OKAY",
      copy: "You’re running a bit cold, but still inside a normal range for this sample.",
    };
  }

  return {
    state: "on_track",
    label: "ON TRACK",
    copy: "Results are lining up with expectation.",
  };
}

export function buildChartSeries(bets: Bet[]): StatsChartPoint[] {
  if (bets.length === 0) {
    return [];
  }

  const sortedBets = [...bets].sort(
    (left, right) => resolveBetTimestamp(left).getTime() - resolveBetTimestamp(right).getTime(),
  );

  const byDay = new Map<string, { ev: number; profit: number; variance: number }>();

  for (const bet of sortedBets) {
    const dateKey = buildDateKey(resolveBetTimestamp(bet));
    const current = byDay.get(dateKey) ?? { ev: 0, profit: 0, variance: 0 };
    current.ev += bet.ev_total;
    current.profit += bet.real_profit ?? 0;
    current.variance += getBetVariance(bet);
    byDay.set(dateKey, current);
  }

  let cumulativeEv = 0;
  let cumulativeProfit = 0;
  let cumulativeVariance = 0;

  return Array.from(byDay.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([dateKey, totals]) => {
      cumulativeEv += totals.ev;
      cumulativeProfit += totals.profit;
      cumulativeVariance += totals.variance;

      const swing = Math.sqrt(Math.max(0, cumulativeVariance)) * STATS_VERDICT_CONSTANTS.varianceBandSigma;
      const varianceLow = cumulativeEv - swing;
      const varianceHigh = cumulativeEv + swing;

      return {
        dateKey,
        dateLabel: buildDateLabel(dateKey),
        cumulativeEv: roundCurrency(cumulativeEv),
        cumulativeProfit: roundCurrency(cumulativeProfit),
        varianceLow: roundCurrency(varianceLow),
        varianceHigh: roundCurrency(varianceHigh),
        bandBase: roundCurrency(varianceLow),
        bandSize: roundCurrency(varianceHigh - varianceLow),
      };
    });
}

export function buildStatsPageModel(input: {
  bets: Bet[];
  balances: Balance[];
  settings?: Settings | null;
  now?: Date;
  showProcessStatsRow?: boolean;
}): StatsPageModel {
  const { bets, balances, settings, now = new Date(), showProcessStatsRow = true } = input;
  const settledBets = bets.filter((bet) => bet.result !== "pending" && bet.real_profit !== null);
  const pendingBets = bets.filter((bet) => bet.result === "pending");
  const coreBets = bets.filter((bet) => classifyStatsSource(bet) === "core");
  const bankroll = balances.length > 0
    ? roundCurrency(balances.reduce((sum, balance) => sum + balance.balance, 0))
    : null;
  const atRisk = roundCurrency(
    pendingBets
      .filter((bet) => bet.promo_type !== "bonus_bet")
      .reduce((sum, bet) => sum + bet.stake, 0),
  );
  const pendingEv = roundCurrency(
    pendingBets.reduce((sum, bet) => sum + bet.ev_total, 0),
  );
  const profit = roundCurrency(settledBets.reduce((sum, bet) => sum + (bet.real_profit ?? 0), 0));
  const evEarned = roundCurrency(settledBets.reduce((sum, bet) => sum + bet.ev_total, 0));
  const sevenDaysAgo = new Date(now.getTime() - (7 * 24 * 60 * 60 * 1000));
  const sevenDayProfitChange = roundCurrency(
    settledBets
      .filter((bet) => resolveBetTimestamp(bet).getTime() >= sevenDaysAgo.getTime())
      .reduce((sum, bet) => sum + (bet.real_profit ?? 0), 0),
  );

  const chartSeriesByFilter: Record<StatsChartFilter, StatsChartPoint[]> = {
    all: buildChartSeries(settledBets),
    core: buildChartSeries(settledBets.filter((bet) => classifyStatsSource(bet) === "core")),
    promos: buildChartSeries(settledBets.filter((bet) => classifyStatsSource(bet) === "promos")),
  };

  const sourceBreakdown: Record<TrackerSource, SourceTotals> = {
    core: { ev: 0, profit: 0 },
    promos: { ev: 0, profit: 0 },
  };

  for (const bet of settledBets) {
    const source = classifyStatsSource(bet);
    if (source === "core" || source === "promos") {
      sourceBreakdown[source].ev += bet.ev_total;
      sourceBreakdown[source].profit += bet.real_profit ?? 0;
    }
  }

  const finalAllPoint = chartSeriesByFilter.all.at(-1);
  const normalSwing = finalAllPoint
    ? roundCurrency(Math.max(0, finalAllPoint.varianceHigh - finalAllPoint.cumulativeEv))
    : 0;
  const verdict = settledBets.length > 0
    ? buildVerdictSummary({
      actualProfit: profit,
      expectedProfit: evEarned,
      normalSwing,
    })
    : {
      state: "on_track",
      label: "ON TRACK",
      copy: "Once a few bets settle, this will tell you how results compare with your EV.",
    } satisfies VerdictSummary;

  const trackedCloseCoreBets = coreBets.filter((bet) => bet.pinnacle_odds_at_entry !== null);
  const validCloseCoreBets = trackedCloseCoreBets.filter(
    (bet) => bet.clv_ev_percent !== null && bet.beat_close !== null,
  );
  const beatClosePct = validCloseCoreBets.length > 0
    ? roundPercent((validCloseCoreBets.filter((bet) => bet.beat_close === true).length / validCloseCoreBets.length) * 100)
    : null;
  const avgClvPct = validCloseCoreBets.length > 0
    ? roundPercent(
      validCloseCoreBets.reduce((sum, bet) => sum + (bet.clv_ev_percent ?? 0), 0) / validCloseCoreBets.length,
    )
    : null;
  const closeCoveragePct = trackedCloseCoreBets.length > 0
    ? roundPercent((validCloseCoreBets.length / trackedCloseCoreBets.length) * 100)
    : null;
  const avgEdgePct = coreBets.length > 0
    ? roundPercent((coreBets.reduce((sum, bet) => sum + bet.ev_per_dollar, 0) / coreBets.length) * 100)
    : null;
  const decisiveCoreBetsWithProbability = coreBets.filter(
    (bet) =>
      (bet.result === "win" || bet.result === "loss")
      && typeof bet.true_prob_at_entry === "number"
      && Number.isFinite(bet.true_prob_at_entry),
  );
  const actualWinRatePct = decisiveCoreBetsWithProbability.length > 0
    ? roundPercent(
      (decisiveCoreBetsWithProbability.filter((bet) => bet.result === "win").length / decisiveCoreBetsWithProbability.length) * 100,
    )
    : null;
  const expectedWinRatePct = decisiveCoreBetsWithProbability.length > 0
    ? roundPercent(
      (decisiveCoreBetsWithProbability.reduce((sum, bet) => sum + (bet.true_prob_at_entry ?? 0), 0) / decisiveCoreBetsWithProbability.length) * 100,
    )
    : null;

  const bankrollDetails: BankrollDetailsModel = {
    total: bankroll,
    books: balances.map((balance) => ({
      sportsbook: balance.sportsbook,
      deposits: roundCurrency(balance.deposits),
      withdrawals: roundCurrency(balance.withdrawals),
      pending: roundCurrency(balance.pending),
      balance: roundCurrency(balance.balance),
    })),
    sizingMode:
      typeof settings?.use_computed_bankroll === "boolean"
        ? settings.use_computed_bankroll
          ? "computed"
          : "override"
        : null,
    bankrollOverride:
      settings && settings.use_computed_bankroll === false
        ? roundCurrency(settings.bankroll_override)
        : null,
  };

  return {
    bankroll,
    totalBetsLogged: bets.length,
    settledBetsCount: settledBets.length,
    profit,
    sevenDayProfitChange,
    atRisk,
    pendingEv,
    evEarned,
    normalSwing,
    verdict,
    chartSeriesByFilter,
    sourceBreakdown: {
      core: {
        ev: roundCurrency(sourceBreakdown.core.ev),
        profit: roundCurrency(sourceBreakdown.core.profit),
      },
      promos: {
        ev: roundCurrency(sourceBreakdown.promos.ev),
        profit: roundCurrency(sourceBreakdown.promos.profit),
      },
    },
    processStats: {
      beatClosePct,
      avgClvPct,
      trackedCloseCount: trackedCloseCoreBets.length,
      validCloseCount: validCloseCoreBets.length,
      closeCoveragePct,
      avgEdgePct,
      actualWinRatePct,
      expectedWinRatePct,
      winRateSampleCount: decisiveCoreBetsWithProbability.length,
    },
    bankrollDetails,
    hasSettledData: settledBets.length > 0,
    showProcessStatsRow,
  };
}
