"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useAltPitcherKLookup } from "@/lib/hooks";
import type { AltPitcherKLookupResponse, AltPitcherKLookupRequest } from "@/lib/types";

function formatProbability(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  return `${(value * 100).toFixed(1)}%`;
}

function formatOdds(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Unknown";
  return value > 0 ? `+${value}` : String(value);
}

function formatCommenceTime(value?: string | null): string {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function formatResolutionMode(value?: AltPitcherKLookupResponse["resolution_mode"]): string {
  switch (value) {
    case "exact_pair":
      return "Exact Pair";
    case "modeled_nearby_pairs":
      return "Modeled Nearby Pairs";
    case "observed_only_one_sided":
      return "Observed Only";
    default:
      return "Unknown";
  }
}

function sameLookup(left: AltPitcherKLookupRequest | null, right: AltPitcherKLookupRequest): boolean {
  if (!left) return false;
  return (
    left.player_name === right.player_name
    && (left.team ?? "") === (right.team ?? "")
    && (left.opponent ?? "") === (right.opponent ?? "")
    && left.line_value === right.line_value
    && (left.game_date ?? "") === (right.game_date ?? "")
  );
}

function LookupStatus({ result }: { result: AltPitcherKLookupResponse }) {
  if (result.status === "ambiguous_event") {
    return (
      <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        {result.warning ?? "Multiple games matched this exact lookup. Pick the correct game context before trusting the line."}
      </div>
    );
  }
  if (result.status === "not_found") {
    return (
      <div className="rounded-lg border border-border bg-muted/60 px-3 py-2 text-sm text-muted-foreground">
        {result.warning ?? "No exact MLB alternate pitcher strikeout line matched this request."}
      </div>
    );
  }
  if (result.resolution_mode === "observed_only_one_sided") {
    return (
      <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        {result.warning ?? "Only one-sided ladder evidence was available, so no fair price was computed."}
      </div>
    );
  }
  if (result.resolution_mode === "modeled_nearby_pairs" && result.status === "insufficient_depth") {
    return (
      <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        {result.warning ?? "Fair odds were modeled from nearby paired lines, but reference depth is still thin."}
      </div>
    );
  }
  if (result.resolution_mode === "modeled_nearby_pairs") {
    return (
      <div className="rounded-lg border border-sky-300/60 bg-sky-50 px-3 py-2 text-sm text-sky-900">
        {result.warning ?? "Fair odds were modeled from nearby paired alt lines because the exact target pair was unavailable."}
      </div>
    );
  }
  if (result.status === "insufficient_depth") {
    return (
      <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        Exact line found, but fewer than 2 paired books were available. Shown for admin review only.
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-emerald-300/60 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
      Exact target line matched with sufficient paired-book depth.
    </div>
  );
}

export function AltPitcherKLookupPage() {
  const [playerName, setPlayerName] = useState("");
  const [team, setTeam] = useState("");
  const [opponent, setOpponent] = useState("");
  const [lineValue, setLineValue] = useState("");
  const [gameDate, setGameDate] = useState("");
  const [submitted, setSubmitted] = useState<AltPitcherKLookupRequest | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const query = useAltPitcherKLookup(submitted, !!submitted);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextLineValue = Number.parseFloat(lineValue);
    if (!playerName.trim() || Number.isNaN(nextLineValue)) {
      setValidationError("Player and exact alt K line are required.");
      return;
    }

    const nextLookup = {
      player_name: playerName.trim(),
      team: team.trim() || undefined,
      opponent: opponent.trim() || undefined,
      line_value: nextLineValue,
      game_date: gameDate.trim() || undefined,
    };
    setValidationError(null);

    if (sameLookup(submitted, nextLookup)) {
      void query.refetch();
      return;
    }

    setSubmitted(nextLookup);
  }

  const result = query.data;
  const errorMessage = validationError ?? (query.error instanceof Error ? query.error.message : null);
  const consensusBookLabel = result?.resolution_mode === "modeled_nearby_pairs" ? "Reference Books" : "Paired Books";
  const consensusBookCount = result?.resolution_mode === "modeled_nearby_pairs"
    ? (result?.consensus?.reference_books_count ?? 0)
    : (result?.consensus?.paired_books_count ?? 0);
  const consensusBooks = result?.resolution_mode === "modeled_nearby_pairs"
    ? (result?.consensus?.reference_books ?? [])
    : (result?.consensus?.paired_books ?? []);
  const offerSectionTitle = result?.resolution_mode === "exact_pair" ? "Exact-Line Offers" : "Target-Line Offers";

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-4xl px-4 py-6 space-y-4 pb-20">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Alt Pitcher K Lookup</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Admin-only MLB alternate pitcher strikeout lookup with exact, modeled, and observed-only resolution modes.
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link href="/admin/ops">Back to Ops</Link>
          </Button>
        </div>

        <Card>
          <CardHeader className="pb-2">
            <h2 className="text-base font-semibold">Lookup</h2>
            <p className="text-sm text-muted-foreground">
              Prefers exact paired target-line pricing, falls back to nearby paired ladder modeling when available, and otherwise shows observed one-sided ladder evidence without fair odds.
            </p>
          </CardHeader>
          <CardContent>
            <form className="grid gap-3 md:grid-cols-2" onSubmit={handleSubmit}>
              <label className="space-y-1 text-sm">
                <span className="font-medium">Player</span>
                <input
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={playerName}
                  onChange={(event) => setPlayerName(event.target.value)}
                  placeholder="Gerrit Cole"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium">Pitcher Team (optional)</span>
                <input
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={team}
                  onChange={(event) => setTeam(event.target.value)}
                  placeholder="New York Yankees"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium">Opponent (optional)</span>
                <input
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={opponent}
                  onChange={(event) => setOpponent(event.target.value)}
                  placeholder="Boston Red Sox"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium">Exact Alt K Line</span>
                <input
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={lineValue}
                  onChange={(event) => setLineValue(event.target.value)}
                  placeholder="6.5"
                  inputMode="decimal"
                />
              </label>
              <label className="space-y-1 text-sm md:col-span-2">
                <span className="font-medium">Game Date (optional)</span>
                <input
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  type="date"
                  value={gameDate}
                  onChange={(event) => setGameDate(event.target.value)}
                />
              </label>
              <p className="text-xs text-muted-foreground md:col-span-2">
                If player name + exact line is too broad, add team, opponent, or game date to avoid hitting the live-event budget guardrail.
              </p>
              <div className="md:col-span-2 flex items-center gap-3">
                <Button type="submit" disabled={query.isFetching}>
                  {query.isFetching ? "Looking up..." : "Run Lookup"}
                </Button>
                {submitted && (
                  <span className="text-xs text-muted-foreground">
                    Cache: {result?.cache.hit ? "hit" : "live"} • TTL {result?.cache.ttl_seconds ?? 60}s
                  </span>
                )}
              </div>
            </form>
            {errorMessage && (
              <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {errorMessage}
              </div>
            )}
          </CardContent>
        </Card>

        {result && (
          <Card>
            <CardHeader className="pb-2">
              <div className="flex flex-col gap-1">
                <h2 className="text-base font-semibold">Result</h2>
                <p className="text-sm text-muted-foreground">
                  {result.event?.event ?? "No matched event"} {result.event?.commence_time ? `• ${formatCommenceTime(result.event.commence_time)}` : ""}
                </p>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <LookupStatus result={result} />

              {result.resolution_mode && (
                <div className="rounded-lg border border-border p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Resolution Mode</div>
                  <div className="mt-1 font-medium">{formatResolutionMode(result.resolution_mode)}</div>
                </div>
              )}

              {result.confidence && (
                <div className="grid gap-2 rounded-lg border border-border p-3 text-sm md:grid-cols-3">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Lookup Confidence</div>
                    <div className="font-medium capitalize">{result.confidence.bucket.replace("_", " ")}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Repo Score</div>
                    <div className="font-medium">
                      {result.confidence.repo_label ?? "Unknown"}
                      {typeof result.confidence.repo_score === "number" ? ` • ${result.confidence.repo_score.toFixed(2)}` : ""}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">{consensusBookLabel}</div>
                    <div className="font-medium">{consensusBookCount}</div>
                  </div>
                </div>
              )}

              {result.consensus && (
                <>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg border border-border p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Over Consensus</div>
                      <div className="mt-1 text-lg font-semibold">
                        {formatProbability(result.consensus.over_prob)} • {formatOdds(result.consensus.fair_over_odds)}
                      </div>
                    </div>
                    <div className="rounded-lg border border-border p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Under Consensus</div>
                      <div className="mt-1 text-lg font-semibold">
                        {formatProbability(result.consensus.under_prob)} • {formatOdds(result.consensus.fair_under_odds)}
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg border border-border p-3 text-sm">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Best Over</div>
                      <div className="mt-1 font-medium">
                        {result.consensus.best_over_sportsbook ?? "Unknown"} • {formatOdds(result.consensus.best_over_odds)}
                      </div>
                      {result.consensus.best_over_deeplink_url && (
                        <a
                          className="mt-2 inline-flex text-xs text-primary underline-offset-2 hover:underline"
                          href={result.consensus.best_over_deeplink_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open over deeplink
                        </a>
                      )}
                    </div>
                    <div className="rounded-lg border border-border p-3 text-sm">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Best Under</div>
                      <div className="mt-1 font-medium">
                        {result.consensus.best_under_sportsbook ?? "Unknown"} • {formatOdds(result.consensus.best_under_odds)}
                      </div>
                      {result.consensus.best_under_deeplink_url && (
                        <a
                          className="mt-2 inline-flex text-xs text-primary underline-offset-2 hover:underline"
                          href={result.consensus.best_under_deeplink_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open under deeplink
                        </a>
                      )}
                    </div>
                  </div>

                  <div className="rounded-lg border border-border p-3 text-sm">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">{consensusBookLabel}</div>
                    <div className="mt-1 font-medium">
                      {consensusBooks.length > 0 ? consensusBooks.join(", ") : "None"}
                    </div>
                  </div>

                  {result.consensus.offers.length > 0 && (
                    <div className="rounded-lg border border-border">
                      <div className="border-b border-border px-3 py-2 text-sm font-medium">{offerSectionTitle}</div>
                      <div className="divide-y divide-border">
                        {result.consensus.offers.map((offer) => (
                          <div key={offer.sportsbook} className="grid gap-2 px-3 py-3 text-sm md:grid-cols-3">
                            <div className="font-medium">{offer.sportsbook}</div>
                            <div>Over {formatOdds(offer.over_odds)}</div>
                            <div>Under {formatOdds(offer.under_odds)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {result.observed_offers.length > 0 && (
                <div className="rounded-lg border border-border">
                  <div className="border-b border-border px-3 py-2 text-sm font-medium">Observed Ladder</div>
                  <div className="divide-y divide-border">
                    {result.observed_offers.map((offer) => (
                      <div
                        key={`${offer.sportsbook}-${offer.line_value}`}
                        className="grid gap-2 px-3 py-3 text-sm md:grid-cols-4"
                      >
                        <div className="font-medium">{offer.sportsbook}</div>
                        <div>Line {offer.line_value}</div>
                        <div>Over {formatOdds(offer.over_odds)}</div>
                        <div>Under {formatOdds(offer.under_odds)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.status === "ambiguous_event" && result.candidate_events.length > 0 && (
                <div className="rounded-lg border border-border">
                  <div className="border-b border-border px-3 py-2 text-sm font-medium">Candidate Events</div>
                  <div className="divide-y divide-border">
                    {result.candidate_events.map((event) => (
                      <div key={`${event.event_id ?? event.event}-${event.commence_time ?? ""}`} className="px-3 py-3 text-sm">
                        <div className="font-medium">{event.event}</div>
                        <div className="text-muted-foreground">{formatCommenceTime(event.commence_time)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </main>
  );
}
