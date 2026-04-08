"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { STRAIGHT_BETS_TUTORIAL_STEP } from "@/app/scanner/scanner-tutorial";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useApplyOnboardingEvent, useBets, useSettings } from "@/lib/hooks";
import { useOnboardingHighlight } from "@/lib/onboarding-highlight";
import { ONBOARDING_HIGHLIGHT_TARGETS } from "@/lib/onboarding-guidance";
import {
  selectJourneyCoachCandidate,
  type JourneyCoachAction,
  type JourneyCoachActionCommand,
  type JourneyCoachRoute,
  type JourneyCoachStep,
} from "@/lib/journey-coach-registry";
import type { OnboardingStepId, ScannerSurface } from "@/lib/types";
import { cn } from "@/lib/utils";

interface JourneyCoachProps {
  route: JourneyCoachRoute;
  scannerSurface?: ScannerSurface;
  scannerDrawerOpen?: boolean;
  tutorialMode?: boolean;
  onReviewScannerPick?: () => void;
  onStartTutorial?: () => void;
  onFinishTutorial?: () => void;
}

function renderActionIcon(icon: JourneyCoachAction["icon"]) {
  if (icon === "check") {
    return <CheckCircle2 className="ml-2 h-4 w-4" />;
  }
  if (icon === "arrow") {
    return <ArrowRight className="ml-2 h-4 w-4" />;
  }
  return null;
}

function getActionTarget(command?: JourneyCoachActionCommand) {
  if (command === "start_tutorial") {
    return ONBOARDING_HIGHLIGHT_TARGETS.COACH_START_WALKTHROUGH;
  }
  return undefined;
}

