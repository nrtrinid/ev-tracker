# Player Props V2

This document describes the current curated player-props system used across the manual scanner, daily board, Pick'em validation, and CLV tracking.

## Goals

- avoid unsupported Pinnacle assumptions for player props
- keep Odds API token usage bounded
- surface only props backed by credible cross-book consensus
- make thin or empty runs diagnosable
- support board-time research and close tracking without lowering surfaced-card quality

## Core Flow

1. Curate NBA events instead of crawling every prop market blindly.
2. Fetch flagship prop markets for those events.
3. Build no-vig over/under probabilities per book.
4. Exclude the target book from its own reference pool.
5. Use the remaining market set to produce fair probability and fair odds.

## Quality Gates

- Surfaced sportsbook prop cards default to `PLAYER_PROP_MIN_REFERENCE_BOOKMAKERS=3`
- Pick'em board + pick'em research default to `PLAYER_PROP_PICKEM_MIN_REFERENCE_BOOKMAKERS=2`
- Thin references still appear in diagnostics, but they do not surface as normal cards
- CLV close capture can use the looser `PLAYER_PROP_CLV_MIN_REFERENCE_BOOKMAKERS`

That separation is intentional:

- surfaced cards should be conservative
- pick'em validation should still form exact-line pairs often enough to be measurable
- logged-bet close capture should recover as many valid closes as possible

## Current Runtime Behavior

Player props now participate in multiple runtime paths:

- manual scanner props at `/scanner/player_props`
- scheduled daily-board props on the home page
- Pick'em board generation
- Pick'em research capture
- logged-bet CLV close tracking

What is still true:

- NBA props use curated game discovery, while MLB props scan the supported pregame slate directly
- surfaced prop cards require stronger consensus than CLV close capture
- board and research paths should be treated as operationally important, not just UI extras

Current standard MLB sportsbook markets:

- `pitcher_strikeouts`
- `batter_total_bases`
- `batter_hits`
- `batter_hits_runs_rbis`
- `batter_home_runs`
- `batter_strikeouts`

## Operator Checklist

1. Run a manual `/scanner/player_props` scan.
2. Confirm diagnostics show shortlist, matched events, fetched events, and surfaced side counts.
3. Confirm `Sportsbooks` and `Pick'em` modes are both understandable.
4. Confirm surfaced cards show player, line, sportsbook, and confidence.
5. Log one prop and verify the bet row stores source metadata.
6. Confirm the daily board persists props and Pick'em artifacts cleanly.
7. Confirm logged prop bets now capture CLV close snapshots on the next valid window.

## Key Files

- `backend/services/player_props.py`
- `backend/services/player_prop_board.py`
- `backend/services/pickem_research.py`
- `backend/services/odds_api.py`
- `frontend/src/app/scanner/ScannerSurfacePage.tsx`
- `frontend/src/app/scanner/components/PlayerPropCard.tsx`
- `frontend/src/app/scanner/components/PickEmBoardCard.tsx`
