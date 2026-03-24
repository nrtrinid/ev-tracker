"use client";

import { useEffect, useState } from "react";
import { Dashboard } from "@/components/Dashboard";
import { BetList } from "@/components/BetList";
import { JourneyCoach } from "@/components/JourneyCoach";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { isStraightBetsTutorialActive } from "@/app/scanner/scanner-tutorial";
import type { ScannedBetData } from "@/lib/types";
import { Plus } from "lucide-react";

export default function Home() {
  const [logBetOpen, setLogBetOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const [drawerInitialValues, setDrawerInitialValues] = useState<ScannedBetData | undefined>();
  const {
    isHydrated,
    scannerReviewCandidate,
    tutorialSession,
    clearScannerReviewCandidate,
    onboardingCompleted,
    onboardingDismissed,
  } = useBettingPlatformStore();
  const tutorialMode = isHydrated && isStraightBetsTutorialActive({
    surface: "straight_bets",
    completed: onboardingCompleted,
    dismissed: onboardingDismissed,
  });

  const openQuickLog = () => {
    setDrawerInitialValues(undefined);
    setDrawerKey(Date.now());
    setLogBetOpen(true);
  };

  const openSavedScannerPick = () => {
    if (!scannerReviewCandidate) return;
    setDrawerInitialValues(scannerReviewCandidate.bet);
    setDrawerKey(Date.now());
    setLogBetOpen(true);
  };

  const jumpToTracker = () => {
    const tracker = document.getElementById("tracker");
    tracker?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  useEffect(() => {
    if (tutorialSession?.step !== "home_review" || !tutorialSession.practice_bet) return;
    const timer = window.setTimeout(() => {
      jumpToTracker();
    }, 150);
    return () => window.clearTimeout(timer);
  }, [tutorialSession?.practice_bet, tutorialSession?.step]);

  return (
    <main className="min-h-screen bg-background">
      {/* Main Content */}
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-2xl pb-24">
        <JourneyCoach
          route="home"
          tutorialMode={tutorialMode}
          onReviewScannerPick={openSavedScannerPick}
        />
        {/* Dashboard Stats */}
        <Dashboard />

        {/* Bet History */}
        <div id="tracker">
          <BetList
            showWorkflowCoach={false}
            tutorialPracticeBet={tutorialSession?.step === "home_review" ? tutorialSession.practice_bet : null}
          />
        </div>
      </div>

      {/* Floating Action Button */}
      <button
        onClick={openQuickLog}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-5 py-3.5 rounded-full bg-foreground text-background shadow-lg hover:scale-105 transition-transform active:scale-95"
      >
        <Plus className="h-5 w-5" />
        <span className="font-semibold">Log Bet</span>
      </button>

      {/* Log Bet Drawer */}
      <LogBetDrawer
        key={drawerKey}
        open={logBetOpen}
        onOpenChange={setLogBetOpen}
        initialValues={drawerInitialValues}
        onLogged={() => {
          if (drawerInitialValues) {
            clearScannerReviewCandidate();
          }
        }}
      />
    </main>
  );
}
