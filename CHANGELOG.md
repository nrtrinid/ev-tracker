# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Version labels use pre-release suffixes until the app is ready for outside users: `-alpha.N` (early dev), `-beta.N` (trusted beta / dogfooding), then a final `v2.2.0` when comfortable inviting others.

---

## [Unreleased]

### Added

- **Bankroll Center**
  - Added a compact header bankroll pill that opens a shared mobile-first drawer for total bankroll, per-book balances, and manual bankroll activity.
  - Added logged deposits, withdrawals, and tracked-balance adjustments to the existing transaction ledger while keeping bet settlement effects in `/balances`.
  - Added migration `database/migration_024_bankroll_center_transactions.sql` for adjustment transactions, transaction dates, updated timestamps, and balance-activity indexes.
- **Live bet tracking MVP**
  - Added backend-owned `/bets/live` snapshots for compact Bets-page live status, score, and supported NBA player-prop progress.
  - Added ESPN-backed live provider normalization with shared cache/stale fallback behavior and a provider abstraction for future documented backups.
  - Added a fixed-height live chip to Open Bets cards so live state appears inline without adding a default card row.
  - Added the live-tracking index migration for pending-bet live-window lookup performance.
  - Added focused backend and frontend tests for live snapshot contracts, provider normalization, and chip-state formatting.
  - Expanded live tracking to MLB via StatsAPI-backed game matching, inning-aware live state, and compact progress counters for the safe MLB prop set (`pitcher_strikeouts`, `pitcher_strikeouts_alternate`, `batter_total_bases`, `batter_total_bases_alternate`, `batter_hits`, `batter_hits_alternate`, `batter_hits_runs_rbis`).

### Changed

- **Middleware availability hotfix**
  - Prevented slow or unavailable Supabase auth lookups from timing out Vercel middleware and taking down public auth pages.
- **Crash-prevention guardrails**
  - Made readiness use a bounded direct Supabase probe and stop writing failure history during readiness failures.
  - Made ops status fall back to in-memory status when DB connectivity is degraded.
  - Routed frontend cron board-refresh triggers to the backend async endpoint and added a bridge timeout.
  - Made Next production builds use a single worker to avoid intermittent missing-manifest failures during page-data collection.
  - Blocked test DB initialization against production Supabase unless `ALLOW_PROD_TESTS=1` is set deliberately.
- **Mobile Safari chrome polish**
  - Matched iPhone Safari browser chrome to the app shell and made mobile sticky offsets safe-area aware so the top header and bottom nav feel anchored instead of floating against Safari's bars.
- **Beta analytics trust hardening**
  - Canonicalized analytics metadata and dedupe handling so key events carry stable source attribution (`origin_surface`, `book`, `market`, `edge_bucket`, `opportunity_id` when available).
  - Defaulted ops beta analytics summary/user drilldown to external tester signal while exposing excluded internal/test counts and quality warnings.
  - Added backend analytics service/reporting tests plus frontend analytics bridge timeout/access coverage.
- **Scanner duplicate-state badges**
  - Applied duplicate-state tagging consistently across straight-bet and player-prop scanner cards, including `Already Placed`, `Placed Elsewhere`, and `Better Now` badges.
  - Extended straight-bet duplicate matching to support spread/total selection identity while preserving legacy moneyline matching.
- **MLB prop market scope**
  - Removed `batter_home_runs`, `batter_strikeouts`, and `batter_strikeouts_alternate` from the supported/shared MLB prop scan registry.
  - Kept historical labels and settlement support intact for existing logged bets while narrowing active scan coverage to the remaining MLB prop set.
- **MLB alt total-bases support**
  - Promoted `batter_total_bases_alternate` into the default MLB prop scan set and scanner market filters.
  - Added canonical `2+ -> over 1.5` threshold handling so one-sided alternate total-base ladders can surface as sportsbook targets while fair odds still come from paired reference books.
  - Collapsed same-book canonical-equivalent `TB`/`TB ALT` offers so redundant cards no longer survive when a sportsbook publishes both versions at the same effective line.
