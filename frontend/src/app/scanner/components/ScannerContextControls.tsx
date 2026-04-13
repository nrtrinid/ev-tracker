import { cn } from "@/lib/utils";
import { shouldShowProfitBoostContextControls } from "../scanner-ui-model";

interface ScannerContextControlsProps {
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  boostPercent: number;
  customBoostInput: string;
  boostPresets: number[];
  onPresetSelect: (value: number) => void;
  onCustomBoostInputChange: (value: string) => void;
}

export function ScannerContextControls({
  activeLens,
  boostPercent,
  customBoostInput,
  boostPresets,
  onPresetSelect,
  onCustomBoostInputChange,
}: ScannerContextControlsProps) {
  if (!shouldShowProfitBoostContextControls(activeLens)) {
    return null;
  }

  return (
    <div className="space-y-1.5 rounded-xl border bg-card p-3">
      <p className="text-xs font-medium text-muted-foreground">Profit Boost</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {boostPresets.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => onPresetSelect(preset)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              boostPercent === preset && customBoostInput === ""
                ? "border border-primary/40 bg-primary/15 text-primary"
                : "bg-muted text-muted-foreground hover:bg-secondary"
            )}
          >
            {preset}%
          </button>
        ))}

        <div className="flex items-center gap-1">
          <input
            type="number"
            min={1}
            max={200}
            placeholder="Custom"
            value={customBoostInput}
            onChange={(e) => onCustomBoostInputChange(e.target.value)}
            className={cn(
              "w-16 rounded-md border bg-muted px-2 py-1 text-xs font-medium text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50",
              customBoostInput !== "" ? "border-primary/40" : "border-transparent"
            )}
          />
          {customBoostInput !== "" && <span className="text-xs text-muted-foreground">%</span>}
        </div>
      </div>
    </div>
  );
}
