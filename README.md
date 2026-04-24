# EV Betting Tracker

[![Backend tests](https://github.com/nrtrinid/ev-tracker/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/nrtrinid/ev-tracker/actions/workflows/backend-tests.yml)

**Find +EV bets, log them, and track real P&L across every sportsbook.**

EV Betting Tracker is a multi-tenant SaaS application for sharp sports bettors. It uses live odds from [The Odds API](https://the-odds-api.com) and Pinnacle as a sharp-line reference to surface positive expected value (+EV) opportunities across DraftKings, FanDuel, BetMGM, Caesars, and ESPN Bet — then gives you the math to size them.

> **Status:** Trusted beta (`v2.2.0-beta.2`). `main` is the stable branch for invited testers, with active iteration continuing on `dev`.

---

## What Makes It Different

| Feature | What it means |
|---|---|
| **Pinnacle de-vig** | Uses Pinnacle's sharp two-way lines as a no-vig probability reference instead of relying on book-implied probabilities |
| **4 Promo Lenses** | Scanner adapts its math per promo type — standard EV, profit boosts, bonus bet conversion, and qualifier legs all have distinct objectives |
| **Fractional Kelly sizing** | Recommends bet sizes based on your bankroll and a configurable Kelly multiplier (default: quarter Kelly) |
| **Server-side caching** | 5-minute TTL cache per sport — multiple users share the same Odds API call, protecting token quota |
| **Multi-book scanning** | One scan covers all your selected books simultaneously at no extra API cost |
| **Full P&L tracking** | Log every bet (pre-game), settle it after, and see actual vs. expected return over time |
| **Automation hardening** | Scheduler heartbeats + readiness freshness checks + cron fallbacks keep scans/settles reliable |
| **Operator observability** | Internal `/admin/ops` console shows automation health, CLV tracking states, pick'em validation, and compact Odds API activity summaries |

---

## Screenshots

<img width="652" height="552" alt="image" src="https://github.com/user-attachments/assets/f8253a3e-06a8-4898-94af-e76c579de6c5" />

<img width="607" height="694" alt="image" src="https://github.com/user-attachments/assets/98e88e2c-fda1-4daa-8ddd-f0b0e126b234" />

<img width="743" height="956" alt="image" src="https://github.com/user-attachments/assets/07fbf302-6455-445a-84f1-d0ec00ff46bf" />

---

## Feature Set

### Daily Drop Board
- Daily-drop board powers Home across `Promos`, `Game Lines`, and `Player Props`
- Manual straight-bet scanner across NBA, NCAAB, and MLB
- **Standard EV** lens: top +EV game lines sorted by edge
- **Profit Boost** lens: recalculates EV after applying an x% profit multiplier
- **Bonus Bet** lens: sorts by retention rate (`true_prob × decimal_odds`) to maximize free-bet conversion
- **Qualifier** lens: filters odds between −250 and +150, minimizing expected qualifying loss
- Result filter bar: Search, Time presets, Standard-only Edge threshold, and More menu controls
- More controls: Hide longshots, Hide already logged, and risk presets (Any/Safer/Balanced)
- Distinct null states: "no scanner results" vs "no matches for active filters"
- Duplicate-state badges identify `Already Placed`, `Placed Elsewhere`, and `Better Now` opportunities across straight bets and player props
- Per-book badges (DK, FD, MGM, CZR, ESPN)
- "Fair Odds" line shows the de-vigged Pinnacle line for every result
- One-tap pre-fill into the log drawer
- Player Props surface with two clear modes:
  - **Sportsbooks** for curated prop cards with consensus fair odds
  - **Pick'em** for exact-line board comparisons and matching-book support
- MLB sportsbook props now use five standard markets in the shared main feed:
  - Pitcher Strikeouts, Total Bases, Total Bases Alt, Hits, and Hits + Runs + RBIs
- Canonical-equivalent Total Bases and Total Bases Alt offers from the same sportsbook are collapsed on the board so duplicate cards do not appear unless the alternate ladder is actually the better price
- Promos merges promo-ranked game lines and player props into one board view
- Pregame-only availability messaging so stale scans explain when started games are hidden

### Bet Logging
- Log bets with full promo context (standard, boost %, bonus bet, no-sweat, qualifier)
- Supports winnings cap for boosted bets
- Open Bets can show compact backend-fetched live state (currently NBA and MLB game status/score plus supported NBA/MLB prop progress) without expanding card height by default
- Settle bets (win/loss/push/void) and see real P&L vs. expected

### Parlay Builder
- Build one-book parlays from straight bets and sportsbook props
- Uses de-vigged fair odds from the scanner for parlay pricing and EV estimation
- Auto-fills stake from the current Kelly recommendation when a fair estimate is available
- Logs directly into the main tracker instead of relying on saved server-side drafts

### Dashboard & Analytics
- Total P&L, EV earned, edge vs. actual
- Balance tracking per sportsbook
- EV per dollar by promo type
- Internal beta analytics defaults to external tester signal and tracks excluded internal/test activity separately for ops visibility

### Settings
- Configure Kelly multiplier (10%, 25%, 50%, full)
- Set bankroll: use computed (sum of logged balances) or override manually
- Persisted per user and mirrored locally for fast reloads
- Theme preference is stored per account and synced across devices

### Internal Ops Console
- Route: `/admin/ops` (allowlisted operators only)
- Scheduler-first **Automation Health** panel, with cron run details as fallback visibility
- **Beta Analytics** cards default to external tester signal while reporting excluded internal/test counts and quality warnings
- **Odds API Activity** panel:
    - Calls/errors in the last hour
    - Last success/error timestamps
    - Recent compact call history (source, endpoint, cache-hit/live call, status, duration)
- Frontend fallback derivation keeps status useful during partial backend rollout windows

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Browser                         │
│ Next.js 14 (App Router)  ·  React Query  ·  Tailwind│
│   /  /scanner  /analytics  /bets  /settings         │
└───────────────────┬─────────────────────────────────┘
                    │  HTTPS / JSON
┌───────────────────▼─────────────────────────────────┐
│                 FastAPI (Python)                    │
│   /api/scan-markets   /bets   /settings   /balances │
│   Auth via Supabase JWT  ·  Rate limiting  ·  Cache │
└───────────┬──────────────────────┬──────────────────┘
            │                      │
┌───────────▼───────┐   ┌──────────▼───────────────────┐
│  Supabase Postgres│   │      The Odds API            │
│  bets · balances  │   │  Live h2h odds — Pinnacle +  │
│  users · RLS      │   │  DK, FD, MGM, CZR, ESPN Bet  │
└───────────────────┘   └──────────────────────────────┘
```

**Key files:**
- `backend/services/odds_api.py` — fetch, de-vig, edge calculation, cache
- `backend/calculations.py` — EV math, Kelly criterion, odds conversion
- `backend/routes/scan_routes.py` — scan endpoint routing
- `backend/routes/settings_routes.py` — settings and onboarding state endpoints
- `backend/dependencies.py` — shared auth/rate-limit/ops-token dependencies
- `backend/main.py` — FastAPI app bootstrap + scanner handler implementations
- `frontend/src/app/scanner/[surface]/page.tsx` — scanner surface routing
- `frontend/src/app/scanner/components/ScannerResultFilters.tsx` — scanner filter bar UI
- `frontend/src/lib/scanner-filters.ts` — scanner result-filter helpers
- `frontend/src/lib/kelly-context.tsx` — global Kelly/bankroll state
- `frontend/src/lib/theme-context.tsx` — local + server-synced theme preference state
- `frontend/src/app/scanner/ScannerSurfacePage.tsx` — scanner orchestration, filtering, and props subviews
- `frontend/src/app/parlay/page.tsx` — local parlay builder and tracker handoff

See [PROJECT.md](./PROJECT.md) for full architecture, conventions, and key decisions.

---

## Local Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- A [Supabase](https://supabase.com) project (free tier works)
- A [The Odds API](https://the-odds-api.com) key (500 free requests/month)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
```

Edit `backend/.env`:
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ODDS_API_KEY=your-odds-api-key
ENVIRONMENT=development
LOG_LEVEL=INFO
CRON_TOKEN=your-random-cron-token
BETA_INVITE_CODE="Daily Drop"
OPS_ADMIN_EMAILS=ops@example.com
# Optional: exclude known test accounts from default beta analytics views
ANALYTICS_TEST_EMAILS=tester@example.com
# Scheduled board-drop alerts use the alert route; ops/test/heartbeat traffic uses debug.
DISCORD_ENABLE_ALERT_ROUTE=1
DISCORD_ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_DEBUG_WEBHOOK_URL=https://discord.com/api/webhooks/...
# Optional: disable/enable live snapshots endpoint output (default: 1)
LIVE_TRACKING_ENABLED=1
# Optional: provider priority list (current MVP defaults to ESPN NBA + MLB StatsAPI)
LIVE_TRACKING_PROVIDER_ORDER=espn,mlb,api_sports,odds_scores
# Optional: auto-settle score source (default: provider-first NBA/MLB finals,
# with Odds API scores as fallback)
AUTO_SETTLE_SCORE_SOURCE=provider_first
AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS=1
AUTO_SETTLE_PROVIDER_FINALITY_DELAY_MINUTES=15
# Optional: shared state backend for multi-instance rate-limit/cache coordination
# REDIS_URL=redis://localhost:6379/0
ALERT_DEDUPE_TTL_SECONDS=21600
```

### Operator-triggered automation
If you want external wake/trigger automation, use a scheduler (cron-job.org, GitHub Actions, etc.) to hit these endpoints:

- `POST /api/ops/trigger/scan` (warms scanner cache; manual ops-triggered notifications use the debug/heartbeat route while scheduled board-drop windows use the alert route)
- `POST /api/ops/trigger/auto-settle` (grades eligible pending ML bets, supported NBA/MLB props, parlays, and pick'em research rows)
- `POST /api/ops/trigger/test-discord` (sends a test Discord message through the debug/test route)
- `POST /api/ops/trigger/test-discord-alert` (sends an alert-style validation message through the debug/test route without touching the live alert path)

All operator endpoints require the header `X-Ops-Token` matching `CRON_TOKEN`.

Frontend bridge routes (for serverless schedulers that should not hold backend secrets directly):

- `GET /api/cron/wakeup` (requires `Authorization: Bearer ${CRON_SECRET}`)
- `GET /api/cron/trigger-backend?target=scan|auto-settle|test-discord` (same auth)

`target=settle` is accepted and mapped to `auto-settle` for compatibility.

Health endpoints:
- `GET /health` for liveness (process is up)
- `GET /ready` for readiness (Supabase env + DB connectivity; scheduler freshness is advisory for `APP_ROLE=api` and enforced for scheduler roles)
- `GET /api/ops/status` for operator status (requires `X-Ops-Token`)
- `GET /api/ops/clv-debug` for CLV audit counts/samples across bets + research tracking (requires `X-Ops-Token`)

For production verification (health, ops, and Discord checks), use [DEPLOY.md](./DEPLOY.md#discord-verification-required).

Readiness scheduler freshness uses a startup grace window equal to each job's expected
stale window, so a fresh deploy is not marked degraded before the first scheduled run.

If you use the frontend cron bridge routes (for example on Vercel), set `BACKEND_BASE_URL`
in the frontend environment so the bridge knows where to forward cron triggers.

```bash
python entrypoint.py
# → http://localhost:8000
```

To run the scheduler locally in a separate process:

```bash
$env:APP_ROLE="scheduler"        # Windows PowerShell
$env:ENABLE_SCHEDULER="1"
python entrypoint.py
```

### Frontend

```bash
cd frontend
npm install
copy .env.example .env.local   # Windows
# cp .env.example .env.local   # macOS/Linux
```

Edit `frontend/.env.local`:
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://localhost:8000
BACKEND_BASE_URL=http://localhost:8000
CRON_SECRET=your-random-cron-secret
CRON_TOKEN=your-backend-cron-token
OPS_ADMIN_EMAILS=ops@example.com
BETA_INVITE_CODE="Daily Drop"
NEXT_PUBLIC_DISCORD_INVITE_URL=https://discord.gg/your-beta-invite
```

Production / preview Vercel env:
- `NEXT_PUBLIC_API_URL=/api/backend`
- `BACKEND_BASE_URL=http://5.78.192.196`

That keeps browser requests same-origin through the Next proxy while server-side bridge routes still forward to Hetzner directly. Once you provision a real HTTPS backend hostname, only `BACKEND_BASE_URL` needs to change.

For the complete environment variable reference (including optional values), see [PROJECT.md](./PROJECT.md#environment-variables).

### Trusted beta readiness

Before inviting testers onto `main`:

- Confirm migration parity and apply-order rules in [database/README.md](./database/README.md)
- Confirm backend/frontend release env values in [DEPLOY.md](./DEPLOY.md#beta-env-checklist)
- Run the production verification sequence in [DEPLOY.md](./DEPLOY.md#discord-verification-required)
- Run the tester-facing launch checks in [docs/trusted-beta.md](./docs/trusted-beta.md#launch-day-checklist)

### Internal operator console

- Route: `/admin/ops` (internal use)
- Data source: frontend server bridge `GET /api/ops/status` -> backend `GET /api/ops/status`
- Security: the browser never receives `X-Ops-Token`; token is injected server-side only

Operator access control:
- Both `/admin/ops` and `/api/ops/status` require a logged-in user
- Both routes require email allowlist membership via `OPS_ADMIN_EMAILS`
- Allowlist matching is exact after lowercase + trim normalization
- If `OPS_ADMIN_EMAILS` is unset/empty, access fails closed
- Backend ops calls use server-side `CRON_TOKEN` (or `CRON_SECRET` fallback) only
- Backend remains source-of-truth; frontend operator status route is a protected bridge only

```bash
npm run dev
# → http://localhost:3000
```

---

## Testing

A small but meaningful test suite protects EV math, settlement/profit logic, scheduler/ops status behavior, and critical UI access paths. Details (what’s live vs mocked, what’s covered vs manual): [docs/testing.md](./docs/testing.md).

- **Backend unit tests** (math layer): `cd backend && pytest tests/test_calculations.py -v` — or unit-only by marker: `cd backend && pytest -m "not integration" -v`
- **Backend hardening tests** (scheduler + odds activity): `cd backend && pytest tests/test_scheduler.py tests/test_odds_api_activity.py -v`
- **Backend integration tests** (requires test Supabase and auth user): From `backend/` with venv + full deps (`pip install -r requirements.txt`): Set `TESTING=1`, `SUPABASE_URL` (or `TEST_SUPABASE_URL`), and `TEST_USER_ID`. Then: Windows PowerShell: `$env:TESTING="1"; pytest tests/test_api.py -v` — macOS/Linux: `TESTING=1 pytest tests/test_api.py -v`. By marker: `$env:TESTING="1"; pytest -m integration -v` (Windows) or `TESTING=1 pytest -m integration -v` (macOS/Linux). Set `TEST_USER_ID` to a UUID that exists in your test project’s `auth.users`, or create a user and use its id. Optional: `TEST_SUPABASE_URL` and `TEST_SUPABASE_SERVICE_ROLE_KEY` for a separate test project.
- **Frontend build + typecheck**: `cd frontend && npm run build && npm run typecheck`
- **Playwright browser smoke** (run with frontend and backend dev servers up): From `frontend/`: `npm install`, then `npx playwright install`, then `npm run test:smoke:list`, `npm run test:smoke`, or `npm run test:e2e` for the broader browser-only set. Set `PLAYWRIGHT_TEST_EMAIL` and `PLAYWRIGHT_TEST_PASSWORD` so smoke tests can log in; otherwise they skip cleanly.
- **Operator access tests**: `cd frontend && npm run test:ops-utils` and (with non-admin creds) `npm run test:ops-access`
- **Quarantined frontend utility specs**: `cd frontend && npm run test:quarantined` when you want extra signal without making those suites beta-blocking.
- **CI**: GitHub Actions runs backend unit tests and the integration marker. Integration tests skip cleanly when test Supabase secrets are not configured. Playwright remains local-only.

---

## Docs

| Document | What it covers |
|---|---|
| [docs/methodology.md](./docs/methodology.md) | How Pinnacle lines are de-vigged and EV is calculated |
| [docs/scanner.md](./docs/scanner.md) | End-to-end scanner pipeline |
| [docs/promos.md](./docs/promos.md) | Math behind each promo lens |
| [docs/player-props-v2.md](./docs/player-props-v2.md) | Curated props, pick'em board, quality gates, and board integration |
| [docs/testing.md](./docs/testing.md) | Unit/integration/e2e strategy and hardening coverage |
| [docs/trusted-beta.md](./docs/trusted-beta.md) | Trusted beta expectations, feedback flow, and launch-day checks |
| [docs/workflow.md](./docs/workflow.md) | Lightweight stable-vs-dev workflow for solo shipping and beta testers |
| [docs/secrets.md](./docs/secrets.md) | Secret rotation and local secret hygiene checks |
| [PROJECT.md](./PROJECT.md) | Architecture, conventions, key decisions |
| [DEPLOY.md](./DEPLOY.md) | VPS deploy, production verification sequence, and canonical beta env checklist |
| [database/README.md](./database/README.md) | Canonical migration chain and schema parity workflow |
| [AGENTS.md](./AGENTS.md) | Agent-facing repo conventions, guardrails, and fast validation commands |
| [HANDOFF.md](./HANDOFF.md) | Current focus, recent changes, open risks, and next concrete tasks |
| [FUTURE_PLANS.md](./FUTURE_PLANS.md) | Living launch roadmap with must-ship, should-ship, and later priorities |

---

## Branching Workflow

For beta testing, keep `main` stable and do active work on `dev`.

- `main` should be the branch you are comfortable sharing with testers
- `dev` should be your day-to-day branch for active iteration
- merge `dev -> main` only after local sanity checks pass

See [docs/workflow.md](./docs/workflow.md) for the lightweight workflow and pre-merge checklist.

## Design Docs

UI direction lives here:

- [docs/design/design-direction.md](./docs/design/design-direction.md)

---

## Stack

Tech stack details live in [PROJECT.md](./PROJECT.md#tech-stack).

---

## Security

See [SECURITY.md](./SECURITY.md) for our vulnerability disclosure policy.

---

## License

[MIT](./LICENSE)
