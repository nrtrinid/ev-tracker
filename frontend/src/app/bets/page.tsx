"use client";

import { Suspense, useState } from "react";
import { useRouter } from "next/navigation";
import { BetList } from "@/components/BetList";
import { JourneyCoach } from "@/components/JourneyCoach";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { useApplyOnboardingEvent } from "@/lib/hooks";
import { ONBOARDING_STEPS } from "@/lib/onboarding";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { isStraightBetsTutorialActive } from "@/app/scanner/scanner-tutorial";
import { Plus } from "lucide-react";

export default function BetsPage() {
  const router = useRouter();
  const applyOnboardingEvent = useApplyOnboardingEvent();
  const {
    tutorialSession,
    onboardingCompleted,
    onboardingDismissed,
    clearTutorialSession,
    clearScannerReviewCandidate,
    markOnboardingCompleted,
  } = useBettingPlatformStore();
  const tutorialPracticeBet = tutorialSession?.practice_bet ?? null;
  const [logBetOpen, setLogBetOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const tutorialMode = isStraightBetsTutorialActive({
    surface: "straight_bets",
    completed: onboardingCompleted,
    dismissed: onboardingDismissed,
  });

  const openQuickLog = () => {
    setDrawerKey(Date.now());
    setLogBetOpen(true);
  };

  const handleFinishTutorial = () => {
    markOnboardingCompleted(ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS);
    clearTutorialSession();
    clearScannerReviewCandidate();
    applyOnboardingEvent.mutate({
      event: "complete_step",
      step: ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
    });
    router.push("/?onboarding=complete");
  };

  return (
    <div className="container mx-auto px-4 pt-4 pb-6 space-y-6 max-w-2xl">
      <JourneyCoach
        route="bets"
        tutorialMode={tutorialMode}
        onFinishTutorial={handleFinishTutorial}
      />

      {/* Bet history ledger */}
      <div id="tracker">
        <Suspense fallback={null}>
          <BetList
            showWorkflowCoach={false}
            tutorialPracticeBet={tutorialPracticeBet}
          />
        </Suspense>
      </div>

      {/* Floating Log Bet button */}
      <button
        onClick={openQuickLog}
        className="fixed bottom-24 right-4 z-40 flex items-center gap-2 px-4 py-3 rounded-full bg-foreground text-background shadow-lg animate-fab-enter hover:scale-105 active:scale-95 transition-transform"
        style={{ animationDelay: "200ms", animationFillMode: "both" }}
      >
        <Plus className="h-4 w-4" />
        <span className="font-semibold text-sm">Log Bet</span>
      </button>

      <LogBetDrawer
        key={drawerKey}
        open={logBetOpen}
        onOpenChange={setLogBetOpen}
      />
    </div>
  );
}
