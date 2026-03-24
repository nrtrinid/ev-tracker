# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Version labels use pre-release suffixes until the app is ready for outside users: `-alpha.N` (early dev), `-beta.N` (dogfooding / smoke tests), then a final `v2.2.0` when comfortable inviting others.

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
- Backend app bootstrap now includes router registration while keeping core handler implementations in `main.py`.

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
  - `docs/PROJECT_OVERVIEW_FOR_LLM.md` for LLM/onboarding context.

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

[2.2.0-alpha.1]: https://github.com/your-org/ev-betting-tracker/compare/v2.1.0...v2.2.0-alpha.1
[2.2.0-alpha.2]: https://github.com/your-org/ev-betting-tracker/compare/v2.2.0-alpha.1...v2.2.0-alpha.2
[2.2.0-alpha.3]: https://github.com/your-org/ev-betting-tracker/compare/v2.2.0-alpha.2...v2.2.0-alpha.3
[2.2.0-alpha.4]: https://github.com/your-org/ev-betting-tracker/compare/v2.2.0-alpha.3...v2.2.0-alpha.4
[2.1.0]: https://github.com/your-org/ev-betting-tracker/compare/v2.0.0...v2.1.0
