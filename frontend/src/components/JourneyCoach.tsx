"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, MapPin, X } from "lucide-react";

import { Button } from "@/components/ui/button";
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
  if (icon === "check") return <CheckCircle2 className="ml-2 h-3.5 w-3.5" />;
  if (icon === "arrow") return <ArrowRight className="ml-2 h-3.5 w-3.5" />;
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
    if (!command) return;

    if (command === "start_tutorial") {
      startTutorialSession("straight_bets");
      markTutorialScanSeeded();
      onStartTutorial?.();
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

  if (!isHydrated || !candidate) return null;

  if (candidate.persistStep) {
    const hidden =
      onboardingCompleted.includes(candidate.persistStep) ||
      onboardingDismissed.includes(candidate.persistStep);
    if (hidden) return null;
  }

  if (candidate.dismissStep && onboardingDismissed.includes(candidate.dismissStep)) return null;
  if (temporarilyHiddenKey === candidate.key) return null;

  // Determine if this card has a primary CTA (first non-outline action)
  const primaryAction = candidate.actions?.find((a) => !a.variant || a.variant === "default");
  const secondaryActions = candidate.actions?.filter((a) => a !== primaryAction) ?? [];

  return (
    <div className="rounded-lg border border-primary/25 bg-card overflow-hidden animate-slide-up">
      {/* Amber accent bar at top */}
      <div className="h-0.5 w-full bg-gradient-to-r from-primary/60 via-primary to-primary/60" />

      <div className="p-4 space-y-3.5">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5 min-w-0">
            <div className="mt-0.5 shrink-0 rounded-md bg-primary/12 p-1.5 text-primary">
              <MapPin className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
                {candidate.eyebrow}
              </p>
              <h2 className="mt-0.5 text-sm font-semibold text-foreground leading-snug">
                {candidate.title}
              </h2>
              <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                {candidate.body}
              </p>
            </div>
          </div>
          {candidate.persistStep && (
            <button
              type="button"
              className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
              onClick={() => handleDismiss(candidate.persistStep!)}
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Step tracker */}
        {candidate.steps && (
          <div className="grid grid-cols-3 gap-1.5">
            {candidate.steps.map((step, index) => (
              <div
                key={step.label}
                className={cn(
                  "rounded border px-2.5 py-2 text-center transition-colors",
                  step.complete
                    ? "border-primary/20 bg-primary/8"
                    : step.active
                      ? "border-primary/35 bg-primary/12"
                      : "border-border/50 bg-background/40"
                )}
              >
                <div className="flex items-center justify-center">
                  {step.complete ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
                  ) : (
                    <Circle
                      className={cn(
                        "h-3.5 w-3.5",
                        step.active ? "text-primary" : "text-muted-foreground/40"
                      )}
                    />
                  )}
                </div>
                <p
                  className={cn(
                    "mt-1 text-[10px] font-medium leading-tight",
                    step.complete || step.active ? "text-foreground" : "text-muted-foreground/60"
                  )}
                >
                  {index + 1}. {step.label}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Detail block */}
        {candidate.detailTitle && (
          <div className="rounded border border-border/60 bg-background/60 px-3 py-2">
            <p className="text-xs font-medium text-foreground">{candidate.detailTitle}</p>
            {candidate.detailBody && (
              <p className="mt-0.5 text-[11px] text-muted-foreground">{candidate.detailBody}</p>
            )}
          </div>
        )}

        {/* Actions */}
        {candidate.actions && candidate.actions.length > 0 ? (
          <div className="flex flex-col gap-2">
            {/* Primary CTA — full width, visually prominent */}
            {primaryAction && (
              <ActionButton
                action={primaryAction}
                isPrimary
                onCommand={handleActionCommand}
                onHide={() => {
                  clearHighlight();
                  if (candidate.dismissStep) {
                    handleDismiss(candidate.dismissStep);
                  } else {
                    setTemporarilyHiddenKey(candidate.key);
                  }
                }}
                onComplete={() => {
                  if (candidate.persistStep) handleComplete(candidate.persistStep);
                }}
              />
            )}
            {/* Secondary actions — row */}
            {secondaryActions.length > 0 && (
              <div className="flex gap-2">
                {secondaryActions.map((action) => (
                  <ActionButton
                    key={action.label}
                    action={action}
                    isPrimary={false}
                    onCommand={handleActionCommand}
                    onHide={() => {
                      clearHighlight();
                      if (candidate.dismissStep) {
                        handleDismiss(candidate.dismissStep);
                      } else {
                        setTemporarilyHiddenKey(candidate.key);
                      }
                    }}
                    onComplete={() => {
                      if (candidate.persistStep) handleComplete(candidate.persistStep);
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        ) : candidate.persistStep ? (
          <Button
            type="button"
            size="sm"
            className="w-full h-9 text-xs font-semibold"
            onClick={() => handleComplete(candidate.persistStep!)}
          >
            Got It
          </Button>
        ) : null}
      </div>
    </div>
  );
}

// ── ActionButton helper ───────────────────────────────────────────────────────

interface ActionButtonProps {
  action: JourneyCoachAction;
  isPrimary: boolean;
  onCommand: (command?: JourneyCoachActionCommand) => void;
  onHide: () => void;
  onComplete: () => void;
}

function ActionButton({ action, isPrimary, onCommand, onHide, onComplete }: ActionButtonProps) {
  const actionTarget = getActionTarget(action.command);

  const handleClick = () => {
    onCommand(action.command);
    if (action.hideOnClick) onHide();
    if (action.completeStepOnClick) onComplete();
  };

  const baseClass = isPrimary
    ? "w-full h-9 rounded-md px-4 text-xs font-semibold transition-all duration-150 active:scale-[0.98] flex items-center justify-center bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
    : "flex-1 h-8 rounded-md px-3 text-xs font-medium transition-all duration-150 active:scale-[0.98] flex items-center justify-center border border-border/70 bg-background/60 text-muted-foreground hover:text-foreground hover:bg-muted/50 hover:border-border";

  if (action.href) {
    return (
      <Link
        href={action.href}
        data-onboarding-target={actionTarget}
        onClick={handleClick}
        className={baseClass}
      >
        {action.label}
        {renderActionIcon(action.icon)}
      </Link>
    );
  }

  return (
    <button
      type="button"
      data-onboarding-target={actionTarget}
      onClick={handleClick}
      className={baseClass}
    >
      {action.label}
      {renderActionIcon(action.icon)}
    </button>
  );
}
