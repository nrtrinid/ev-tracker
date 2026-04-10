import { expect, test } from "@playwright/test";

import { resolveHydratedOnboardingState } from "@/lib/betting-platform-store";
import { ONBOARDING_STEPS } from "@/lib/onboarding";

test.describe("betting platform onboarding hydration", () => {
  test("remote hydration does not regress a locally completed tutorial step", async () => {
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

    expect(resolved.completed).toEqual([ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS]);
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
