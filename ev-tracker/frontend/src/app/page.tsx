"use client";

import { useState } from "react";
import { Dashboard } from "@/components/Dashboard";
import { BetList } from "@/components/BetList";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { Plus } from "lucide-react";

export default function Home() {
  const [logBetOpen, setLogBetOpen] = useState(false);

  return (
    <main className="min-h-screen bg-background">
      {/* Main Content */}
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-2xl pb-24">
        {/* Dashboard Stats */}
        <Dashboard />

        {/* Bet History */}
        <BetList />
      </div>

      {/* Floating Action Button */}
      <button
        onClick={() => setLogBetOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-5 py-3.5 rounded-full bg-foreground text-background shadow-lg hover:scale-105 transition-transform active:scale-95"
      >
        <Plus className="h-5 w-5" />
        <span className="font-semibold">Log Bet</span>
      </button>

      {/* Log Bet Drawer */}
      <LogBetDrawer open={logBetOpen} onOpenChange={setLogBetOpen} />
    </main>
  );
}
