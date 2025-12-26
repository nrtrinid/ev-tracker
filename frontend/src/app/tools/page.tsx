"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn, americanToDecimal, formatPercent } from "@/lib/utils";
import { Calculator, TrendingUp, AlertCircle, CheckCircle, ArrowLeftRight, Gift } from "lucide-react";

// ============ HOLD CALCULATOR LOGIC ============

function calculateHold(odds1: number, odds2: number): {
  hold: number;
  impliedProb1: number;
  impliedProb2: number;
  fairOdds1: number;
  fairOdds2: number;
  fairProb1: number;
  bonusConversion1: number;
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
  
  // Bonus bet conversion: (decimal - 1) * fair probability
  // This is the expected value per dollar of bonus bet face value
  const bonusConversion1 = (decimal1 - 1) * fairProb1;
  
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
    fairProb1,
    bonusConversion1,
    quality,
  };
}

const qualityConfig = {
  excellent: { label: "Excellent", color: "text-[#4A7C59]", bg: "bg-[#4A7C59]/10", desc: "Sharp line, great for +EV" },
  good: { label: "Good", color: "text-[#4A7C59]", bg: "bg-[#4A7C59]/5", desc: "Solid market, reasonable vig" },
  fair: { label: "Fair", color: "text-[#C4A35A]", bg: "bg-[#C4A35A]/10", desc: "Average hold, acceptable" },
  poor: { label: "Poor", color: "text-[#B85C38]", bg: "bg-[#B85C38]/10", desc: "High vig, less favorable" },
};

// ============ ODDS CONVERTER LOGIC ============

function americanToDecimalConvert(american: number): number {
  if (american === 0) return 0;
  if (american >= 100) {
    return 1 + (american / 100);
  } else {
    return 1 + (100 / Math.abs(american));
  }
}

function decimalToAmerican(decimal: number): number {
  if (decimal === 0 || decimal === 1) return 0;
  if (decimal >= 2) {
    return Math.round((decimal - 1) * 100);
  } else {
    return Math.round(-100 / (decimal - 1));
  }
}

function decimalToImplied(decimal: number): number {
  if (decimal === 0) return 0;
  return (1 / decimal) * 100;
}

function impliedToDecimal(implied: number): number {
  if (implied === 0) return 0;
  return 100 / implied;
}

// ============ MAIN PAGE ============