- **Release/docs parity**
  - Refreshed README, PROJECT env reference, HANDOFF, and FUTURE_PLANS so roadmap status and current release context match the implemented beta hardening work.
- **Ops visibility and Discord routing**
  - Tightened Discord route isolation so debug/test/heartbeat traffic cannot fall back onto the alert webhook path.
  - Restricted alert-path Discord delivery to scheduler-owned board-drop contexts and removed the legacy generic webhook fallback from active routing/docs.
  - Added a scheduled board-drop alert freshness guard so sleeping/paused scheduler instances cannot replay the 09:30/15:00 alert hours late.
  - Updated ops status freshness selection so live scheduler board-drop state can beat stale durable history on the ops page.
- **Provider-first auto-settle**
  - Switched NBA/MLB auto-settle completed-game detection to provider finals first, with a 15-minute finality delay and Odds API score fallback for unresolved or unsupported sports.
  - Added auto-settle score-source telemetry so ops runs show provider completions, fallback sports, fetch errors, and finality-delay skips.
  - Limited provider score prefetching to auto-settle-eligible rows so old manual-only bets no longer force large ESPN/MLB scoreboard crawls during settle runs.

## [2.2.0-beta.2] - 2026-04-17

### Added

- **Admin alt pitcher K lookup**
  - Added an admin-only exact-line MLB alternate pitcher strikeout lookup flow with route protection, typed API bridge, dedicated response models, and targeted tests.
- **MLB player props main-feed expansion**
  - Added `batter_home_runs` to the shared MLB player-prop market registry, frontend labels, and auto-settle path.
- **Theme preference persistence**
  - Added persisted user theme setting (`settings.theme_preference`) so light/dark preference now survives refreshes and syncs across signed-in devices.
  - Added migration `database/migration_021_theme_preference.sql` with a constrained `light|dark` value set.

### Changed

- **Trusted-beta UX and search reliability**
  - Improved Markets search behavior so player-prop matching includes market labels/keys and straight-bet search accepts user-facing market terms.
  - Improved Promos filter transparency by exposing separate prop/game-line book controls and consistent reset/chip behavior.
  - Updated scanner empty-state guidance copy to match active controls.
- **Discord routing safety**
  - Hardened debug/test routing so heartbeat/test traffic only falls back to primary Discord webhook/role when explicitly enabled.
  - Added env/docs/test coverage for `DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY` behavior.
- **MLB player props**
  - Promoted the six standard MLB sportsbook markets in the shared player-props feed: pitcher strikeouts, total bases, hits, hits + runs + RBIs, home runs, and batter strikeouts.
  - Kept the existing 3-book sportsbook gate and 2-book pick'em gate unchanged while expanding the market set.
  - Fixed player-props board snapshot fallback metadata so empty or mixed props payloads no longer default to `basketball_nba`.
- **Readiness gate split-role hardening**
  - Updated `/ready` so `APP_ROLE=api` no longer fails readiness on scheduler freshness while still reporting scheduler freshness details for operators.
  - Preserved scheduler freshness enforcement for scheduler-enabled roles.
- **Reliability guardrails (split-role + bridge timeouts)**
  - Added startup warnings when `APP_ROLE` and `ENABLE_SCHEDULER` are misaligned in split-role deployments.
  - Added `backend_api` container healthcheck and healthy dependency gating for Caddy in compose.
  - Added `backend_scheduler` container healthcheck so scheduler role drift is visible in compose health state.
  - Added frontend bridge request timeouts for backend proxy, ops status, and admin trigger routes to fail fast when upstream stalls.
  - Added targeted frontend route tests that assert timeout branches return deterministic `504` responses.
  - Tightened BetMGM deeplink canonicalization to exact placeholder-host matching and added hostile embedding regression tests.
- **Onboarding + settings UX reliability**
  - Fixed onboarding reset sync so backend reset state now authoritatively clears stale local onboarding flags.
  - Updated settings onboarding summary to split Daily Drops tutorial progress from Home/Scanner review prompts.
  - Removed the "Current theme" subtitle under the settings light/dark controls.
