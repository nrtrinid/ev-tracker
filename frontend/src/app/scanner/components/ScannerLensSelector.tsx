import { Gift, ShieldCheck, TrendingUp, Zap } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ScannerLens } from "../scanner-ui-model";

interface ScannerLensSelectorProps {
  activeLens: ScannerLens;
  onLensChange: (lens: ScannerLens) => void;
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
    description: "Best +EV lines",
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
    description: "Boosted EV lines",
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
    description: "Best bonus conversion",
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
    description: "Low-loss promo legs",
    icon: ShieldCheck,
    // #B85C38 (rust)
    activeBg: "bg-[#FDF6F3]", // very light rust tint
    activeBorder: "border-[#E9C7B9]",
    activeText: "text-[#8B3D20]",
    iconText: "text-[#8B3D20]",
  },
];

export function ScannerLensSelector({ activeLens, onLensChange }: ScannerLensSelectorProps) {
  return (
    <div className="space-y-1.5">
      <p className="pl-0.5 text-xs font-medium text-muted-foreground">Choose your lens</p>
      <div className="grid grid-cols-2 gap-2">
        {LENS_OPTIONS.map((lens) => {
          const Icon = lens.icon;
          const isActive = activeLens === lens.id;
          return (
            <button
              key={lens.id}
              type="button"
              onClick={() => onLensChange(lens.id)}
              aria-pressed={isActive}
              className={cn(
                "rounded-lg border px-3 py-2.5 text-left transition-colors",
                isActive
                  ? `${lens.activeBg} ${lens.activeBorder} ${lens.activeText}`
                  : "border-border bg-background text-foreground hover:bg-muted"
              )}
            >
              <div className="flex items-center gap-2">
                <span className={cn("inline-flex h-6 w-6 items-center justify-center rounded-md bg-background/70", isActive ? lens.iconText : "text-muted-foreground") }>
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <span className="text-xs font-semibold leading-tight md:text-sm">{lens.label}</span>
              </div>
              <p className="mt-1 text-[11px] leading-tight text-muted-foreground">{lens.description}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
