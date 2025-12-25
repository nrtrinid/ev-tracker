"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn, americanToDecimal, formatPercent } from "@/lib/utils";
import { Calculator, ArrowLeft, TrendingUp, AlertCircle, CheckCircle } from "lucide-react";
import Link from "next/link";

// Calculate hold % from two American odds
function calculateHold(odds1: number, odds2: number): {
  hold: number;
  impliedProb1: number;
  impliedProb2: number;
  fairOdds1: number;
  fairOdds2: number;
  quality: "excellent" | "good" | "fair" | "poor";
} {
  const decimal1 = americanToDecimal(odds1);
  const decimal2 = americanToDecimal(odds2);
  
  // Implied probabilities (includes vig)
  const impliedProb1 = 1 / decimal1;
  const impliedProb2 = 1 / decimal2;
  
  // Total implied probability (should be >100% due to vig)
  const totalImplied = impliedProb1 + impliedProb2;
  
  // Hold % (vig)
  const hold = totalImplied - 1;
  
  // Fair probabilities (remove vig proportionally)
  const fairProb1 = impliedProb1 / totalImplied;
  const fairProb2 = impliedProb2 / totalImplied;
  
  // Convert back to American odds
  const fairOdds1 = fairProb1 >= 0.5 
    ? -100 * fairProb1 / (1 - fairProb1)
    : 100 * (1 - fairProb1) / fairProb1;
  const fairOdds2 = fairProb2 >= 0.5
    ? -100 * fairProb2 / (1 - fairProb2)
    : 100 * (1 - fairProb2) / fairProb2;
  
  // Quality rating based on typical sportsbook holds
  let quality: "excellent" | "good" | "fair" | "poor";
  if (hold <= 0.03) quality = "excellent";
  else if (hold <= 0.045) quality = "good";
  else if (hold <= 0.06) quality = "fair";
  else quality = "poor";
  
  return {
    hold,
    impliedProb1,
    impliedProb2,
    fairOdds1: Math.round(fairOdds1),
    fairOdds2: Math.round(fairOdds2),
    quality,
  };
}

const qualityConfig = {
  excellent: { label: "Excellent", color: "text-green-600", bg: "bg-green-50", desc: "Sharp line, great for +EV" },
  good: { label: "Good", color: "text-blue-600", bg: "bg-blue-50", desc: "Solid market, reasonable vig" },
  fair: { label: "Fair", color: "text-yellow-600", bg: "bg-yellow-50", desc: "Average hold, acceptable" },
  poor: { label: "Poor", color: "text-red-600", bg: "bg-red-50", desc: "High vig, less favorable" },
};

export default function ToolsPage() {
  const [odds1, setOdds1] = useState("");
  const [odds2, setOdds2] = useState("");
  
  const odds1Num = parseFloat(odds1) || 0;
  const odds2Num = parseFloat(odds2) || 0;
  
  const canCalculate = odds1Num !== 0 && odds2Num !== 0 && 
    (Math.abs(odds1Num) >= 100 || odds1Num === 0) && 
    (Math.abs(odds2Num) >= 100 || odds2Num === 0);
  
  const result = canCalculate ? calculateHold(odds1Num, odds2Num) : null;
  const quality = result ? qualityConfig[result.quality] : null;

  return (
    <main className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b sticky top-0 bg-background/95 backdrop-blur z-10">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-muted-foreground hover:text-foreground transition-colors">
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <h1 className="text-xl font-bold">Tools</h1>
          </div>
        </div>
      </header>

      <div className="container mx-auto px-4 py-6 space-y-6 max-w-md">
        {/* Hold Calculator */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <Calculator className="h-5 w-5 text-muted-foreground" />
              <h2 className="font-semibold">Hold % Calculator</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Enter both sides of a line to see the market vig
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Odds Inputs */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium mb-2 block">Your Odds</label>
                <Input
                  type="number"
                  placeholder="+150"
                  value={odds1}
                  onChange={(e) => setOdds1(e.target.value)}
                  className="font-mono text-center"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Opposing Odds</label>
                <Input
                  type="number"
                  placeholder="-180"
                  value={odds2}
                  onChange={(e) => setOdds2(e.target.value)}
                  className="font-mono text-center"
                />
              </div>
            </div>

            {/* Results */}
            {result && quality && (
              <div className="space-y-3 pt-2">
                {/* Hold % - Big Display */}
                <div className={cn("rounded-lg p-4 text-center", quality.bg)}>
                  <p className="text-sm text-muted-foreground mb-1">Market Hold</p>
                  <p className={cn("text-3xl font-bold", quality.color)}>
                    {(result.hold * 100).toFixed(2)}%
                  </p>
                  <div className="flex items-center justify-center gap-1 mt-2">
                    {result.quality === "excellent" || result.quality === "good" ? (
                      <CheckCircle className={cn("h-4 w-4", quality.color)} />
                    ) : (
                      <AlertCircle className={cn("h-4 w-4", quality.color)} />
                    )}
                    <span className={cn("text-sm font-medium", quality.color)}>
                      {quality.label}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{quality.desc}</p>
                </div>

                {/* Detailed Breakdown */}
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs text-muted-foreground">Fair Odds (You)</p>
                    <p className="font-mono font-semibold">
                      {result.fairOdds1 >= 0 ? "+" : ""}{result.fairOdds1}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {formatPercent(result.impliedProb1 / (result.impliedProb1 + result.impliedProb2))} true
                    </p>
                  </div>
                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs text-muted-foreground">Fair Odds (Opp)</p>
                    <p className="font-mono font-semibold">
                      {result.fairOdds2 >= 0 ? "+" : ""}{result.fairOdds2}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {formatPercent(result.impliedProb2 / (result.impliedProb1 + result.impliedProb2))} true
                    </p>
                  </div>
                </div>

                {/* EV Hint */}
                <div className="text-xs text-muted-foreground bg-muted/50 rounded p-2">
                  <p className="flex items-center gap-1">
                    <TrendingUp className="h-3 w-3" />
                    Lower hold = sharper line = better for finding +EV
                  </p>
                </div>
              </div>
            )}

            {/* Empty State */}
            {!result && (
              <div className="text-center py-6 text-muted-foreground">
                <Calculator className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p className="text-sm">Enter both odds to calculate</p>
                <p className="text-xs mt-1">Use American format (e.g., +150, -110)</p>
              </div>
            )}

            {/* Quick Clear */}
            {(odds1 || odds2) && (
              <Button
                variant="ghost"
                size="sm"
                className="w-full text-muted-foreground"
                onClick={() => { setOdds1(""); setOdds2(""); }}
              >
                Clear
              </Button>
            )}
          </CardContent>
        </Card>

        {/* Future Tools Placeholder */}
        <div className="text-center text-sm text-muted-foreground py-4">
          <p>More tools coming soon...</p>
        </div>
      </div>
    </main>
  );
}
