import { Gift, ShieldCheck, TrendingUp, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ScannerLens } from "../scanner-ui-model";

interface ScannerLensSelectorProps {
  activeLens: ScannerLens;
  onLensChange: (lens: ScannerLens) => void;
  tutorialMode?: boolean;
}

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
    // #4A7C59 (deep green)
    activeBg: "bg-[#F3F7F5]", // very light green tint
    activeBorder: "border-[#B7D1C2]",
    activeText: "text-[#2E5D39]",
    iconText: "text-[#2E5D39]",
  },
  {
    id: "profit_boost",
    label: "Profit Boost",
    description: "Use when a book adds a boost",
    icon: Zap,
    // #C4A35A (gold/yellow)
    activeBg: "bg-[#FCF7EC]", // very light gold tint
    activeBorder: "border-[#E9D7B9]",
    activeText: "text-[#8B7A3E]",
    iconText: "text-[#8B7A3E]",
  },
  {
    id: "bonus_bet",
    label: "Bonus Bet",
    description: "Turn bonus bets into cash",
    icon: Gift,
    // #7A9E7E (muted teal/green)
    activeBg: "bg-[#F4F7F5]", // very light teal tint
    activeBorder: "border-[#B7CFC2]",
    activeText: "text-[#3B6C4C]",
    iconText: "text-[#3B6C4C]",
  },
  {
    id: "qualifier",
    label: "Qualifier",
    description: "Safer promo setup",
    icon: ShieldCheck,
    // #B85C38 (rust)
    activeBg: "bg-[#FDF6F3]", // very light rust tint
    activeBorder: "border-[#E9C7B9]",
    activeText: "text-[#8B3D20]",
    iconText: "text-[#8B3D20]",
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
        "rounded-lg border px-3 py-2.5 text-left transition-colors",
        isActive
          ? `${lens.activeBg} ${lens.activeBorder} ${lens.activeText}`
          : tutorialMode && lens.id === "standard"
            ? "border-primary/25 bg-background text-foreground hover:bg-muted"
            : "border-border bg-background text-foreground hover:bg-muted"
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
          {lens.id === "standard" ? "Core View" : "Specialty"}
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
            "inline-flex h-6 w-6 items-center justify-center rounded-md bg-background/70",
            isActive ? lens.iconText : "text-muted-foreground"
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="text-xs font-semibold leading-tight md:text-sm">{lens.label}</span>
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
      <p className="pl-0.5 text-xs font-medium text-muted-foreground">View</p>

      {tutorialMode && (
        <div className="rounded-lg border border-primary/20 bg-primary/8 px-3 py-2 text-xs text-muted-foreground">
          <p className="font-semibold text-primary">Tutorial tip</p>
          <p className="mt-1">
            Start in Standard EV while you learn. The other views are mainly for promos, boosts, and qualifier hunting later on.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {LENS_OPTIONS.map((lens) => (
          <LensButton
            key={lens.id}
            lens={lens}
            isActive={activeLens === lens.id}
            tutorialMode={tutorialMode}
            onClick={() => onLensChange(lens.id)}
          />
        ))}
      </div>

      {tutorialMode && (
        <p className="px-0.5 text-[11px] text-muted-foreground">
          {activeLens === "standard"
            ? "Standard EV is active. Stay here for the tutorial and focus on one clean practice play."
            : "You switched into a specialty view. For the simplest tutorial flow, switch back to Standard EV."}
        </p>
      )}
      <div className="sr-only">
        {activeLens}
      </div>
    </div>
  );
}
