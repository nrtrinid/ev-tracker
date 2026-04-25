# Deeplink Reliability Audit

Last updated: 2026-04-24
Status: in progress
Scope: scanner and board sportsbook handoff links for trusted beta

This audit tracks whether scanner cards hand users to the expected sportsbook destination, and what fallback copy should appear when the provider cannot supply a precise betslip or market link.

## Current Implementation

Deeplink source of truth:

- Backend resolver: `backend/services/sportsbook_deeplinks.py`
- Straight-bet link extraction: `backend/services/odds_api.py`
- Player-prop link extraction: `backend/services/player_props.py`
- Frontend action/copy model: `frontend/src/app/scanner/scanner-ui-model.ts`
- Card rendering: `frontend/src/app/scanner/components/StraightBetCard.tsx` and `frontend/src/app/scanner/components/PlayerPropCard.tsx`

Resolution order:

1. Selection link from provider outcome payload.
2. Market link from provider market payload.
3. Event link from provider bookmaker payload.
4. Known sportsbook homepage fallback.
5. Log-only CTA when no safe URL is available.

Safety rules:

- Only `http` and `https` links are accepted.
- URLs with unresolved template braces are rejected.
- The exact BetMGM template host `sports.{state}.betmgm.com` is canonicalized to `sports.betmgm.com`.
- Button copy reflects destination precision:
  - `selection`: `Place at {Sportsbook}`
  - `market`: `Open Market at {Sportsbook}`
  - `event`: `Open Event at {Sportsbook}`
  - `homepage`: `Open {Sportsbook}`
  - no link: `Review & Log`

## Coverage Matrix

Legend:

- `selection`: should open directly to the bet selection or betslip when provider support works.
- `market`: should open the market and still require selection verification.
- `event`: should open the game/event and require line lookup.
- `homepage`: safe fallback only; user must navigate manually.
- `needs QA`: requires human desktop/mobile/app validation with real sportsbook accounts and geo/plugin conditions.

| Sportsbook | Scanner surface | Current safe fallback | Expected best level | Desktop web QA | Mobile web QA | Native app QA | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DraftKings | Game lines, player props | `https://sportsbook.draftkings.com/` | selection | needs QA | needs QA | needs QA | Backend consumes outcome, market, and event links when provider supplies them. |
| FanDuel | Game lines, player props | `https://sportsbook.fanduel.com/` | selection | needs QA | needs QA | needs QA | Backend consumes outcome, market, and event links when provider supplies them. |
| BetMGM | Game lines, player props | `https://sports.betmgm.com/` | selection | needs QA | needs QA | needs QA | Exact `{state}` host template is canonicalized; other templates are rejected. |
| Caesars | Game lines, player props | `https://www.caesars.com/sportsbook` | selection | needs QA | needs QA | needs QA | Provider key is `williamhill_us`; display name is `Caesars`. |
| ESPN Bet | Game lines | `https://sportsbook.thescore.bet/` | selection | needs QA | needs QA | needs QA | Homepage fallback should be verified carefully because brand/app routing may differ by platform. |
| Bovada | Player props reference/target set | `https://www.bovada.lv/sports` | selection | needs QA | needs QA | n/a | Offshore web flow; app handoff likely not applicable for most beta users. |
| BetOnline.ag | Player props reference/target set | `https://www.betonline.ag/sportsbook` | selection | needs QA | needs QA | n/a | Offshore web flow; app handoff likely not applicable for most beta users. |

## Initial Findings

- Backend and frontend both maintain sportsbook homepage fallback maps. They currently match for active scanner books, but duplication creates drift risk.
- Fallback behavior is destination-aware, but the card UI does not expose the trust hint text from `buildScannerActionModel`; users only see the CTA label.
- Existing automated coverage verifies link sanitization, BetMGM canonicalization, selection-level propagation, homepage fallback, and visible CTA labels.
- Browser/app reliability cannot be proven by unit tests because geo checks, installed-app routing, login state, and sportsbook-specific redirects change the user path.
- Pick'em comparison cards link directly to best sportsbook URLs when present, but they do not use the same action model/copy hierarchy as standard scanner cards.

## Human QA Checklist

For each sportsbook and platform, capture:

- Surface tested: game lines or player props.
- Market tested: moneyline, spread, total, or prop market.
- Link level observed in payload: selection, market, event, homepage, or none.
- Result after click/tap: betslip, market, event, homepage, login wall, geo wall, unsupported, or dead link.
- Whether the odds/line shown at the destination match the scanner card.
- Whether app-open behavior is better or worse than web.
- Required fallback copy or UI hint.

Suggested pass/fail labels:

- `pass`: lands on the expected selection or market with minimal friction.
- `usable`: lands on event/homepage and user can find the wager quickly.
- `degraded`: login/geo/app redirect adds friction but the user can recover.
- `fail`: dead link, wrong event, wrong market, unsupported region, or unclear recovery.

## Next Implementation Candidates

1. Move active sportsbook homepage metadata into a shared frontend/backend fixture or add parity tests so fallback maps cannot drift.
2. Show a compact destination hint when the CTA is market/event/homepage level, using the existing trust-hint text.
3. Route Pick'em comparison CTAs through the same action model so fallback copy is consistent.
4. Add an ops-only deeplink QA note field or static matrix that records the latest manual result per book/platform.
5. Add tests for unsupported/unknown active books so log-only behavior remains intentional.
