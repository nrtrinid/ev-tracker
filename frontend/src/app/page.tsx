"use client";

import { Dashboard } from "@/components/Dashboard";
import { BetEntryForm } from "@/components/BetEntryForm";
import { BetList } from "@/components/BetList";
import Link from "next/link";
import { Calculator, BarChart3 } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b sticky top-0 bg-background/95 backdrop-blur z-10">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold">EV Tracker</h1>
          <nav className="flex items-center gap-1">
            <Link 
              href="/tools" 
              className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title="Tools"
            >
              <Calculator className="h-5 w-5" />
            </Link>
            <Link 
              href="/analytics" 
              className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title="Analytics"
            >
              <BarChart3 className="h-5 w-5" />
            </Link>
          </nav>
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
