import { expect, test } from "@playwright/test";

import {
  buildStatsPageModel,
  buildVerdictSummary,
  classifyStatsSource,
} from "@/lib/stats-page";
import type { Balance, Bet, Settings } from "@/lib/types";

const testEmail = process.env.PLAYWRIGHT_TEST_EMAIL;
const testPassword = process.env.PLAYWRIGHT_TEST_PASSWORD;
const hasAuth = !!testEmail && !!testPassword;

const betsApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/bets(?:\?.*)?$/;
const balancesApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/balances(?:\?.*)?$/;
const settingsApiPattern = /http:\/\/(127\.0\.0\.1|localhost):8000\/settings(?:\?.*)?$/;

function makeBet(overrides: Partial<Bet> = {}): Bet {
  const createdAt = overrides.created_at ?? "2026-04-01T12:00:00Z";
  const settledAt = overrides.settled_at ?? createdAt;
  return {
    id: overrides.id ?? "bet-1",
    created_at: createdAt,
    event_date: overrides.event_date ?? createdAt.slice(0, 10),
    settled_at: settledAt,
    sport: overrides.sport ?? "NBA",
    event: overrides.event ?? "Lakers ML",
    market: overrides.market ?? "ML",
    surface: overrides.surface ?? "straight_bets",
    sportsbook: overrides.sportsbook ?? "DraftKings",
    promo_type: overrides.promo_type ?? "standard",
    odds_american: overrides.odds_american ?? 100,
    odds_decimal: overrides.odds_decimal ?? 2,
    stake: overrides.stake ?? 10,
    boost_percent: overrides.boost_percent ?? null,
    winnings_cap: overrides.winnings_cap ?? null,
    notes: overrides.notes ?? null,
    opposing_odds: overrides.opposing_odds ?? null,
    result: overrides.result ?? "win",
    win_payout: overrides.win_payout ?? 20,
    ev_per_dollar: overrides.ev_per_dollar ?? 0.2,
    ev_total: overrides.ev_total ?? 2,
    real_profit: overrides.real_profit ?? 10,
    pinnacle_odds_at_entry: overrides.pinnacle_odds_at_entry ?? null,
    latest_pinnacle_odds: overrides.latest_pinnacle_odds ?? null,
    latest_pinnacle_updated_at: overrides.latest_pinnacle_updated_at ?? null,
    pinnacle_odds_at_close: overrides.pinnacle_odds_at_close ?? null,
    clv_updated_at: overrides.clv_updated_at ?? null,
    commence_time: overrides.commence_time ?? null,
    clv_team: overrides.clv_team ?? null,
    clv_sport_key: overrides.clv_sport_key ?? null,
    clv_event_id: overrides.clv_event_id ?? null,
    true_prob_at_entry: overrides.true_prob_at_entry !== undefined ? overrides.true_prob_at_entry : 0.6,
    clv_ev_percent: overrides.clv_ev_percent ?? null,
    beat_close: overrides.beat_close ?? null,
    is_paper: overrides.is_paper ?? false,
    strategy_cohort: overrides.strategy_cohort ?? null,
    auto_logged: overrides.auto_logged ?? false,
    auto_log_run_at: overrides.auto_log_run_at ?? null,
    auto_log_run_key: overrides.auto_log_run_key ?? null,
    scan_ev_percent_at_log: overrides.scan_ev_percent_at_log ?? null,
    book_odds_at_log: overrides.book_odds_at_log ?? null,
    reference_odds_at_log: overrides.reference_odds_at_log ?? null,
    source_event_id: overrides.source_event_id ?? null,
    source_market_key: overrides.source_market_key ?? null,
    source_selection_key: overrides.source_selection_key ?? null,
    participant_name: overrides.participant_name ?? null,
    participant_id: overrides.participant_id ?? null,
    selection_side: overrides.selection_side ?? null,
    line_value: overrides.line_value ?? null,
    selection_meta: overrides.selection_meta ?? null,
  };
}

function makeBalance(overrides: Partial<Balance> = {}): Balance {
  return {
    sportsbook: overrides.sportsbook ?? "DraftKings",
    deposits: overrides.deposits ?? 100,
    withdrawals: overrides.withdrawals ?? 0,
    net_deposits: overrides.net_deposits ?? 100,
    profit: overrides.profit ?? 15,
    pending: overrides.pending ?? 10,
    balance: overrides.balance ?? 105,
  };
}

function makeSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    k_factor: overrides.k_factor ?? 0.78,
    default_stake: overrides.default_stake ?? null,
    preferred_sportsbooks: overrides.preferred_sportsbooks ?? ["DraftKings", "FanDuel"],
    kelly_multiplier: overrides.kelly_multiplier ?? 0.25,
    bankroll_override: overrides.bankroll_override ?? 150,
    use_computed_bankroll: overrides.use_computed_bankroll ?? true,
    theme_preference: overrides.theme_preference ?? "light",
    k_factor_mode: overrides.k_factor_mode ?? "baseline",
    k_factor_min_stake: overrides.k_factor_min_stake ?? 100,
    k_factor_smoothing: overrides.k_factor_smoothing ?? 0.5,
    k_factor_clamp_min: overrides.k_factor_clamp_min ?? 0.6,
    k_factor_clamp_max: overrides.k_factor_clamp_max ?? 0.9,
    k_factor_observed: overrides.k_factor_observed ?? null,
    k_factor_weight: overrides.k_factor_weight ?? 0,
    k_factor_effective: overrides.k_factor_effective ?? 0.78,
    k_factor_bonus_stake_settled: overrides.k_factor_bonus_stake_settled ?? 0,
    onboarding_state: overrides.onboarding_state ?? null,
  };
}

async function loginIfNeeded(page: import("@playwright/test").Page) {
  if (!hasAuth) return;
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(testEmail!);
  await page.getByLabel(/password/i).fill(testPassword!);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL("/", { timeout: 15000 });
}

