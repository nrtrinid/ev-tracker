import { test, expect } from "@playwright/test";

const testEmail = process.env.PLAYWRIGHT_TEST_EMAIL;
const testPassword = process.env.PLAYWRIGHT_TEST_PASSWORD;
const hasAuth = !!testEmail && !!testPassword;

type DuplicateState = "logged_elsewhere" | "already_logged" | "better_now";

function buildStraightScanPayload(params: {
  duplicateState: DuplicateState;
  team: string;
  event: string;
  bookOdds: number;
  bestLoggedOdds?: number;
  currentOdds?: number;
}) {
  return {
    sport: "basketball_nba",
    sides: [
      {
        sportsbook: "DraftKings",
        sport: "basketball_nba",
        event: params.event,
        commence_time: "2026-01-15T00:30:00Z",
        team: params.team,
        pinnacle_odds: 112,
        book_odds: params.bookOdds,
        true_prob: 0.465,
        base_kelly_fraction: 0.04,
        book_decimal: 2.3,
        ev_percentage: 3.9,
        scanner_duplicate_state: params.duplicateState,
        best_logged_odds_american: params.bestLoggedOdds ?? null,
        current_odds_american: params.currentOdds ?? params.bookOdds,
        matched_pending_bet_id: "bet-123",
      },
    ],
    events_fetched: 1,
    events_with_both_books: 1,
    api_requests_remaining: "499",
    scanned_at: "2026-01-14T18:00:00Z",
  };
}

function buildPlayerPropScanPayload(params: {
  duplicateState: DuplicateState;
  playerName: string;
  displayName: string;
  bookOdds: number;
  bestLoggedOdds?: number;
  currentOdds?: number;
}) {
  return {
    surface: "player_props",
    sport: "basketball_nba",
    sides: [
      {
        surface: "player_props",
        event_id: "evt-prop-1",
        market_key: "player_points",
        selection_key: "evt-prop-1|player_points|nikola-jokic|over:24.5",
        sportsbook: "FanDuel",
        sport: "basketball_nba",
        event: "Nuggets @ Suns",
        commence_time: "2026-01-15T00:30:00Z",
        market: "player_points",
        player_name: params.playerName,
        participant_id: null,
        team: "Nuggets",
        opponent: "Suns",
        selection_side: "over",
        line_value: 24.5,
        display_name: params.displayName,
        reference_odds: -108,
        reference_source: "market_median",
        reference_bookmakers: ["DraftKings", "BetMGM"],
        reference_bookmaker_count: 2,
        book_odds: params.bookOdds,
        true_prob: 0.52,
        base_kelly_fraction: 0.03,
        book_decimal: 2.05,
        ev_percentage: 6.6,
        scanner_duplicate_state: params.duplicateState,
        best_logged_odds_american: params.bestLoggedOdds ?? null,
        current_odds_american: params.currentOdds ?? params.bookOdds,
        matched_pending_bet_id: "prop-bet-123",
      },
    ],
    prizepicks_cards: [],
    events_fetched: 1,
    events_with_both_books: 1,
    api_requests_remaining: "499",
    scanned_at: "2026-01-14T18:00:00Z",
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

async function mockScannerLatest(page: import("@playwright/test").Page, payload: unknown) {
  await page.route("**/api/scan-latest**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
}

test.describe("scanner duplicate states", () => {
  test.skip(!hasAuth, "Set PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD to run scanner duplicate-state tests.");

  test.beforeEach(async ({ page }) => {
    await loginIfNeeded(page);
  });

  test("shows Better Now badge and improved-line microcopy", async ({ page }) => {
    await mockScannerLatest(
      page,
      buildStraightScanPayload({
        duplicateState: "better_now",
        team: "Los Angeles Lakers",
        event: "Lakers @ Warriors",
        bookOdds: 130,
        bestLoggedOdds: 100,
        currentOdds: 130,
      })
    );

    await page.goto("/scanner");

    const card = page.locator(".card-hover").filter({ hasText: "Los Angeles Lakers" }).first();
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card.getByText("Better Now")).toBeVisible();
    await expect(card.getByText("Already Placed")).toHaveCount(0);
    await expect(card.getByText(/Logged at \+100 - now \+130/i)).toBeVisible();
    await expect(card.getByText(/This line is better than the one you already logged\./i)).toHaveCount(0);
  });

  test("shows Placed Elsewhere badge for cross-book exposure", async ({ page }) => {
    await mockScannerLatest(
      page,
      buildStraightScanPayload({
        duplicateState: "logged_elsewhere",
        team: "Phoenix Suns",
        event: "Suns @ Kings",
        bookOdds: 118,
        bestLoggedOdds: 112,
      })
    );

    await page.goto("/scanner");

    const card = page.locator(".card-hover").filter({ hasText: "Phoenix Suns" }).first();
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card.getByText("Placed Elsewhere")).toBeVisible();
    await expect(card.getByText("Already Placed")).toHaveCount(0);
    await expect(card.getByText("Better Now")).toHaveCount(0);
    await expect(card.getByText(/Logged at/i)).toHaveCount(0);
  });

  test("drawer warns on duplicate exposure and updates submit CTA", async ({ page }) => {
    await mockScannerLatest(
      page,
      buildStraightScanPayload({
        duplicateState: "already_logged",
        team: "Boston Celtics",
        event: "Celtics @ Knicks",
        bookOdds: 115,
      })
    );

    await page.goto("/scanner");

    const card = page.locator(".card-hover").filter({ hasText: "Boston Celtics" }).first();
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card.getByText("Already Placed")).toBeVisible();
    await card.getByRole("button", { name: /Review & Log/i }).click();

    await expect(page.getByRole("heading", { name: "Log Bet" })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("You already placed this side.")).toBeVisible();
    await expect(page.getByText(/increase exposure on the same outcome/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Log Another Ticket" })).toBeVisible();
  });

  [
    {
      duplicateState: "better_now" as const,
      expectedBadge: "Better Now",
      bookOdds: 130,
      bestLoggedOdds: 100,
    },
    {
      duplicateState: "logged_elsewhere" as const,
      expectedBadge: "Placed Elsewhere",
      bookOdds: 118,
      bestLoggedOdds: 112,
    },
    {
      duplicateState: "already_logged" as const,
      expectedBadge: "Already Placed",
      bookOdds: 115,
    },
  ].forEach(({ duplicateState, expectedBadge, bookOdds, bestLoggedOdds }) => {
    test(`shows ${expectedBadge} badge on player prop cards`, async ({ page }) => {
      await mockScannerLatest(
        page,
        buildPlayerPropScanPayload({
          duplicateState,
          playerName: "Nikola Jokic",
          displayName: "Nikola Jokic Over 24.5",
          bookOdds,
          bestLoggedOdds,
          currentOdds: bookOdds,
        })
      );

      await page.goto("/scanner/player_props");

      const card = page.locator(".card-hover").filter({ hasText: "Nikola Jokic Over 24.5" }).first();
      await expect(card).toBeVisible({ timeout: 10000 });
      await expect(card.getByText(expectedBadge)).toBeVisible();
    });
  });
});
