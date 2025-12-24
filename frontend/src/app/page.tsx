"use client";

import { Dashboard } from "@/components/Dashboard";
import { BetEntryForm } from "@/components/BetEntryForm";
import { BetList } from "@/components/BetList";

export default function Home() {
  return (
    <main className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b sticky top-0 bg-background/95 backdrop-blur z-10">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-xl font-bold">EV Tracker</h1>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-2xl">
        {/* Dashboard Stats */}
        <Dashboard />

        {/* Bet Entry Form */}
        <BetEntryForm />

        {/* Bet History */}
        <BetList />
      </div>
    </main>
  );
}
