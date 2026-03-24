# Player Props V2

This document describes the manual-only player props scanner introduced in the V2 curated sniper sprint.

## Goals

- avoid unsupported Pinnacle assumptions for player props
- keep The Odds API token usage bounded
- surface only props backed by credible cross-book consensus
- make empty or thin runs diagnosable from the UI and logs

## Architecture

1. ESPN scoreboard prefilter
- Fetch the free ESPN NBA scoreboard window.
- Rank up to 3 games as `national_tv`, then `nba_tv`, then `scoreboard_fallback`.
- Never scan the full NBA slate for props.

2. Odds API event mapping
- Fetch `/v4/sports/basketball_nba/events`.
- Match ESPN shortlist games to Odds API events by canonicalized away/home team pairs.
- Skip unmatched games instead of broadening the search.

3. Single-event prop fetches
- For matched events only, call `/v4/sports/basketball_nba/events/{eventId}/odds`.
- Send all prop books in one `bookmakers=` parameter:
  - `bovada`
  - `betonlineag`
  - `draftkings`
  - `betmgm`
  - `williamhill_us`
  - `fanduel`

4. Sharp consensus math
- For each `(market_key, player, line)` pair, compute each book's no-vig over/under probabilities.
- When evaluating book `X`, exclude `X` from the reference pool.
- Use the median remaining no-vig probability as `true_prob`.
- Convert that fair probability into `reference_odds`.

5. Quality gate
- Default requirement: `PLAYER_PROP_MIN_REFERENCE_BOOKMAKERS=2`
- Thin one-book references are still counted in diagnostics, but they are not surfaced by default.

## Response contract

Player prop sides use:

- `reference_odds`
- `reference_source`
- `reference_bookmakers`
- `reference_bookmaker_count`
- `confidence_label`

The diagnostics payload also includes:

- `candidate_sides_count`
- `quality_gate_filtered_count`
- `quality_gate_min_reference_bookmakers`

## Manual-only rule

Player props are not part of any scheduler, cache-warm, or alert cron path.

- scheduled scans remain straight-bets only
- player props should be triggered manually from `/scanner/player_props`
- any future prop automation should be treated as a new design decision

## Operator checklist

1. Run a manual `/scanner/player_props` scan.
2. Confirm diagnostics show shortlist -> matched -> fetched -> props counts.
3. Confirm the page distinguishes raw props from filtered props.
4. Confirm top cards show player, team, opponent, sportsbook, and confidence.
5. Log one prop from the scanner and verify the bet row stores source metadata.
6. Confirm scheduled scans still do not call the prop scanner.

## Key files

- `backend/services/player_props.py`
- `backend/services/espn_scoreboard.py`
- `backend/services/odds_api.py`
- `backend/routes/scan_routes.py`
- `frontend/src/app/scanner/ScannerSurfacePage.tsx`
- `frontend/src/app/scanner/components/PlayerPropCard.tsx`
- `frontend/src/app/scanner/components/PlayerPropDiagnosticsPanel.tsx`