test.describe("stats page helpers", () => {
  test("classifies core bets, promos, and standard game lines correctly", async () => {
    expect(classifyStatsSource(makeBet({ surface: "player_props", promo_type: "standard" }))).toBe("core");
    expect(classifyStatsSource(makeBet({ surface: "player_props", promo_type: "boost_30" }))).toBe("promos");
    expect(classifyStatsSource(makeBet({ market: "Spread", surface: "straight_bets", promo_type: "standard" }))).toBe("core");
  });

  test("includes standard game lines in the core-bets bucket while keeping them out of promos", async () => {
    const model = buildStatsPageModel({
      bets: [
        makeBet({
          id: "props-standard",
          surface: "player_props",
          promo_type: "standard",
          ev_total: 6,
          real_profit: 8,
          created_at: "2026-04-01T12:00:00Z",
          settled_at: "2026-04-01T13:00:00Z",
        }),
        makeBet({
          id: "promo-straight",
          surface: "straight_bets",
          promo_type: "boost_30",
          ev_total: 4,
          real_profit: 2,
          created_at: "2026-04-02T12:00:00Z",
          settled_at: "2026-04-02T13:00:00Z",
        }),
        makeBet({
          id: "game-line",
          market: "Spread",
          surface: "straight_bets",
          promo_type: "standard",
          ev_total: 5,
          real_profit: 4,
          created_at: "2026-04-03T12:00:00Z",
          settled_at: "2026-04-03T13:00:00Z",
        }),
      ],
      balances: [makeBalance()],
    });

    expect(model.profit).toBe(14);
    expect(model.evEarned).toBe(15);
    expect(model.chartSeriesByFilter.all.at(-1)?.cumulativeProfit).toBe(14);
    expect(model.chartSeriesByFilter.core.at(-1)?.cumulativeProfit).toBe(12);
    expect(model.chartSeriesByFilter.promos.at(-1)?.cumulativeProfit).toBe(2);
    expect(model.sourceBreakdown.core.profit).toBe(12);
    expect(model.sourceBreakdown.core.ev).toBe(11);
    expect(model.sourceBreakdown.promos.profit).toBe(2);
  });

  test("builds conservative verdict states across all four thresholds", async () => {
    expect(buildVerdictSummary({ actualProfit: 160, expectedProfit: 100, normalSwing: 20 }).state).toBe("hot");
    expect(buildVerdictSummary({ actualProfit: 95, expectedProfit: 100, normalSwing: 20 }).state).toBe("on_track");
    expect(buildVerdictSummary({ actualProfit: 84, expectedProfit: 100, normalSwing: 20 }).state).toBe("cold_but_okay");
    expect(buildVerdictSummary({ actualProfit: 60, expectedProfit: 100, normalSwing: 20 }).state).toBe("worth_reviewing");
  });

  test("uses settled_at for 7-day profit and builds daily cumulative variance-band points", async () => {
    const model = buildStatsPageModel({
      now: new Date("2026-04-10T12:00:00Z"),
      bets: [
        makeBet({
          id: "older-created-recent-settle",
          created_at: "2026-03-20T10:00:00Z",
          settled_at: "2026-04-08T10:00:00Z",
          ev_total: 3,
          real_profit: 6,
          true_prob_at_entry: 0.55,
        }),
        makeBet({
          id: "outside-window",
          created_at: "2026-04-01T10:00:00Z",
          settled_at: "2026-04-02T10:00:00Z",
          ev_total: 2,
          real_profit: -4,
          true_prob_at_entry: 0.52,
        }),
      ],
      balances: [makeBalance()],
    });

    expect(model.sevenDayProfitChange).toBe(6);
    expect(model.chartSeriesByFilter.all).toHaveLength(2);
    expect(model.chartSeriesByFilter.all[0].varianceHigh).toBeGreaterThan(model.chartSeriesByFilter.all[0].cumulativeEv);
    expect(model.chartSeriesByFilter.all[0].bandSize).toBeGreaterThan(0);
  });

  test("derives process stats from core bets only and exposes bankroll sizing details", async () => {
    const model = buildStatsPageModel({
      bets: [
        makeBet({
          id: "core-valid-win",
          promo_type: "standard",
          result: "win",
          ev_per_dollar: 0.06,
          pinnacle_odds_at_entry: -110,
          clv_ev_percent: 3,
          beat_close: true,
          true_prob_at_entry: 0.55,
        }),
        makeBet({
          id: "core-valid-loss",
          promo_type: "standard",
          result: "loss",
          real_profit: -10,
          ev_per_dollar: 0.04,
          pinnacle_odds_at_entry: -115,
          clv_ev_percent: -1,
          beat_close: false,
          true_prob_at_entry: 0.45,
        }),
        makeBet({
          id: "core-tracked-pending",
          promo_type: "standard",
          result: "pending",
          real_profit: null,
          settled_at: null,
          ev_per_dollar: 0.03,
          ev_total: 1.5,
          pinnacle_odds_at_entry: -108,
          clv_ev_percent: null,
          beat_close: null,
          true_prob_at_entry: 0.52,
        }),
        makeBet({
          id: "promo-ignored",
          promo_type: "boost_30",
          ev_per_dollar: 0.2,
          pinnacle_odds_at_entry: -120,
          clv_ev_percent: 9,
          beat_close: true,
          true_prob_at_entry: 0.7,
        }),
      ],
      balances: [
        makeBalance({ sportsbook: "DraftKings", balance: 120, deposits: 150, withdrawals: 10, pending: 20 }),
      ],
      settings: makeSettings({ use_computed_bankroll: false, bankroll_override: 175 }),
    });

    expect(model.processStats.beatClosePct).toBe(50);
    expect(model.processStats.avgClvPct).toBe(1);
    expect(model.processStats.trackedCloseCount).toBe(3);
    expect(model.processStats.validCloseCount).toBe(2);
    expect(model.processStats.closeCoveragePct).toBe(66.7);
    expect(model.processStats.avgEdgePct).toBe(4.3);
    expect(model.processStats.actualWinRatePct).toBe(50);
    expect(model.processStats.expectedWinRatePct).toBe(50);
    expect(model.bankrollDetails.sizingMode).toBe("override");
    expect(model.bankrollDetails.bankrollOverride).toBe(175);
  });

  test("keeps win rate empty when expected win rate cannot be computed honestly", async () => {
    const model = buildStatsPageModel({
      bets: [
        makeBet({
          id: "core-without-probability",
          promo_type: "standard",
          result: "win",
          true_prob_at_entry: null,
        }),
      ],
      balances: [makeBalance()],
    });

    expect(model.processStats.actualWinRatePct).toBeNull();
    expect(model.processStats.expectedWinRatePct).toBeNull();
    expect(model.processStats.winRateSampleCount).toBe(0);
  });
});

