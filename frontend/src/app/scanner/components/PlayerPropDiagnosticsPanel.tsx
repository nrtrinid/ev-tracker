import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PlayerPropScanDiagnostics } from "@/lib/types";

function selectionReasonLabel(reason: string): string {
  switch (reason) {
    case "national_tv":
      return "National TV";
    case "nba_tv":
      return "NBA TV";
    case "scoreboard_fallback":
      return "Scoreboard fallback";
    default:
      return reason.replaceAll("_", " ");
  }
}

function summarizeBroadcasts(broadcasts: string[]): string {
  const cleaned = broadcasts
    .map((entry) => entry.trim())
    .filter((entry) => entry && entry !== "home" && entry !== "away" && entry !== "national");
  return cleaned.slice(0, 3).join(" | ");
}

interface PlayerPropDiagnosticsPanelProps {
  diagnostics: PlayerPropScanDiagnostics;
}

export function PlayerPropDiagnosticsPanel({ diagnostics }: PlayerPropDiagnosticsPanelProps) {
  const usedOddsFallback =
    diagnostics.scan_scope === "odds_fallback" && (diagnostics.fallback_event_count ?? 0) > 0;
  const curatedJoinMissed =
    diagnostics.curated_games.length > 0 &&
    diagnostics.matched_event_count === 0 &&
    diagnostics.odds_event_count > 0;
  const scanSummary = usedOddsFallback
    ? `${diagnostics.curated_games.length} shortlisted -> ${diagnostics.matched_event_count} curated matches -> fallback ${diagnostics.fallback_event_count ?? 0} events -> ${diagnostics.events_fetched} prop requests -> ${diagnostics.sides_count} props`
    : `${diagnostics.curated_games.length} shortlisted -> ${diagnostics.matched_event_count} curated matches -> ${diagnostics.events_fetched} prop requests -> ${diagnostics.sides_count} props`;

  return (
    <Card className="border-[#4A7C59]/20 bg-[#4A7C59]/[0.04]">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Scan diagnostics</CardTitle>
        <CardDescription>
          Shortlist, match status, and result counts for the manual prop sniper.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-md border border-[#3B6C8E]/20 bg-[#3B6C8E]/10 px-3 py-2 text-sm font-medium text-[#2D5673]">
          {scanSummary}
        </div>

        {usedOddsFallback && diagnostics.fallback_reason && (
          <div className="rounded-md border border-[#C4A35A]/35 bg-[#C4A35A]/10 px-3 py-2 text-xs text-[#5C4D2E]">
            {diagnostics.fallback_reason}
          </div>
        )}

        {curatedJoinMissed && !usedOddsFallback && (
          <div className="rounded-md border border-[#C4A35A]/35 bg-[#C4A35A]/10 px-3 py-2 text-xs text-[#5C4D2E]">
            The sportsbook event list loaded, but none of the curated games matched it, so no
            per-game prop requests were sent.
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <div className="rounded-md border border-border/60 bg-background/70 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Scoreboard</div>
            <div className="mt-1 text-sm font-semibold">{diagnostics.scoreboard_event_count}</div>
          </div>
          <div className="rounded-md border border-border/60 bg-background/70 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Shortlisted</div>
            <div className="mt-1 text-sm font-semibold">{diagnostics.curated_games.length}</div>
          </div>
          <div className="rounded-md border border-border/60 bg-background/70 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Matched</div>
            <div className="mt-1 text-sm font-semibold">{diagnostics.matched_event_count}</div>
          </div>
          <div className="rounded-md border border-border/60 bg-background/70 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Props</div>
            <div className="mt-1 text-sm font-semibold">{diagnostics.sides_count}</div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Quality gate: {diagnostics.quality_gate_min_reference_bookmakers}+ refs
          </span>
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Raw props: {diagnostics.candidate_sides_count}
          </span>
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Gate filtered: {diagnostics.quality_gate_filtered_count}
          </span>
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Odds events: {diagnostics.odds_event_count}
          </span>
          {usedOddsFallback && (
            <span className="rounded-full border border-border/70 px-2 py-0.5">
              Fallback events: {diagnostics.fallback_event_count ?? 0}
            </span>
          )}
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Prop requests: {diagnostics.events_fetched}
          </span>
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Result games: {diagnostics.events_with_results}
          </span>
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Pregame skipped: {diagnostics.events_skipped_pregame}
          </span>
          <span className="rounded-full border border-border/70 px-2 py-0.5">
            Markets: {diagnostics.markets_requested.join(", ")}
          </span>
        </div>

        <div className="space-y-2">
          {diagnostics.curated_games.map((game) => (
            <div
              key={`${game.event_id ?? "scoreboard"}:${game.away_team}:${game.home_team}`}
              className="rounded-md border border-border/60 bg-background/70 px-3 py-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium">
                  {game.away_team} @ {game.home_team}
                </p>
                <span className="rounded-full border border-[#C4A35A]/35 bg-[#C4A35A]/10 px-2 py-0.5 text-[10px] text-[#8B7355]">
                  {selectionReasonLabel(game.selection_reason)}
                </span>
                <span
                  className={
                    game.matched
                      ? "rounded-full border border-[#4A7C59]/30 bg-[#4A7C59]/10 px-2 py-0.5 text-[10px] text-[#2E5D39]"
                      : "rounded-full border border-[#B85C38]/30 bg-[#B85C38]/10 px-2 py-0.5 text-[10px] text-[#8B3D20]"
                  }
                >
                  {game.matched ? "Matched" : "Unmatched"}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {summarizeBroadcasts(game.broadcasts) || "No broadcast details"}
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