export function JourneyCoach({
  route,
  scannerSurface,
  scannerDrawerOpen = false,
  tutorialMode = false,
  onReviewScannerPick,
  onStartTutorial,
  onFinishTutorial,
}: JourneyCoachProps) {
  const { data: bets } = useBets();
  const { data: settings } = useSettings();
  const applyOnboardingEvent = useApplyOnboardingEvent();
  const { highlight, clear: clearHighlight } = useOnboardingHighlight();
  const {
    isHydrated,
    cart,
    scannerReviewCandidate,
    tutorialSession,
    onboardingCompleted,
    onboardingDismissed,
    hydrateOnboarding,
    startTutorialSession,
    markTutorialScanSeeded,
    clearTutorialSession,
    markOnboardingCompleted,
    dismissOnboardingStep,
  } = useBettingPlatformStore();
  const [temporarilyHiddenKey, setTemporarilyHiddenKey] = useState<string | null>(null);

  useEffect(() => {
    hydrateOnboarding(settings?.onboarding_state ?? null, "remote");
  }, [hydrateOnboarding, settings?.onboarding_state]);

  const hasLoggedBet = (bets?.length ?? 0) > 0;
  const tutorialDismissed = onboardingDismissed.includes(STRAIGHT_BETS_TUTORIAL_STEP);
  const tutorialPracticeBet = tutorialSession?.practice_bet ?? null;

  const homeSteps = useMemo<JourneyCoachStep[]>(() => {
    const hasSavedScannerPick = Boolean(scannerReviewCandidate);
    return [
      {
        label: "Open Markets",
        complete: hasSavedScannerPick || hasLoggedBet,
        active: !hasSavedScannerPick && !hasLoggedBet,
      },
      {
        label: "Place at Book",
        complete: hasSavedScannerPick || hasLoggedBet,
        active: hasSavedScannerPick,
      },
      {
        label: "Review & Log",
        complete: hasLoggedBet && !hasSavedScannerPick,
        active: hasSavedScannerPick,
      },
    ];
  }, [hasLoggedBet, scannerReviewCandidate]);

  const candidate = useMemo(
    () =>
      selectJourneyCoachCandidate({
        route,
        scannerSurface,
        scannerDrawerOpen,
        tutorialMode,
        tutorialDismissed,
        scannerReviewCandidate,
        tutorialPracticeBet,
        tutorialHasSeededScan: Boolean(tutorialSession?.has_seeded_scan),
        cartLength: cart.length,
        homeSteps,
      }),
    [
      cart.length,
      homeSteps,
      route,
      scannerDrawerOpen,
      scannerReviewCandidate,
      scannerSurface,
      tutorialDismissed,
      tutorialMode,
      tutorialPracticeBet,
      tutorialSession?.has_seeded_scan,
    ]
  );

  useEffect(() => {
    setTemporarilyHiddenKey(null);
  }, [candidate?.key]);

  useEffect(() => {
    if (!isHydrated || !candidate) {
      clearHighlight();
      return;
    }

    if (route === "home" && candidate.key === "home-tutorial-intro") {
      if (tutorialSession?.has_seeded_scan) {
        highlight(ONBOARDING_HIGHLIGHT_TARGETS.MARKETS_PRACTICE_PLACE);
      } else {
        clearHighlight();
      }
      return;
    }

    if (route === "home" && candidate.key === "home-tutorial-review") {
      highlight(ONBOARDING_HIGHLIGHT_TARGETS.NAV_BETS_TAB);
      return;
    }

    if (route === "scanner" && candidate.key.startsWith("scanner-tutorial")) {
      highlight(ONBOARDING_HIGHLIGHT_TARGETS.NAV_MARKETS_TAB);
      return;
    }

    if (route === "bets" && candidate.key === "bets-tutorial-review") {
      clearHighlight();
      return;
    }

    clearHighlight();
  }, [
    candidate,
    clearHighlight,
    highlight,
    isHydrated,
    route,
    tutorialSession?.has_seeded_scan,
  ]);

  const handleComplete = (step: OnboardingStepId) => {
    markOnboardingCompleted(step);
    clearHighlight();
    applyOnboardingEvent.mutate({ event: "complete_step", step });
  };

  const handleDismiss = (step: OnboardingStepId) => {
    dismissOnboardingStep(step);
    if (step === STRAIGHT_BETS_TUTORIAL_STEP) {
      clearTutorialSession();
    }
    clearHighlight();
    applyOnboardingEvent.mutate({ event: "dismiss_step", step });
  };

  const handleActionCommand = (command?: JourneyCoachActionCommand) => {
    if (!command) {
      return;
    }

    if (command === "start_tutorial") {
      startTutorialSession("straight_bets");
      markTutorialScanSeeded();
      onStartTutorial?.();
      return;
    }

    if (command === "clear_tutorial") {
      clearTutorialSession();
      clearHighlight();
      return;
    }

    if (command === "review_scanner_pick") {
      onReviewScannerPick?.();
      window.setTimeout(() => {
        highlight(ONBOARDING_HIGHLIGHT_TARGETS.DRAWER_SAVE_PRACTICE_TICKET);
      }, 120);
      return;
    }

    if (command === "finish_tutorial") {
      clearHighlight();
      onFinishTutorial?.();
    }
  };

  if (!isHydrated || !candidate) {
    return null;
  }

  if (candidate.persistStep) {
    const hidden =
      onboardingCompleted.includes(candidate.persistStep) ||
      onboardingDismissed.includes(candidate.persistStep);
    if (hidden) {
      return null;
    }
  }

  if (candidate.dismissStep && onboardingDismissed.includes(candidate.dismissStep)) {
    return null;
  }

  if (temporarilyHiddenKey === candidate.key) {
    return null;
  }

  return (
    <Card className="border-primary/20 bg-primary/10">
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
              {candidate.eyebrow}
            </p>
            <h2 className="mt-1 text-base font-semibold text-foreground">{candidate.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{candidate.body}</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="rounded-full bg-background/80 p-2 text-primary">
              <Sparkles className="h-4 w-4" />
            </div>
            {candidate.persistStep && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => handleDismiss(candidate.persistStep!)}
                aria-label="Hide coach"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {candidate.steps && (
          <div className="grid grid-cols-3 gap-2">
            {candidate.steps.map((step, index) => (
              <div
                key={step.label}
                className={cn(
                  "rounded-lg border px-3 py-2 text-center",
                  step.active ? "border-primary/35 bg-background/80" : "border-border bg-background/50"
                )}
              >
                <div className="flex items-center justify-center">
                  {step.complete ? (
                    <CheckCircle2 className="h-4 w-4 text-primary" />
                  ) : (
                    <Circle className={cn("h-4 w-4", step.active ? "text-primary" : "text-muted-foreground/50")} />
                  )}
                </div>
                <p className="mt-1 text-[11px] font-medium text-foreground">
                  {index + 1}. {step.label}
                </p>
              </div>
            ))}
          </div>
        )}

        {candidate.detailTitle && (
          <div className="rounded-lg border border-border bg-background/80 px-3 py-2">
            <p className="text-sm font-medium text-foreground">{candidate.detailTitle}</p>
            {candidate.detailBody && (
              <p className="mt-0.5 text-xs text-muted-foreground">{candidate.detailBody}</p>
            )}
          </div>
        )}

        {candidate.actions && candidate.actions.length > 0 ? (
          <div className="flex flex-col gap-2 sm:flex-row">
            {candidate.actions.map((action) => {
              const actionTarget = getActionTarget(action.command);
              const handleClick = () => {
                handleActionCommand(action.command);
                if (action.hideOnClick) {
                  clearHighlight();
                  if (candidate.dismissStep) {
                    handleDismiss(candidate.dismissStep);
                  } else {
                    setTemporarilyHiddenKey(candidate.key);
                  }
                }
                if (action.completeStepOnClick && candidate.persistStep) {
                  handleComplete(candidate.persistStep);
                }
              };

              if (action.href) {
                return (
                  <Button
                    key={action.label}
                    asChild
                    variant={action.variant ?? "default"}
                    className="h-11 flex-1"
                  >
                    <Link
                      href={action.href}
                      data-onboarding-target={actionTarget}
                      onClick={handleClick}
                    >
                      {action.label}
                      {renderActionIcon(action.icon)}
                    </Link>
                  </Button>
                );
              }

              return (
                <Button
                  key={action.label}
                  type="button"
                  variant={action.variant ?? "default"}
                  className="h-11 flex-1"
                  data-onboarding-target={actionTarget}
                  onClick={handleClick}
                >
                  {action.label}
                  {renderActionIcon(action.icon)}
                </Button>
              );
            })}
          </div>
        ) : candidate.persistStep ? (
          <Button type="button" className="h-11 w-full sm:w-auto" onClick={() => handleComplete(candidate.persistStep!)}>
            Got It
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
