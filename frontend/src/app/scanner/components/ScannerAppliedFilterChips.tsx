import { X } from "lucide-react";

import { Button } from "@/components/ui/button";

interface ScannerAppliedFilterChipsProps {
  chips: string[];
  onResetFilters: () => void;
}

export function ScannerAppliedFilterChips({
  chips,
  onResetFilters,
}: ScannerAppliedFilterChipsProps) {
  if (!chips.length) return null;

  const visible = chips.slice(0, 3);
  const hiddenCount = Math.max(chips.length - visible.length, 0);

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-2.5 py-1.5">
      <div className="flex flex-1 flex-wrap items-center gap-1.5">
        {visible.map((chip) => (
          <span
            key={chip}
            className="rounded-full border border-color-profit/25 bg-color-profit-subtle px-2 py-0.5 text-[11px] text-color-profit-fg"
          >
            {chip}
          </span>
        ))}
        {hiddenCount > 0 && (
          <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground">
            +{hiddenCount} more
          </span>
        )}
      </div>

      <Button type="button" variant="ghost" className="h-7 px-2 text-xs" onClick={onResetFilters}>
        <X className="mr-1 h-3.5 w-3.5" />
        Reset
      </Button>
    </div>
  );
}