test.describe("stats page mobile UI", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page }) => {
    test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run the UI verification.");
    await loginIfNeeded(page);
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("renders the locked section order and keeps pills chart-only", async ({ page }) => {
    const mockedBets = [
      makeBet({
        id: "props-standard",
        surface: "player_props",
        promo_type: "standard",
        market: "Prop",
        event: "Jokic Over 24.5",
        sportsbook: "FanDuel",
        ev_total: 6,
        real_profit: 8,
        created_at: "2026-04-01T12:00:00Z",
        settled_at: "2026-04-01T14:00:00Z",
      }),
      makeBet({
        id: "promo-boost",
        surface: "straight_bets",
        promo_type: "boost_30",
        market: "ML",
        event: "Suns ML",
        sportsbook: "DraftKings",
        ev_total: 4,
        real_profit: 2,
        created_at: "2026-04-02T12:00:00Z",
        settled_at: "2026-04-02T14:00:00Z",
      }),
      makeBet({
        id: "game-line",
        surface: "straight_bets",
        promo_type: "standard",
        market: "Spread",
        event: "Lakers +4.5",
        sportsbook: "BetMGM",
        ev_total: 5,
        real_profit: 4,
        created_at: "2026-04-03T12:00:00Z",
        settled_at: "2026-04-03T14:00:00Z",
      }),
      makeBet({
        id: "open-risk",
        result: "pending",
        real_profit: null,
        settled_at: null,
        ev_total: 2,
        stake: 25,
        win_payout: 50,
        created_at: "2026-04-04T12:00:00Z",
      }),
    ];

    const mockedBalances = [
      makeBalance({
        sportsbook: "DraftKings",
        deposits: 120,
        net_deposits: 120,
        profit: 8,
        pending: 15,
        balance: 113,
      }),
      makeBalance({
        sportsbook: "FanDuel",
        deposits: 100,
        net_deposits: 100,
        profit: 10,
        pending: 10,
        balance: 100,
      }),
    ];

    const mockedSettings = makeSettings({
      use_computed_bankroll: false,
      bankroll_override: 250,
    });

    await page.route(betsApiPattern, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedBets),
      });
    });

    await page.route(balancesApiPattern, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedBalances),
      });
    });

    await page.route(settingsApiPattern, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedSettings),
      });
    });

    await page.goto("/bets/stats");

    const verdictCard = page.getByTestId("verdict-card");
    const summaryCards = page.getByTestId("summary-cards");
    const chart = page.getByTestId("stats-chart");
    const breakdown = page.getByTestId("source-breakdown");
    const processStats = page.getByTestId("process-stats");

    await expect(verdictCard).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("summary-card")).toHaveCount(3);
    await expect(breakdown.getByTestId("source-row")).toHaveCount(2);
    await expect(processStats).toBeVisible();
    await expect(page.getByRole("button", { name: "Core Bets" })).toBeVisible();
    await expect(breakdown).toContainText("Core Bets");
    await expect(processStats).toContainText("Process Stats");

    const verdictBox = await verdictCard.boundingBox();
    const summaryBox = await summaryCards.boundingBox();
    const chartBox = await chart.boundingBox();
    const breakdownBox = await breakdown.boundingBox();
    const processBox = await processStats.boundingBox();

    expect(verdictBox?.y ?? 0).toBeLessThan(summaryBox?.y ?? 0);
    expect(summaryBox?.y ?? 0).toBeLessThan(chartBox?.y ?? 0);
    expect(chartBox?.y ?? 0).toBeLessThan(breakdownBox?.y ?? 0);
    expect(breakdownBox?.y ?? 0).toBeLessThan(processBox?.y ?? 0);

    const breakdownTextBefore = await breakdown.textContent();
    await expect(chart).toHaveAttribute("data-chart-filter", "all");
    await expect(chart).toHaveAttribute("data-final-profit", "14.00");

    await page.getByRole("button", { name: "Promos" }).click();
    await expect(chart).toHaveAttribute("data-chart-filter", "promos");
    await expect(chart).toHaveAttribute("data-final-profit", "2.00");
    await expect(breakdown).toHaveText(breakdownTextBefore ?? "");

    await page.getByTestId("bankroll-summary-trigger").click();
    await expect(page.getByTestId("bankroll-details-sheet")).toBeVisible();
    await expect(page.getByText("Bankroll Details")).toBeVisible();
    await expect(page.getByText("DraftKings")).toBeVisible();
    await expect(page.getByText("Bankroll settings")).toBeVisible();
  });
});
