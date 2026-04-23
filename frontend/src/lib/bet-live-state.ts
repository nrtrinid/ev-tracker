import type { BetLiveSnapshot, LiveGameStatus } from "@/lib/types";

export type BetLiveChipTone = "live" | "scheduled" | "final" | "stale" | "warning";

export interface BetLiveChipState {
  label: string;
  title: string;
  tone: BetLiveChipTone;
  progressRatio: number | null;
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

function formatGameLabel(snapshot: BetLiveSnapshot): string | null {
  const event = snapshot.event;
  if (!event) return null;
  const away = event.away.short_name || event.away.name;
  const home = event.home.short_name || event.home.name;
  const awayScore = formatCompactNumber(event.away.score);
  const homeScore = formatCompactNumber(event.home.score);
  const score = awayScore && homeScore ? `${away} ${awayScore}-${homeScore} ${home}` : `${away} @ ${home}`;

  if (event.status === "live") {
    const clock = [event.period_label, event.clock].filter(Boolean).join(" ");
    return clock ? `${clock} • ${score}` : `Live • ${score}`;
  }
  if (event.status === "final") return `Final • ${score}`;
  if (event.status === "postponed") return "Postponed";
  if (event.status === "delayed") return "Delayed";
  if (event.status === "cancelled") return "Cancelled";
  if (event.status === "scheduled") return `Sched ${formatStartTime(event.start_time)}`;
  return event.status_detail || "Status pending";
}

export function buildBetLiveChipState(snapshot: BetLiveSnapshot | null | undefined): BetLiveChipState | null {
  if (!snapshot || snapshot.status === "unavailable") return null;

  if (snapshot.player_stat) {
    const stat = snapshot.player_stat;
    const value = formatCompactNumber(stat.value);
    const line = formatCompactNumber(stat.line_value);
    const label = STAT_LABELS[stat.stat_key] || stat.stat_label || stat.stat_key;
    const progressLabel = line ? `${value} / ${line} ${label}` : `${value} ${label}`;
    return {
      label: snapshot.provider.stale ? `Stale • ${progressLabel}` : progressLabel,
      title: `${stat.participant_name}: ${progressLabel}`,
      tone: toneForStatus(snapshot.status, snapshot.provider.stale),
      progressRatio: stat.progress_ratio,
    };
  }

  const gameLabel = formatGameLabel(snapshot);
  if (!gameLabel) return null;
  return {
    label: snapshot.provider.stale ? `Stale • ${gameLabel}` : gameLabel,
    title: snapshot.event?.status_detail || gameLabel,
    tone: toneForStatus(snapshot.status, snapshot.provider.stale),
    progressRatio: null,
  };
}