- **Research diagnostics clarity**
  - Improved CLV research `By market` aggregation labels to include sport tags and preserve straight-bet market-type distinctions (ML/Spreads/Totals).
- **Release hardening**
  - Cleared admin research dashboard production lint failure by removing an unused diagnostics helper component.

### Docs

- Refreshed trusted-beta handoff and runbook context for the deployed trusted-beta baseline.
- Updated README, PROJECT.md, DEPLOY.md, and docs/testing.md to match the current route surface, migration chain, and test command conventions.

## [2.2.0-beta.1] - 2026-04-01

### Added

- **Trusted beta support surfaces**
  - Added a reusable trusted-beta feedback card inside the app.
  - Added a public `NEXT_PUBLIC_DISCORD_INVITE_URL` env hook for the beta Discord invite link.
- **Trusted beta runbook**
  - Added `docs/trusted-beta.md` with beta expectations, Discord workflow, env checklist, and launch-day operator steps.

### Changed

- **Docs and release posture**
  - Updated README and supporting docs to describe the current daily-drop board, promos/game lines behavior, player props + pick'em flow, CLV tracking, and release workflow more accurately.
  - Formalized split Discord routing for alert vs debug/test webhook usage in env examples and deploy guidance.
  - Promoted the project framing from alpha-era setup notes to a trusted-beta launch posture for invited testers.

---

## [2.2.0-alpha.4] - 2026-03-24

### Added

- **Parlay builder polish**
  - Smarter parlay naming based on the legs in the cart.
  - De-vigged fair-odds inputs and reference true probabilities now carry from the scanner into parlay pricing.
  - Auto-applied stealth Kelly sizing in the parlay builder stake field when a fair estimate is available.
- **Player props UX polish**
  - Larger Sportsbooks vs Pick'em mode selector for the props surface.
  - Pick'em board cards now emphasize the line and matching-book support more clearly.

### Changed

- **Parlay workflow**
  - Removed saved-slip drafting from the main parlay helper flow so the page acts as a local builder and logs directly into the tracker.
  - Simplified Kelly presentation on the parlay page to a compact inline suggestion instead of a larger sizing panel.
- **Scanner behavior**
  - Stale started-game results are no longer counted as available props in empty states.
  - Player-props empty messaging now distinguishes between real filter empties and pregame-only stale scans.
  - Optional scanner parlay coaching was removed to keep the scanner focused on finding and logging plays.

### Docs

- Updated README, workflow guidance, and project documentation for the current player-props, parlay, Kelly, and migration behavior.

---

## [2.2.0-alpha.3] - 2026-03-20

### Added

- **Scanner and ops contract guardrails (PR1)**
  - Backend fixture-based contract tests for scan + ops payload shape parity (`backend/tests/test_scan_ops_contracts.py`).
  - Frontend scanner contract helper module (`scanner-contract.ts`) with null-state helpers and tests.
- **Backend route modularization (PR2)**
  - Centralized dependency module (`backend/dependencies.py`) for auth, scan rate limiting, and ops token checks.
  - APIRouter endpoint ownership for scan/ops/settings/transactions/utility/admin route groups.
- **Scanner filter decomposition (PR3)**
  - New scanner filter utility layer (`scanner-filters.ts`) and dedicated filter-bar component.
  - Search/Time/Edge/More controls with client-side derived filtering and reset behavior.
  - Persisted "Hide Already Logged" preference and explicit backend-empty vs filter-empty messaging.

### Changed

- Scanner page now runs a two-stage client pipeline: lens ranking first, then result filters.
- Backend app bootstrap now owns router registration while core handlers live in route/service modules.

### Docs

- Updated scanner, testing, and architecture docs to match the PR1-PR3 implementation details and test commands.

---

## [2.2.0-alpha.2] - 2026-03-18

### Added

- **Automation + Ops hardening**
  - Scheduler-first automation health model surfaced to operators.
  - Protected backend operator endpoint: `GET /api/ops/status` (cron-token protected).
  - Internal frontend operator console (`/admin/ops`) with allowlist enforcement.
  - Compact Odds API activity telemetry exposed in ops payload (`summary` + `recent_calls`).
