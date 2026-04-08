export const ONBOARDING_HIGHLIGHT_TARGETS = {
  COACH_START_WALKTHROUGH: "coach_start_walkthrough",
  COACH_REVIEW_SAVED_PICK: "coach_review_saved_pick",
  MARKETS_PRACTICE_PLACE: "markets_practice_place",
  DRAWER_SAVE_PRACTICE_TICKET: "drawer_save_practice_ticket",
  NAV_BETS_TAB: "nav_bets_tab",
  NAV_MARKETS_TAB: "nav_markets_tab",
  BETS_FINISH_TUTORIAL: "bets_finish_tutorial",
} as const;

export type OnboardingHighlightTarget =
  (typeof ONBOARDING_HIGHLIGHT_TARGETS)[keyof typeof ONBOARDING_HIGHLIGHT_TARGETS];

export interface OnboardingHighlightMessage {
  title: string;
  body: string;
}

export const ONBOARDING_HIGHLIGHT_MESSAGES: Record<OnboardingHighlightTarget, OnboardingHighlightMessage> = {
  [ONBOARDING_HIGHLIGHT_TARGETS.COACH_START_WALKTHROUGH]: {
    title: "Start here",
    body: "Tap Start Walkthrough to begin the guided Daily Drops flow.",
  },
  [ONBOARDING_HIGHLIGHT_TARGETS.COACH_REVIEW_SAVED_PICK]: {
    title: "Next step",
    body: "Tap Review Saved Pick to open the practice log drawer.",
  },
  [ONBOARDING_HIGHLIGHT_TARGETS.MARKETS_PRACTICE_PLACE]: {
    title: "Practice this action",
    body: "Tap Practice Log Ticket on a simulated line to continue.",
  },
  [ONBOARDING_HIGHLIGHT_TARGETS.DRAWER_SAVE_PRACTICE_TICKET]: {
    title: "Save your practice ticket",
    body: "Tap Save Practice Ticket to move to the Bets review step.",
  },
  [ONBOARDING_HIGHLIGHT_TARGETS.NAV_BETS_TAB]: {
    title: "Open Bets",
    body: "Tap Bets in the bottom nav to review your practice ticket.",
  },
  [ONBOARDING_HIGHLIGHT_TARGETS.NAV_MARKETS_TAB]: {
    title: "Open Markets",
    body: "Tap Markets in the bottom nav to continue the walkthrough.",
  },
  [ONBOARDING_HIGHLIGHT_TARGETS.BETS_FINISH_TUTORIAL]: {
    title: "Finish onboarding",
    body: "Tap Finish Tutorial to complete onboarding and return to Markets.",
  },
};
