"use client";

import { useState } from "react";
import { Dashboard } from "@/components/Dashboard";
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
      {/* KPI summary */}
      <Dashboard />

      {/* Bet history ledger */}
      <div id="tracker">
        <BetList showWorkflowCoach={false} tutorialPracticeBet={null} />
      </div>

      {/* Floating Log Bet button */}
      <button
        onClick={openQuickLog}
        className="fixed bottom-24 right-4 z-40 flex items-center gap-2 px-4 py-3 rounded-full bg-foreground text-background shadow-lg hover:scale-105 transition-transform active:scale-95"
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