- **Protected bridge routes (frontend)**
  - `GET /api/ops/status` server bridge to backend ops endpoint.
  - `GET /api/cron/trigger-backend?target=...` with strict target allowlist.
  - `GET /api/cron/wakeup` for cron-driven keep-alive workflows.
- **Tests**
  - Added/expanded backend hardening coverage (`test_scheduler.py`, `test_odds_api_activity.py`).
  - Added frontend ops access utility and non-admin access checks.

### Changed

- **Ops UI**
  - Automation card emphasizes scheduler as primary execution path, with cron as fallback visibility.
  - Odds API Activity badge/summary now handles fallback data when backend activity block is missing.
- **Status payloads**
  - Backend ops status now injects latest odds-activity snapshot at response time.
- **Docs**
  - Updated README, PROJECT docs, scanner docs, and testing docs to reflect current hardening architecture and test matrix.

---

## [2.2.0-alpha.1] - 2025-03-16

### Added

- **Automation (backend)**
  - **Smart Stake (frontend):** Auto-fill stake in the log-bet drawer when opening from the scanner — promo bets get $10, standard +EV bets get stealth-rounded Kelly.
  - **JIT CLV Snatcher:** Scheduled job every 15 minutes; fetches closing Pinnacle lines for pending bets whose game starts within the next 20 minutes. One Odds API `/odds` call per sport; `pinnacle_odds_at_close IS NULL` used as a lock to avoid duplicate calls.
  - **Auto-Settler:** Daily job at 4:00 AM UTC; grades pending ML bets using The Odds API `/scores`, sets result (win/loss/push) and `settled_at`. Non-ML markets skipped (schema does not store spread/total line).
- **Stealth Mode (frontend)**
  - `calculateStealthStake(rawStake)` in `utils.ts`: tiered rounding (e.g. &lt;$10 → nearest $0.50; $10–$50 → $1; $50–$150 → $5; ≥$150 → $10) so recommended stakes look like normal bet sizes.
  - Scanner passes `raw_kelly_stake` and `stealth_kelly_stake` into the drawer; Rec Bet on cards shows stealth value with an info tooltip for raw Kelly.
  - Log-bet drawer auto-fill uses stealth value for standard bets; promo default $10; quick-select buttons $5 / $10 / $25.
- **Tests**
  - Initial backend tests: `backend/tests/` (e.g. calculations, odds_api-related behavior).
- **Docs**
  - Added initial LLM/onboarding context notes in project documentation.

### Changed

- Drawer promo default stake: 25.00 → 10.00.
- Quick-select stake buttons: $10 / $25 / $50 → $5 / $10 / $25.

---

## [2.1.0]

- CLV tracking system and analytics dashboard refactor.
- 4-layer CLV: piggyback on scans + daily safety-net job.
- New DB columns: pinnacle_odds_at_entry/close, commence_time, clv_team/sport_key, true_prob_at_entry.
- Bet cards: CLV badge and expanded section; analytics updates (Avg CLV, pie → bar charts, etc.).

---

[2.2.0-beta.1]: https://github.com/nrtrinid/ev-tracker/compare/v2.2.0-alpha.4...v2.2.0-beta.1
[2.2.0-beta.2]: https://github.com/nrtrinid/ev-tracker/compare/v2.2.0-beta.1...v2.2.0-beta.2
[2.2.0-alpha.1]: https://github.com/nrtrinid/ev-tracker/compare/v2.1.0...v2.2.0-alpha.1
[2.2.0-alpha.2]: https://github.com/nrtrinid/ev-tracker/compare/v2.2.0-alpha.1...v2.2.0-alpha.2
[2.2.0-alpha.3]: https://github.com/nrtrinid/ev-tracker/compare/v2.2.0-alpha.2...v2.2.0-alpha.3
[2.2.0-alpha.4]: https://github.com/nrtrinid/ev-tracker/compare/v2.2.0-alpha.3...v2.2.0-alpha.4
[2.1.0]: https://github.com/nrtrinid/ev-tracker/compare/v2.0.0...v2.1.0
