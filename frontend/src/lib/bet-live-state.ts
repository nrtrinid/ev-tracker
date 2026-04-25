import type { BetLiveSnapshot, LiveGameStatus, LivePlayerStatSnapshot } from "@/lib/types";

export type BetLiveChipTone = "live" | "under" | "hit" | "miss" | "scheduled" | "final" | "stale" | "warning";
export type BetLiveChipKind = "prop" | "game" | "exception" | "scheduled";
export type BetLiveChipOutcome = "hit" | "miss" | null;

export interface BetLiveChipState {
  label: string;
  title: string;
  tone: BetLiveChipTone;
  progressRatio: number | null;
  kind: BetLiveChipKind;
  showInCollapsed: boolean;
  outcome: BetLiveChipOutcome;
}

const STAT_LABELS: Record<string, string> = {
  PTS: "PTS",
  REB: "REB",
  AST: "AST",
  PTS_REB_AST: "PRA",
  "3PM": "3PM",
  P_SO: "Ks",
  B_TB: "TB",
  B_H: "H",
  B_H_R_RBI: "H+R+RBI",
  B_HR: "HR",
  B_SO: "Ks",
};

function formatCompactNumber(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(1).replace(/\.0$/, "");
}

export function formatBetLiveProgressLabel(stat: LivePlayerStatSnapshot): string {
  const value = formatCompactNumber(stat.value);
  const line = formatCompactNumber(stat.line_value);
  const label = STAT_LABELS[stat.stat_key] || stat.stat_label || stat.stat_key;
  return line ? `${value} / ${line} ${label}` : `${value} ${label}`;
}

function formatStartTime(value: string | null): string {
  if (!value) return "scheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "scheduled";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function toneForStatus(status: LiveGameStatus, stale: boolean): BetLiveChipTone {
  if (stale) return "stale";
  if (status === "live") return "live";
  if (status === "final") return "final";
  if (status === "postponed" || status === "delayed" || status === "cancelled") return "warning";
  return "scheduled";
}

function toneForPlayerStat(stat: LivePlayerStatSnapshot, status: LiveGameStatus, stale: boolean): BetLiveChipTone {
  const tone = toneForStatus(status, stale);
  if (tone === "live" && stat.selection_side?.toLowerCase() === "under") return "under";
  return tone;
}

function finalPlayerStatOutcome(stat: LivePlayerStatSnapshot, status: LiveGameStatus): BetLiveChipOutcome {
  if (status !== "final" || typeof stat.line_value !== "number") return null;

  const selectionSide = stat.selection_side?.toLowerCase();
  if (selectionSide === "over") return stat.value >= stat.line_value ? "hit" : "miss";
  if (selectionSide === "under") return stat.value <= stat.line_value ? "hit" : "miss";
  return null;
}

function labelForOutcome(outcome: BetLiveChipOutcome): string | null {
  if (outcome === "hit") return "Hit";
  if (outcome === "miss") return "Miss";
  return null;
}

function formatMatchup(snapshot: BetLiveSnapshot): string | null {
  const event = snapshot.event;
  if (!event) return null;
  const away = event.away.short_name || event.away.name;
  const home = event.home.short_name || event.home.name;
  return `${away} @ ${home}`;
}

function formatScore(snapshot: BetLiveSnapshot): string | null {
  const event = snapshot.event;
  if (!event) return null;
  const away = event.away.short_name || event.away.name;
  const home = event.home.short_name || event.home.name;
  const awayScore = formatCompactNumber(event.away.score);
  const homeScore = formatCompactNumber(event.home.score);
  return awayScore && homeScore ? `${away} ${awayScore}-${homeScore} ${home}` : null;
}

function formatExceptionLabel(snapshot: BetLiveSnapshot): string | null {
  const event = snapshot.event;
  if (!event) return null;
  const score = formatScore(snapshot);
  const matchup = formatMatchup(snapshot);

  if (event.status === "final") return score ? `Final • ${score}` : matchup ? `Final • ${matchup}` : "Final";
  if (event.status === "delayed") return event.status_detail || "Delayed";
  if (event.status === "postponed") return "Postponed";
  if (event.status === "cancelled") return "Cancelled";
  if (event.status === "unknown") return event.status_detail || "Status pending";
  return null;
}

function formatGameLabel(snapshot: BetLiveSnapshot): string | null {
  const event = snapshot.event;
  if (!event) return null;
  const score = formatScore(snapshot);
  const matchup = formatMatchup(snapshot);
  const display = score || matchup;
  if (!display) return null;

  if (event.status === "live") {
    const clock = [event.period_label, event.clock].filter(Boolean).join(" ");
    return clock ? `${clock} • ${display}` : `Live • ${display}`;
  }
  if (event.status === "scheduled") return `Sched ${formatStartTime(event.start_time)}`;
  return formatExceptionLabel(snapshot) || event.status_detail || "Status pending";
}

export function buildBetLiveChipState(snapshot: BetLiveSnapshot | null | undefined): BetLiveChipState | null {
  if (!snapshot || snapshot.status === "unavailable") return null;

  if (snapshot.player_stat && snapshot.status !== "scheduled") {
    const stat = snapshot.player_stat;
    const progressLabel = formatBetLiveProgressLabel(stat);
    const outcome = finalPlayerStatOutcome(stat, snapshot.status);
    const outcomeLabel = labelForOutcome(outcome);
    const label = outcomeLabel ? `${outcomeLabel} • ${progressLabel}` : progressLabel;
    return {
      label,
      title: `${stat.participant_name}: ${label}`,
      tone: outcome ?? toneForPlayerStat(stat, snapshot.status, snapshot.provider.stale),
      progressRatio: stat.progress_ratio,
      kind: "prop",
      showInCollapsed: true,
      outcome,
    };
  }

  const gameLabel = formatGameLabel(snapshot);
  if (!gameLabel) return null;
  const kind: BetLiveChipKind =
    snapshot.status === "scheduled"
      ? "scheduled"
      : snapshot.status === "live"
        ? "game"
        : "exception";
  const showInCollapsed = kind !== "scheduled";

  return {
    label: gameLabel,
    title: snapshot.event?.status_detail || gameLabel,
    tone: toneForStatus(snapshot.status, snapshot.provider.stale),
    progressRatio: null,
    kind,
    showInCollapsed,
    outcome: null,
  };
}