export default function ToolsPage() {
  // Hold Calculator State
  const [odds1, setOdds1] = useState("");
  const [odds2, setOdds2] = useState("");
  
  const odds1Num = parseFloat(odds1) || 0;
  const odds2Num = parseFloat(odds2) || 0;
  
  const canCalculateHold = odds1Num !== 0 && odds2Num !== 0 && 
    (Math.abs(odds1Num) >= 100 || odds1Num === 0) && 
    (Math.abs(odds2Num) >= 100 || odds2Num === 0);
  
  const holdResult = canCalculateHold ? calculateHold(odds1Num, odds2Num) : null;
  const quality = holdResult ? qualityConfig[holdResult.quality] : null;

  // Odds Converter State - track which field was last edited
  const [american, setAmerican] = useState("");
  const [decimal, setDecimal] = useState("");
  const [implied, setImplied] = useState("");
  const [lastEdited, setLastEdited] = useState<"american" | "decimal" | "implied" | null>(null);

  // 3-way sync effect
  useEffect(() => {
    if (lastEdited === "american") {
      const americanNum = parseFloat(american);
      if (americanNum !== 0 && !isNaN(americanNum) && Math.abs(americanNum) >= 100) {
        const dec = americanToDecimalConvert(americanNum);
        setDecimal(dec.toFixed(3));
        setImplied(decimalToImplied(dec).toFixed(2));
      } else if (american === "" || american === "-" || american === "+") {
        setDecimal("");
        setImplied("");
      }
    } else if (lastEdited === "decimal") {
      const decimalNum = parseFloat(decimal);
      if (decimalNum > 1 && !isNaN(decimalNum)) {
        setAmerican(String(decimalToAmerican(decimalNum)));
        setImplied(decimalToImplied(decimalNum).toFixed(2));
      } else if (decimal === "") {
        setAmerican("");
        setImplied("");
      }
    } else if (lastEdited === "implied") {
      const impliedNum = parseFloat(implied);
      if (impliedNum > 0 && impliedNum < 100 && !isNaN(impliedNum)) {
        const dec = impliedToDecimal(impliedNum);
        setDecimal(dec.toFixed(3));
        setAmerican(String(decimalToAmerican(dec)));
      } else if (implied === "") {
        setAmerican("");
        setDecimal("");
      }
    }
  }, [american, decimal, implied, lastEdited]);

  const handleAmericanChange = (value: string) => {
    setAmerican(value);
    setLastEdited("american");
  };

  const handleDecimalChange = (value: string) => {
    setDecimal(value);
    setLastEdited("decimal");
  };

  const handleImpliedChange = (value: string) => {
    setImplied(value);
    setLastEdited("implied");
  };

  const clearConverter = () => {
    setAmerican("");
    setDecimal("");
    setImplied("");
    setLastEdited(null);
  };

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-6 space-y-6 max-w-md">
        
        {/* ============ HOLD CALCULATOR ============ */}
        <Card className="card-hover">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <Calculator className="h-5 w-5 text-muted-foreground" />
              <h2 className="font-semibold">Hold % Calculator</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Enter both sides of a line to see vig, fair value & bonus conversion
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
            {holdResult && quality && (
              <div className="space-y-3 pt-2">
                {/* Hold % - Big Display */}
                <div className={cn("rounded-lg p-4 text-center", quality.bg)}>
                  <p className="text-sm text-muted-foreground mb-1">Market Hold</p>
                  <p className={cn("text-3xl font-bold", quality.color)}>
                    {(holdResult.hold * 100).toFixed(2)}%
                  </p>
                  <div className="flex items-center justify-center gap-1 mt-2">
                    {holdResult.quality === "excellent" || holdResult.quality === "good" ? (
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

                {/* Fair Odds Breakdown */}
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs text-muted-foreground">Fair Odds (You)</p>
                    <p className="font-mono font-semibold text-lg">
                      {holdResult.fairOdds1 >= 0 ? "+" : ""}{holdResult.fairOdds1}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {formatPercent(holdResult.fairProb1)} true prob
                    </p>
                  </div>
                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs text-muted-foreground">Fair Odds (Opp)</p>
                    <p className="font-mono font-semibold text-lg">
                      {holdResult.fairOdds2 >= 0 ? "+" : ""}{holdResult.fairOdds2}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {formatPercent(1 - holdResult.fairProb1)} true prob
                    </p>
                  </div>
                </div>

                {/* Bonus Bet Conversion */}
                <div className={cn(
                  "rounded-lg p-3 border",
                  holdResult.bonusConversion1 >= 0.70 
                    ? "bg-[#4A7C59]/10 border-[#4A7C59]/30" 
                    : holdResult.bonusConversion1 < 0.60
                    ? "bg-[#B85C38]/10 border-[#B85C38]/30"
                    : "bg-muted border-border"
                )}>
                  <div className="flex items-center gap-2 mb-1">
                    <Gift className="h-4 w-4 text-muted-foreground" />
                    <p className="text-sm font-medium">Bonus Bet Conversion</p>
                  </div>
                  <p className={cn(
                    "text-2xl font-bold font-mono",
                    holdResult.bonusConversion1 >= 0.70 
                      ? "text-[#4A7C59]" 
                      : holdResult.bonusConversion1 < 0.60
                      ? "text-[#B85C38]"
                      : "text-foreground"
                  )}>
                    {(holdResult.bonusConversion1 * 100).toFixed(1)}%
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {holdResult.bonusConversion1 >= 0.70 
                      ? "✓ Good usage for bonus bets" 
                      : holdResult.bonusConversion1 < 0.60
                      ? "⚠ Poor usage — find longer odds"
                      : "Acceptable conversion rate"}
                  </p>
                </div>

                {/* EV Hint */}
                <div className="text-xs text-muted-foreground bg-muted/50 rounded p-2">
                  <p className="flex items-center gap-1">
                    <TrendingUp className="h-3 w-3" />
                    Aim for 70%+ conversion on bonus bets for optimal value
                  </p>
                </div>
              </div>
            )}

            {/* Empty State */}
            {!holdResult && (
              <div className="text-center py-6 text-muted-foreground">
                <Calculator className="h-8 w-8 mx-auto mb-2 opacity-40" />
                <p className="text-sm">Enter both odds to calculate</p>
                <p className="text-xs mt-1">Use American format (e.g., +150, -110)</p>
              </div>
            )}

            {/* Quick Clear */}
            {(odds1 || odds2) && (
              <Button
                variant="ghost"
                size="sm"
                className="w-full text-muted-foreground hover:text-foreground"
                onClick={() => { setOdds1(""); setOdds2(""); }}
              >
                Clear
              </Button>
            )}
          </CardContent>
        </Card>

        {/* ============ ODDS CONVERTER ============ */}
        <Card className="card-hover">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <ArrowLeftRight className="h-5 w-5 text-muted-foreground" />
              <h2 className="font-semibold">Odds Converter</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Convert between odds formats instantly
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium mb-2 block">American</label>
                <Input
                  type="text"
                  inputMode="numeric"
                  placeholder="+150 or -110"
                  value={american}
                  onChange={(e) => handleAmericanChange(e.target.value)}
                  className="font-mono text-center text-lg"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Decimal</label>
                <Input
                  type="text"
                  inputMode="decimal"
                  placeholder="2.50"
                  value={decimal}
                  onChange={(e) => handleDecimalChange(e.target.value)}
                  className="font-mono text-center text-lg"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Implied Probability (%)</label>
                <Input
                  type="text"
                  inputMode="decimal"
                  placeholder="40.0"
                  value={implied}
                  onChange={(e) => handleImpliedChange(e.target.value)}
                  className="font-mono text-center text-lg"
                />
              </div>
            </div>

            {/* Clear Button */}
            {(american || decimal || implied) && (
              <Button
                variant="ghost"
                size="sm"
                className="w-full text-muted-foreground hover:text-foreground"
                onClick={clearConverter}
              >
                Clear
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
