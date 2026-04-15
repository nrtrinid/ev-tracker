import { expect, test } from "@playwright/test";

import { resolveHydratedOnboardingState } from "@/lib/betting-platform-store";
import { ONBOARDING_STEPS } from "@/lib/onboarding";

test.describe("betting platform onboarding hydration", () => {
  test("remote hydration applies authoritative backend resets", async () => {
    const resolved = resolveHydratedOnboardingState(
      {
        onboardingCompleted: [ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS],
        onboardingDismissed: [],
      },
      {
        completed: [],
        dismissed: [],
      },
      "remote",
    );

    expect(resolved.completed).toEqual([]);
    expect(resolved.dismissed).toEqual([]);
  });

  test("remote hydration keeps backend completed and dismissed steps", async () => {
    const resolved = resolveHydratedOnboardingState(
      {
        onboardingCompleted: [ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS],
        onboardingDismissed: [],
      },
      {
        completed: [ONBOARDING_STEPS.HOME_SCANNER_REVIEW],
        dismissed: [ONBOARDING_STEPS.PARLAY_BUILDER],
      },
      "remote",
    );

    expect(resolved.completed).toEqual([ONBOARDING_STEPS.HOME_SCANNER_REVIEW]);
    expect(resolved.dismissed).toEqual([ONBOARDING_STEPS.PARLAY_BUILDER]);
  });

  test("completed backend steps remove matching dismissed entries", async () => {
    const resolved = resolveHydratedOnboardingState(
      {
        onboardingCompleted: [],
        onboardingDismissed: [],
      },
      {
        completed: [ONBOARDING_STEPS.SCANNER_REVIEW_PROMPT],
        dismissed: [ONBOARDING_STEPS.SCANNER_REVIEW_PROMPT],
      },
      "remote",
    );

    expect(resolved.completed).toEqual([ONBOARDING_STEPS.SCANNER_REVIEW_PROMPT]);
    expect(resolved.dismissed).toEqual([]);
  });

  test("local hydration can still fully reset onboarding state", async () => {
    const resolved = resolveHydratedOnboardingState(
      {
        onboardingCompleted: [ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS],
        onboardingDismissed: [ONBOARDING_STEPS.PARLAY_BUILDER],
      },
      {
        completed: [],
        dismissed: [],
      },
      "local",
    );

    expect(resolved.completed).toEqual([]);
    expect(resolved.dismissed).toEqual([]);
  });
});
