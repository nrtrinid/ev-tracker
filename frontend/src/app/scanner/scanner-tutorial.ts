import type { ScanResult } from "@/lib/types";
import { ONBOARDING_STEPS } from "@/lib/onboarding";
import type { OnboardingStepId } from "@/lib/onboarding";

export const STRAIGHT_BETS_TUTORIAL_STEP = ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS;

function futureIso(minutesFromNow: number) {
  return new Date(Date.now() + minutesFromNow * 60_000).toISOString();
}

export function isStraightBetsTutorialActive(params: {
  surface: string;
  completed: OnboardingStepId[];
  dismissed: OnboardingStepId[];
}) {
  const { surface, completed, dismissed } = params;
  if (surface !== "straight_bets") return false;
  return (
    !completed.includes(STRAIGHT_BETS_TUTORIAL_STEP) &&
    !dismissed.includes(STRAIGHT_BETS_TUTORIAL_STEP)
  );
}

export const STRAIGHT_BETS_TUTORIAL_SCAN: ScanResult = {
  surface: "straight_bets",
  sport: "basketball_nba",
  events_fetched: 4,
  events_with_both_books: 4,
  api_requests_remaining: "tutorial",
  scanned_at: futureIso(0),
  sides: [
    {
      surface: "straight_bets",
      event_id: "tutorial-lakers-celtics",
      market_key: "h2h",
      selection_key: "lakers-ml",
      sportsbook: "DraftKings",
      sportsbook_deeplink_url: null,
      sport: "basketball_nba",
      event: "Los Angeles Lakers @ Boston Celtics",
      commence_time: futureIso(55),
      team: "Los Angeles Lakers",
      pinnacle_odds: 118,
      book_odds: 132,
      true_prob: 0.462,
      base_kelly_fraction: 0.027,
      book_decimal: 2.32,
      ev_percentage: 7.2,
    },
    {
      surface: "straight_bets",
      event_id: "tutorial-knicks-heat",
      market_key: "h2h",
      selection_key: "knicks-ml",
      sportsbook: "FanDuel",
      sportsbook_deeplink_url: null,
      sport: "basketball_nba",
      event: "New York Knicks @ Miami Heat",
      commence_time: futureIso(82),
      team: "New York Knicks",
      pinnacle_odds: -102,
      book_odds: 108,
      true_prob: 0.505,
      base_kelly_fraction: 0.022,
      book_decimal: 2.08,
      ev_percentage: 5.0,
    },
    {
      surface: "straight_bets",
      event_id: "tutorial-warriors-suns",
      market_key: "h2h",
      selection_key: "warriors-ml",
      sportsbook: "BetMGM",
      sportsbook_deeplink_url: null,
      sport: "basketball_nba",
      event: "Golden State Warriors @ Phoenix Suns",
      commence_time: futureIso(96),
      team: "Golden State Warriors",
      pinnacle_odds: 124,
      book_odds: 140,
      true_prob: 0.451,
      base_kelly_fraction: 0.018,
      book_decimal: 2.4,
      ev_percentage: 4.2,
    },
    {
      surface: "straight_bets",
      event_id: "tutorial-bucks-sixers",
      market_key: "h2h",
      selection_key: "bucks-ml",
      sportsbook: "FanDuel",
      sportsbook_deeplink_url: null,
      sport: "basketball_nba",
      event: "Milwaukee Bucks @ Philadelphia 76ers",
      commence_time: futureIso(115),
      team: "Milwaukee Bucks",
      pinnacle_odds: -118,
      book_odds: -104,
      true_prob: 0.553,
      base_kelly_fraction: 0.013,
      book_decimal: 1.96,
      ev_percentage: 3.4,
    },
  ],
};
