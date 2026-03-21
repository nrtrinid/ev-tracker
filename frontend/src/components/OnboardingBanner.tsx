"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useSettings, useUpdateSettings } from "@/lib/hooks";

interface OnboardingBannerProps {
  step: string;
  title: string;
  body: string;
}

export function OnboardingBanner({ step, title, body }: OnboardingBannerProps) {
  const { data: settings } = useSettings();
  const updateSettings = useUpdateSettings();
  const {
    onboardingCompleted,
    onboardingDismissed,
    hydrateOnboarding,
    markOnboardingCompleted,
    dismissOnboardingStep,
  } = useBettingPlatformStore();

  useEffect(() => {
    hydrateOnboarding(settings?.onboarding_state ?? null);
  }, [hydrateOnboarding, settings?.onboarding_state]);

  const hidden = onboardingCompleted.includes(step) || onboardingDismissed.includes(step);
  if (hidden) {
    return null;
  }

  const persist = (completed: string[], dismissed: string[]) => {
    updateSettings.mutate({
      onboarding_state: {
        ...(settings?.onboarding_state ?? {}),
        version: 1,
        completed,
        dismissed,
        last_seen_at: new Date().toISOString(),
      },
    });
  };

  const appendUnique = (items: string[], value: string) => (
    items.includes(value) ? items : [...items, value]
  );

  return (
    <div className="rounded-xl border border-[#C4A35A]/35 bg-[#FAF2DE] px-4 py-3 text-[#4A3D22] shadow-sm">
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-sm">{body}</p>
      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          onClick={() => {
            const completed = appendUnique(onboardingCompleted, step);
            markOnboardingCompleted(step);
            persist(completed, onboardingDismissed);
          }}
        >
          Got it
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            const dismissed = appendUnique(onboardingDismissed, step);
            dismissOnboardingStep(step);
            persist(onboardingCompleted, dismissed);
          }}
        >
          Dismiss
        </Button>
      </div>
    </div>
  );
}
