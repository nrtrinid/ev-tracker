"use client";

import type { BetLiveSnapshot } from "@/lib/types";
import type { BetLiveChipState } from "@/lib/bet-live-state";
import { buildBetLiveChipState } from "@/lib/bet-live-state";
import { cn } from "@/lib/utils";

const TONE_CLASSES = {
  live: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  scheduled: "border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  final: "border-muted-foreground/20 bg-muted text-muted-foreground",
  stale: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  warning: "border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300",
} as const;

interface BetLiveChipProps {
  snapshot: BetLiveSnapshot | null | undefined;
  state?: BetLiveChipState | null;
}

export function BetLiveChip({ snapshot, state: providedState }: BetLiveChipProps) {
  const state = providedState ?? buildBetLiveChipState(snapshot);
  if (!state || !state.showInCollapsed) return null;

  const width =
    typeof state.progressRatio === "number"
      ? `${Math.max(0, Math.min(1, state.progressRatio)) * 100}%`
      : "0%";

  return (
    <span
      className={cn(
        "relative inline-flex h-5 max-w-[9.5rem] items-center overflow-hidden rounded-full border px-2 text-[10px] font-semibold leading-none md:max-w-[11rem]",
        TONE_CLASSES[state.tone],
      )}
      title={state.title}
      aria-label={`Live status: ${state.title}`}
    >
      {state.progressRatio !== null && (
        <span
          className="absolute inset-y-0 left-0 bg-current opacity-10"
          style={{ width }}
          aria-hidden="true"
        />
      )}
      <span className="relative truncate">{state.label}</span>
    </span>
  );
}
