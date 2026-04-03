"use client";

import { Suspense, useState } from "react";
import { BetList } from "@/components/BetList";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { Plus } from "lucide-react";

export default function BetsPage() {
  const [logBetOpen, setLogBetOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);

  const openQuickLog = () => {
    setDrawerKey(Date.now());
    setLogBetOpen(true);
  };

  return (
    <div className="container mx-auto px-4 pt-4 pb-6 space-y-6 max-w-2xl">
      {/* Bet history ledger */}
      <div id="tracker">
        <Suspense fallback={null}>
          <BetList showWorkflowCoach={false} tutorialPracticeBet={null} />
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
