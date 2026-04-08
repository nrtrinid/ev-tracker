export const ONBOARDING_STEPS = {
  TUTORIAL_SCANNER_STRAIGHT_BETS: "tutorial_scanner_straight_bets",
  HOME_SCANNER_REVIEW: "home_scanner_review",
  SCANNER_REVIEW_PROMPT: "scanner_review_prompt",
  PARLAY_BUILDER: "parlay_builder",
  PARLAY_ONE_LEG_PROMPT: "parlay_one_leg_prompt",
} as const;

export const ONBOARDING_STEP_IDS = [
  ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
  ONBOARDING_STEPS.HOME_SCANNER_REVIEW,
  ONBOARDING_STEPS.SCANNER_REVIEW_PROMPT,
  ONBOARDING_STEPS.PARLAY_BUILDER,
  ONBOARDING_STEPS.PARLAY_ONE_LEG_PROMPT,
] as const;

export type OnboardingStepId = (typeof ONBOARDING_STEP_IDS)[number];

export const ONBOARDING_EVENT_TYPES = ["complete_step", "dismiss_step", "reset"] as const;
export type OnboardingEventType = (typeof ONBOARDING_EVENT_TYPES)[number];

const ONBOARDING_STEP_ID_SET = new Set<string>(ONBOARDING_STEP_IDS);

export function isOnboardingStepId(value: unknown): value is OnboardingStepId {
  return typeof value === "string" && ONBOARDING_STEP_ID_SET.has(value);
}

export function sanitizeOnboardingSteps(values: unknown): OnboardingStepId[] {
  if (!Array.isArray(values)) return [];
  const seen = new Set<OnboardingStepId>();
  const next: OnboardingStepId[] = [];

  for (const value of values) {
    if (!isOnboardingStepId(value) || seen.has(value)) {
      continue;
    }
    seen.add(value);
    next.push(value);
  }

  return next;
}

export const ONBOARDING_CORE_FLOW: OnboardingStepId[] = [
  ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
  ONBOARDING_STEPS.HOME_SCANNER_REVIEW,
  ONBOARDING_STEPS.SCANNER_REVIEW_PROMPT,
];

export const ONBOARDING_OPTIONAL_FLOW: OnboardingStepId[] = [
  ONBOARDING_STEPS.PARLAY_BUILDER,
  ONBOARDING_STEPS.PARLAY_ONE_LEG_PROMPT,
];
