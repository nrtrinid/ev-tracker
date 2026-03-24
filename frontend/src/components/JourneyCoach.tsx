"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { STRAIGHT_BETS_TUTORIAL_STEP } from "@/app/scanner/scanner-tutorial";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useBets, useSettings, useUpdateSettings } from "@/lib/hooks";
import type { ScannerSurface } from "@/lib/types";
import { cn } from "@/lib/utils";

type JourneyCoachRoute = "home" | "scanner" | "parlay";

interface JourneyCoachAction {
  label: string;
  href?: string;
  onClick?: () => void;
  variant?: "default" | "outline" | "secondary" | "ghost";
  icon?: "arrow" | "check";
  hideOnClick?: boolean;
  completeStepOnClick?: boolean;
}

interface JourneyCoachStep {
  label: string;
  complete: boolean;
  active: boolean;
}

interface JourneyCoachCandidate {
  key: string;
  persistStep?: string;
  dismissStep?: string;
  eyebrow: string;
  title: string;
  body: string;
  actions?: JourneyCoachAction[];
  steps?: JourneyCoachStep[];
  detailTitle?: string;
  detailBody?: string;
}

interface JourneyCoachProps {
  route: JourneyCoachRoute;
  scannerSurface?: ScannerSurface;
  scannerDrawerOpen?: boolean;
  tutorialMode?: boolean;
  onReviewScannerPick?: () => void;
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

export function JourneyCoach({
  route,
  scannerSurface,
  scannerDrawerOpen = false,
  tutorialMode = false,
  onReviewScannerPick,
}: JourneyCoachProps) {
  const { data: bets } = useBets();
  const { data: settings } = useSettings();
  const updateSettings = useUpdateSettings();
  const {
    isHydrated,
    cart,
    scannerReviewCandidate,
    tutorialSession,
    onboardingCompleted,
    onboardingDismissed,
    hydrateOnboarding,
    startTutorialSession,
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
  const activeScannerReviewCandidate =
    route === "scanner" && scannerReviewCandidate?.surface === scannerSurface
      ? scannerReviewCandidate
      : null;
  const tutorialPracticeBet = tutorialSession?.practice_bet ?? null;

  const homeSteps = useMemo<JourneyCoachStep[]>(() => {
    const hasSavedScannerPick = Boolean(scannerReviewCandidate);
    return [
      {
        label: "Find a play",
        complete: hasSavedScannerPick || hasLoggedBet,
        active: !hasSavedScannerPick && !hasLoggedBet,
      },
      {
        label: "Place it",
        complete: hasSavedScannerPick || hasLoggedBet,
        active: hasSavedScannerPick,
      },
      {
        label: "Log it",
        complete: hasLoggedBet && !hasSavedScannerPick,
        active: hasSavedScannerPick,
      },
    ];
  }, [hasLoggedBet, scannerReviewCandidate]);

  const candidate = useMemo<JourneyCoachCandidate | null>(() => {
    if (route === "home") {
      if (tutorialMode && tutorialPracticeBet) {
        return {
          key: "home-tutorial-review",
          persistStep: STRAIGHT_BETS_TUTORIAL_STEP,
          eyebrow: "Step 3 of 3",
          title: "Review your practice ticket on Home",
          body: "Nice work. This local practice ticket is now sitting above your real Open Bets so you can see where scanner plays land in the tracker.",
          steps: [
            { label: "Open tutorial", complete: true, active: false },
            { label: "Run scan", complete: true, active: false },
            { label: "Review on Home", complete: false, active: true },
          ],
          detailTitle: tutorialPracticeBet.event,
          detailBody: `${tutorialPracticeBet.market} / ${tutorialPracticeBet.sportsbook}`,
          actions: [
            {
              label: "Finish Tutorial",
              icon: "check",
              onClick: clearTutorialSession,
              completeStepOnClick: true,
            },
          ],
        };
      }

      if (tutorialMode) {
        return {
          key: "home-tutorial-intro",
          persistStep: STRAIGHT_BETS_TUTORIAL_STEP,
          eyebrow: "Straight-Bets Tutorial",
          title: "Learn the scanner with one practice ticket",
          body: "Start on Home, run one guided tutorial scan, practice logging a sample bet, then come right back here to see where it appears in your tracker.",
          steps: [
            { label: "Open tutorial", complete: false, active: true },
            { label: "Run scan", complete: false, active: false },
            { label: "Review on Home", complete: false, active: false },
          ],
          actions: [
            {
              label: "Open Tutorial Scanner",
              href: "/scanner/straight_bets",
              icon: "arrow",
              onClick: () => startTutorialSession("straight_bets"),
            },
          ],
        };
      }

      if (scannerReviewCandidate) {
        return {
          key: `home-review-${scannerReviewCandidate.createdAt}`,
          dismissStep: "home_scanner_review",
          eyebrow: "Step 3 of 3",
          title: "Finish the ticket you already placed",
          body: "Your last scanner pick is saved here. Review it now so it lands in Open Bets and stays easy to track.",
          steps: homeSteps,
          actions: [
            {
              label: "Review Saved Pick",
              onClick: onReviewScannerPick,
              icon: "check",
            },
            {
              label: "Not Now",
              variant: "outline",
              hideOnClick: true,
            },
          ],
          detailTitle: scannerReviewCandidate.bet.event,
          detailBody: `${scannerReviewCandidate.bet.market} / ${scannerReviewCandidate.bet.sportsbook}`,
        };
      }

      if (tutorialDismissed) {
        return null;
      }

      return null;
    }

    if (route === "scanner") {
      if (tutorialMode && scannerSurface === "straight_bets") {
        if (tutorialPracticeBet) {
          return {
            key: "scanner-tutorial-return-home",
            eyebrow: "Tutorial Complete",
            title: "Head back Home to finish the practice loop",
            body: "Your practice ticket is waiting in the tracker. That Home review is the last step before the live scanner takes over.",
            actions: [
              {
                label: "Go to Home",
                href: "/",
                icon: "arrow",
              },
            ],
          };
        }

        if (!tutorialSession?.has_seeded_scan) {
          return {
            key: "scanner-tutorial-empty",
            persistStep: STRAIGHT_BETS_TUTORIAL_STEP,
            eyebrow: "Step 1 of 3",
            title: "Run one tutorial scan",
            body: "Start from an empty scanner so the workflow feels real. Tap the tutorial scan button once and we will populate sample straight bets for practice.",
            steps: [
              { label: "Open tutorial", complete: true, active: false },
              { label: "Run scan", complete: false, active: true },
              { label: "Review on Home", complete: false, active: false },
            ],
          };
        }

        return {
          key: "scanner-tutorial-ready",
          persistStep: STRAIGHT_BETS_TUTORIAL_STEP,
          eyebrow: "Step 2 of 3",
          title: "Pick one sample line and practice logging it",
          body: "Open one sample card and save a practice ticket. When it is ready, use the Home prompt to review the final step there.",
          steps: [
            { label: "Open tutorial", complete: true, active: false },
            { label: "Run scan", complete: true, active: false },
            { label: "Review on Home", complete: false, active: true },
          ],
          detailTitle: "Tutorial reminder",
          detailBody: "Practice tickets stay local to this walkthrough and never affect your real stats or bankroll.",
        };
      }

      if (activeScannerReviewCandidate && !scannerDrawerOpen) {
        return {
          key: `scanner-review-${activeScannerReviewCandidate.createdAt}`,
          dismissStep: "scanner_review_prompt",
          eyebrow: "Step 3 of 3",
          title: `Placed it at ${activeScannerReviewCandidate.bet.sportsbook}? Review and log it.`,
          body: "We saved your last scanner pick so you can come back and confirm the bet in a few taps.",
          detailTitle: activeScannerReviewCandidate.bet.event,
          detailBody: `${activeScannerReviewCandidate.bet.market} / ${activeScannerReviewCandidate.bet.sportsbook}`,
          actions: [
            {
              label: "Review & Log Bet",
              onClick: onReviewScannerPick,
              icon: "check",
            },
            {
              label: "Keep Scanning",
              variant: "outline",
              hideOnClick: true,
            },
          ],
        };
      }

      if (tutorialDismissed) {
        return null;
      }

      return null;
    }

    if (route === "parlay") {
      if (tutorialDismissed) {
        return null;
      }

      if (cart.length === 0) {
        return {
          key: "parlay_builder",
          persistStep: "parlay_builder",
          eyebrow: "Optional Step",
          title: "Build parlays later, after you find the plays",
          body: "The simplest beginner path is still one ticket at a time. When you want a multi-leg preview, add a couple of plays in Scanner first.",
          actions: [
            {
              label: "Find Legs in Scanner",
              href: "/scanner/straight_bets",
              icon: "arrow",
              completeStepOnClick: true,
            },
          ],
        };
      }

      if (cart.length === 1) {
        return {
          key: "parlay-one-leg",
          dismissStep: "parlay_one_leg_prompt",
          eyebrow: "Optional Step",
          title: "Add one more leg to complete the preview",
          body: "You have one leg saved so far. Grab one more in Scanner, then come back here to compare the combined payout.",
          actions: [
            {
              label: "Add Another Leg",
              href: "/scanner/straight_bets",
              icon: "arrow",
            },
            {
              label: "Not Now",
              variant: "outline",
              hideOnClick: true,
            },
          ],
        };
      }
    }

    return null;
  }, [
    activeScannerReviewCandidate,
    cart.length,
    homeSteps,
    onReviewScannerPick,
    route,
    scannerDrawerOpen,
    scannerReviewCandidate,
    scannerSurface,
    startTutorialSession,
    clearTutorialSession,
    tutorialDismissed,
    tutorialPracticeBet,
    tutorialSession?.has_seeded_scan,
    tutorialMode,
  ]);

  useEffect(() => {
    setTemporarilyHiddenKey(null);
  }, [candidate?.key]);

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

  const handleComplete = (step: string) => {
    const completed = appendUnique(onboardingCompleted, step);
    markOnboardingCompleted(step);
    persist(completed, onboardingDismissed);
  };

  const handleDismiss = (step: string) => {
    const dismissed = appendUnique(onboardingDismissed, step);
    dismissOnboardingStep(step);
    if (step === STRAIGHT_BETS_TUTORIAL_STEP) {
      clearTutorialSession();
    }
    persist(onboardingCompleted, dismissed);
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
              const handleClick = () => {
                action.onClick?.();
                if (action.hideOnClick) {
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
                    <Link href={action.href} onClick={handleClick}>
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
