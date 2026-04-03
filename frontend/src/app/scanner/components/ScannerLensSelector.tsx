import { Gift, ShieldCheck, TrendingUp, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ScannerLens } from "../scanner-ui-model";

interface ScannerLensSelectorProps {
  activeLens: ScannerLens;
  onLensChange: (lens: ScannerLens) => void;
  tutorialMode?: boolean;
}

// Active state uses token-based classes so they work correctly in both
// light and dark mode without raw hex overrides.
const LENS_OPTIONS: Array<{
  id: ScannerLens;
  label: string;
  description: string;
  icon: typeof TrendingUp;
  activeBg: string;
  activeBorder: string;
  activeText: string;
  iconText: string;
}> = [
  {
    id: "standard",
    label: "Standard EV",
    description: "Best starting place",
    icon: TrendingUp,
    activeBg: "bg-profit/8",
    activeBorder: "border-profit/30",
    activeText: "text-profit",
    iconText: "text-profit",
  },
  {
    id: "profit_boost",
    label: "Profit Boost",
    description: "Use when a book adds a boost",
    icon: Zap,
    activeBg: "bg-primary/10",
    activeBorder: "border-primary/35",
    activeText: "text-primary",
    iconText: "text-primary",
  },
  {
    id: "bonus_bet",
    label: "Bonus Bet",
    description: "Turn bonus bets into cash",
    icon: Gift,
    activeBg: "bg-profit/8",
    activeBorder: "border-profit/25",
    activeText: "text-profit",
    iconText: "text-profit",
  },
  {
    id: "qualifier",
    label: "Qualifier",
    description: "Safer promo setup",
    icon: ShieldCheck,
    activeBg: "bg-loss/8",
    activeBorder: "border-loss/30",
    activeText: "text-loss",
    iconText: "text-loss",
  },
];

function LensButton({
  lens,
  isActive,
  tutorialMode,
  onClick,
}: {
  lens: (typeof LENS_OPTIONS)[number];
  isActive: boolean;
  tutorialMode: boolean;
  onClick: () => void;
}) {
  const Icon = lens.icon;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      className={cn(
        "rounded border px-3 py-2.5 text-left transition-colors",
        isActive
          ? `${lens.activeBg} ${lens.activeBorder} ${lens.activeText}`
          : tutorialMode && lens.id === "standard"
            ? "border-primary/25 bg-background text-foreground hover:bg-muted"
            : "border-border/70 bg-card text-foreground hover:bg-muted/60",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {lens.id === "standard" ? "Core" : "Specialty"}
        </span>
        {isActive && (
          <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Active
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex h-6 w-6 items-center justify-center rounded bg-background/60",
            isActive ? lens.iconText : "text-muted-foreground",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="text-xs font-bold leading-tight">{lens.label}</span>
      </div>
      <p className="mt-1 text-[11px] leading-tight text-muted-foreground">{lens.description}</p>
    </button>
  );
}

export function ScannerLensSelector({
  activeLens,
  onLensChange,
  tutorialMode = false,
}: ScannerLensSelectorProps) {
  return (
    <div className="space-y-2">
      <p className="pl-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        View
      </p>

      {tutorialMode && (
        <div className="rounded border border-primary/20 bg-primary/8 px-3 py-2 text-xs text-muted-foreground">
          <p className="font-semibold text-primary">Tutorial tip</p>
          <p className="mt-1">
            Start in Standard EV while you learn. The other views are mainly for promos, boosts, and qualifier hunting later on.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 animate-slide-up">
        {LENS_OPTIONS.map((lens, i) => (
          <div
            key={lens.id}
            className="animate-slide-up"
            style={{ animationDelay: `${i * 40}ms`, animationFillMode: "both" }}
          >
            <LensButton
              lens={lens}
              isActive={activeLens === lens.id}
              tutorialMode={tutorialMode}
              onClick={() => onLensChange(lens.id)}
            />
          </div>
        ))}
      </div>

      {tutorialMode && (
        <p className="px-0.5 text-[11px] text-muted-foreground">
          {activeLens === "standard"
            ? "Standard EV is active. Stay here for the tutorial and focus on one clean practice play."
            : "You switched into a specialty view. For the simplest tutorial flow, switch back to Standard EV."}
        </p>
      )}
      <div className="sr-only">{activeLens}</div>
    </div>
  );
}
