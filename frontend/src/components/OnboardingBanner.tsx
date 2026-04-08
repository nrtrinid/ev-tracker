"use client";

import Link from "next/link";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useApplyOnboardingEvent, useSettings } from "@/lib/hooks";
import type { OnboardingStepId } from "@/lib/types";

interface OnboardingBannerAction {
  label: string;
  href?: string;
  onClick?: () => void;
  variant?: "default" | "outline" | "secondary" | "ghost";
  completeStepOnClick?: boolean;
}

interface OnboardingBannerProps {
  step: OnboardingStepId;
  title: string;
  body: string;
  eyebrow?: string;
  action?: OnboardingBannerAction;
}

export function OnboardingBanner({
  step,
  title,
  body,
  eyebrow = "Quick Tip",
  action,
}: OnboardingBannerProps) {
  const { data: settings } = useSettings();
  const applyOnboardingEvent = useApplyOnboardingEvent();
  const {
    isHydrated,
    onboardingCompleted,
    onboardingDismissed,
    hydrateOnboarding,
    markOnboardingCompleted,
    dismissOnboardingStep,
  } = useBettingPlatformStore();

  useEffect(() => {
    hydrateOnboarding(settings?.onboarding_state ?? null, "remote");
  }, [hydrateOnboarding, settings?.onboarding_state]);

  if (!isHydrated) {
    return null;
  }

  const hidden = onboardingCompleted.includes(step) || onboardingDismissed.includes(step);
  if (hidden) {
    return null;
  }

  const handleComplete = () => {
    markOnboardingCompleted(step);
    applyOnboardingEvent.mutate({ event: "complete_step", step });
  };

  const handleDismiss = () => {
    dismissOnboardingStep(step);
    applyOnboardingEvent.mutate({ event: "dismiss_step", step });
  };

  const handleAction = () => {
    action?.onClick?.();
    if (action?.completeStepOnClick) {
      handleComplete();
    }
  };

  return (
    <div className="rounded-xl border border-[#C4A35A]/35 bg-[#FAF2DE] px-4 py-3 text-[#4A3D22] shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8B6B2F]">
            {eyebrow}
          </p>
          <p className="mt-1 text-sm font-semibold">{title}</p>
          <p className="mt-1 text-sm leading-relaxed">{body}</p>
        </div>
        <div className="rounded-full border border-[#C4A35A]/35 bg-white/70 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8B6B2F]">
          New
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {action && (
          action.href ? (
            <Button asChild size="sm" className="h-10 sm:h-9" variant={action.variant ?? "default"}>
              <Link href={action.href} onClick={handleAction}>
                {action.label}
              </Link>
            </Button>
          ) : (
            <Button size="sm" className="h-10 sm:h-9" variant={action.variant ?? "default"} onClick={handleAction}>
              {action.label}
            </Button>
          )
        )}
        <Button size="sm" className="h-10 sm:h-9" variant={action ? "secondary" : "default"} onClick={handleComplete}>
          Done for Now
        </Button>
        <Button size="sm" className="h-10 sm:h-9" variant="outline" onClick={handleDismiss}>
          Hide Tip
        </Button>
      </div>
    </div>
  );
}
