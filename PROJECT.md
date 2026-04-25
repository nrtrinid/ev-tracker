# EV Betting Tracker — Project Documentation

Technical documentation for the EV (Expected Value) Betting Tracker: architecture, tech stack, conventions, key logic locations, operational hardening behavior, and important decisions.

---

## Architecture

### Overview

The app is a full-stack web application with a **Next.js frontend** and **FastAPI backend**, backed by **Supabase** (PostgreSQL + Auth). The backend uses the **service role key** to bypass RLS and perform user-scoped operations; RLS protects direct anon access.

Operational hardening adds:

- Scheduler heartbeats and readiness freshness checks.
- Protected operator status bridge (`/api/ops/status`) and internal admin console (`/admin/ops`).
- Cron-trigger fallback routes for sleeping-host environments.
- Odds API activity tracking (summary + recent calls, no secrets/raw payloads).

```
┌─────────────────┐   same-origin API   ┌─────────────────┐   JWT (Bearer)   ┌─────────────────┐   service role client   ┌─────────────────┐
│  Next.js       │ ───────────────────► │  Next route     │ ───────────────► │  FastAPI        │────────────────────────► │  Supabase       │
│  (port 3000)   │   /api/backend/*     │  proxy/bridges   │   REST + bridge  │  (port 8000)    │    (PostgREST/Auth)     │  (PostgreSQL)   │
└─────────────────┘                      └─────────────────┘                   └─────────────────┘                          └─────────────────┘
    │                                                                                   │
    │                                                                                   │
    ▼                                                                                   ▼
  Supabase Auth                                                                      The Odds API
  (SSR + JWT)                                                                        (odds + scores)
```

### Data Flow

1. **Auth**: Supabase Auth → JWT → `api.ts` adds `Authorization` header → local dev calls FastAPI directly, while Vercel production calls same-origin `/api/backend/*` → `auth.get_current_user` validates JWT.
2. **Bets**: `LogBetDrawer` / `EditBetModal` → `api.createBet` / `api.updateBet` → FastAPI → Supabase `bets`.
3. **EV**: `calculate_ev` in `calculations.py` → `build_bet_response` in `services/bet_crud.py` → frontend.
4. **Scanner**: Frontend `scanMarkets()` → `/api/scan-markets` → `services/odds_api.get_cached_or_scan` → The Odds API → de-vig Pinnacle → compare to target books.
5. **Operator status**: `/admin/ops` → protected frontend bridge `/api/ops/status` → backend `/api/ops/status` (server-side ops token).
6. **Automation fallback**: scheduler or external trigger → `/api/ops/trigger/board-refresh` and `/api/ops/trigger/auto-settle`.

### Multi-Tenancy

- `user_id` on `bets`, `transactions`, `settings`.
- RLS policies enforce per-user access.
- Canonical schema history: numbered migrations in `database/migration_*.sql`.

---

## Tech Stack

### Backend

| Category   | Technology      |
|-----------|------------------|
| Framework | FastAPI          |
| Server    | Uvicorn          |
| Validation| Pydantic         |
| Database  | Supabase (PostgreSQL) |
| Auth      | Supabase Auth (JWT)   |
| HTTP      | httpx            |
| Config    | python-dotenv    |

### Frontend

| Category   | Technology              |
|-----------|--------------------------|
| Framework | Next.js 14 (App Router)  |
| UI        | React 18                 |
| Styling   | Tailwind CSS             |
| Components| Radix UI (Dialog, Dropdown, Select, Tabs, etc.) |
| Data      | TanStack React Query v5  |
| Auth      | Supabase SSR + `@supabase/ssr` |
| Charts    | Recharts                 |
| Icons     | Lucide React             |
| Toasts    | Sonner                   |
| Utils     | clsx, tailwind-merge, class-variance-authority |

### External APIs

- **The Odds API** (`api.the-odds-api.com/v4`) — live odds for +EV scanning and fallback settlement scores.
- **ESPN scoreboard + game summary endpoints** — live NBA game state and player-stat progress for compact open-bet snapshots.
- **MLB StatsAPI schedule / linescore / boxscore endpoints** — live MLB game state plus the safe prop-progress set for compact open-bet snapshots.

---

## Project Structure

```
ev-betting-tracker/
├── backend/                 # FastAPI Python backend
|   |-- app entry             # FastAPI composition, middleware, lifespan, router registration
│   ├── dependencies.py      # Shared auth/rate-limit/ops dependencies
│   ├── models.py            # Pydantic schemas (Bet, Settings, Summary, etc.)
│   ├── calculations.py      # EV, odds conversion, Kelly, vig
│   ├── auth.py              # JWT validation via Supabase
│   ├── database.py          # Supabase client
│   ├── routes/              # APIRouter route groups (scan/ops/settings/etc.)
│   ├── services/
│   │   ├── odds_api.py      # Odds/scores integration + activity snapshot
│   │   └── discord_alerts.py
│   ├── seed_data.py         # Mock data seeding
│   ├── requirements.txt
│   └── .env.example
├── frontend/                # Next.js React frontend
│   └── src/
│       ├── app/             # App Router pages (scanner, settings, analytics, login, admin/ops)
│       │   └── api/         # Protected bridge/proxy routes (ops + cron + backend proxy)
│       ├── components/      # UI (BetList, LogBetDrawer, EditBetModal, TopNav, JourneyCoach, ui/)
│       ├── lib/             # api.ts, auth-context, hooks, kelly-context, supabase, types, utils
│       └── middleware.ts    # Auth redirects
├── database/
│   └── migration_001_multi_tenant.sql
└── PROJECT.md               # This file
```

---

## Live Owner Map

Use these files as the live implementation owners when tracing behavior:

| Concern | Live owner |
|---------|------------|
| **Bets** | `backend/routes/bet_routes.py` for HTTP handlers; `backend/services/bet_crud.py` for CRUD and response assembly; `frontend/src/lib/api.ts`, `frontend/src/lib/hooks.ts`, `frontend/src/components/LogBetDrawer.tsx`, `frontend/src/components/EditBetModal.tsx`, and `frontend/src/components/BetList.tsx` for client flows |
| **Summary** | `backend/routes/dashboard_routes.py` `GET /summary` handler; `backend/services/summary_stats.py` for aggregation; `backend/models.py` summary schemas; `frontend/src/lib/api.ts` and `frontend/src/lib/hooks.ts` for fetch/query ownership |
| **Balances** | `backend/routes/dashboard_routes.py` `GET /balances` handler; `backend/services/balance_stats.py` for sportsbook balance calculation; transaction/bet mutation handlers for invalidation inputs; `frontend/src/lib/api.ts`, `frontend/src/lib/hooks.ts`, and settings/bankroll UI consumers |
| **Auth and ops policy** | `backend/auth.py`, `backend/dependencies.py`, `frontend/src/lib/auth-context.tsx`, `frontend/src/middleware.ts`, `frontend/src/lib/server/admin-access.ts`, and protected bridge routes under `frontend/src/app/api/ops/` |
| **Migrations and schema parity** | Numbered files under `database/migration_*.sql`, with policy in `database/README.md` |
| **Ops board refresh** | `backend/routes/ops_cron.py` canonical `/api/ops/trigger/board-refresh` and `/api/ops/trigger/board-refresh/async` handlers; `backend/services/scheduler_runtime.py`, `backend/services/ops_runtime.py`, and `backend/services/scan_runtime.py` scheduled board-drop helpers/status payloads; `frontend/src/lib/server/bridge-route-impl.ts`, `frontend/src/app/api/cron/trigger-backend/route.ts`, and `frontend/src/app/admin/ops/OpsDashboard.tsx` |

Reference-only legacy fences:

- `database/schema.sql` is a legacy snapshot, not the current schema owner.
- `backend/sql/` is legacy/manual SQL reference, not deploy parity or bootstrap history.
- Scheduler runtime ownership lives in `backend/services/scheduler_runtime.py`; stale scheduler service copies were removed.
- Paper-autolog runtime ownership lives in `backend/services/paper_autolog_runner.py` plus `backend/services/paper_autolog_flow.py` and `backend/services/paper_autolog_utils.py`.

---

## API Layout

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/ready` | Readiness check (env, DB, scheduler freshness) |
| GET | `/bets` | List bets (filters: sport, sportsbook, result) |
| GET | `/bets/live` | Compact live snapshots for active pending bets |
| POST | `/bets` | Create bet |
| GET | `/bets/{id}` | Get bet |
| PATCH | `/bets/{id}` | Update bet |
| PATCH | `/bets/{id}/result` | Quick result update |
| DELETE | `/bets/{id}` | Delete bet |
| GET | `/summary` | Dashboard stats |
| GET | `/settings` | User settings |
| PATCH | `/settings` | Update settings |
| GET | `/onboarding/state` | Canonical onboarding state |
| POST | `/onboarding/events` | Onboarding transition event (`complete_step`, `dismiss_step`, `reset`) |
| GET | `/calculate-ev` | EV preview (no save) |
| POST | `/transactions` | Create transaction |
| GET | `/transactions` | List transactions |
| DELETE | `/transactions/{id}` | Delete transaction |
| GET | `/balances` | Per-sportsbook balances |
| GET | `/api/scan-bets` | +EV scan (single sport) |
| GET | `/api/scan-markets` | Full market scan (all sports, cached) |
| GET | `/api/scan-latest` | Latest cached scan snapshot by surface |
| GET | `/board/latest` | Home board snapshot |
| GET | `/board/latest/surface` | Surface-specific board snapshot |
| GET | `/board/latest/player-props/opportunities` | Paginated player-props opportunities view |
| GET | `/board/latest/player-props/browse` | Paginated player-props browse view |
| GET | `/board/latest/player-props/pickem` | Paginated player-props pick'em view |
| GET | `/board/latest/player-props/detail` | Player prop detail payload used by action enrichers |
| GET | `/board/latest/promos` | Promo-ranked board payload |
| POST | `/board/refresh` | Ops-refresh board snapshot (allowlisted) |
| GET | `/parlay-slips` | List parlay slips |
| POST | `/parlay-slips` | Create parlay slip |
| PATCH | `/parlay-slips/{slip_id}` | Update parlay slip |
| DELETE | `/parlay-slips/{slip_id}` | Delete parlay slip |
| POST | `/parlay-slips/{slip_id}/log` | Log parlay slip into bets |
| POST | `/beta/access/grant` | Grant trusted-beta access by invite code |
| POST | `/api/ops/trigger/board-refresh` | Operator-triggered board/cache refresh + debug/heartbeat notifications |
| POST | `/api/ops/trigger/auto-settle` | Operator-triggered auto-settle run |
| POST | `/api/ops/trigger/test-discord` | Test Discord message |
| POST | `/api/ops/trigger/test-discord-alert` | Test alert-style Discord payloads on the debug route |
| GET | `/api/ops/status` | Protected operator status payload |

---

## Key Logic Locations

| Concern | Location |
|---------|----------|
| **EV calculations** | `backend/calculations.py` — `calculate_ev`, `american_to_decimal`, `kelly_fraction`, `calculate_real_profit`, `calculate_hold_from_odds` |
| **Bet CRUD + response building** | `backend/routes/bet_routes.py` + `backend/services/bet_crud.py` — handlers, `build_bet_response`, `get_user_settings`, CRUD implementations |
| **Summary and balances** | `backend/routes/dashboard_routes.py` + `backend/services/summary_stats.py` + `backend/services/balance_stats.py` |
| **Router ownership** | `backend/routes/*.py` — APIRouter endpoint registration by domain |
| **Shared dependencies** | `backend/dependencies.py` — current-user, scan-rate-limit, ops-token checks |
| **Odds / scanner** | `backend/services/odds_api.py` — `fetch_odds`, `devig_pinnacle`, `calculate_edge`, `scan_for_ev`, `scan_all_sides`, `get_cached_or_scan` |
| **Live bet snapshots** | `backend/services/bet_live_tracking.py` + `backend/services/espn_live.py` — pending-bet candidate matching, provider lookup, and compact live score/stat payloads |
| **Odds API activity** | `backend/services/odds_api.py` — `_append_odds_api_activity`, `get_odds_api_activity_snapshot` |
| **Automation/scheduler health** | `backend/services/scheduler_runtime.py` + `backend/services/ops_runtime.py` + `backend/routes/health_routes.py` - live scheduler jobs, heartbeats, readiness freshness, ops status |
| **Auth** | `backend/auth.py` — `get_current_user`; `frontend/src/lib/auth-context.tsx`; `frontend/src/middleware.ts` |
| **Frontend API** | `frontend/src/lib/api.ts` — `fetchAPI`, all API wrappers |
| **React Query hooks** | `frontend/src/lib/hooks.ts` — `useBets`, `useCreateBet`, `useSummary`, etc. |
| **Kelly settings** | `frontend/src/lib/kelly-context.tsx` — bankroll, multiplier, backend-backed sync, local cache |
| **Theme settings** | `frontend/src/lib/theme-context.tsx` + `frontend/src/lib/theme.ts` — local bootstrap + server-backed theme persistence |
| **Scanner UI** | `frontend/src/app/scanner/[surface]/page.tsx` + `frontend/src/app/scanner/ScannerSurfacePage.tsx` — surface routing, lens ranking, props modes, null-state handling, Log Bet flow |
| **Scanner result filters** | `frontend/src/app/scanner/components/ScannerResultFilters.tsx` + `frontend/src/lib/scanner-filters.ts` |
| **Parlay builder** | `frontend/src/app/parlay/page.tsx` + `frontend/src/lib/parlay-utils.ts` — local cart review, fair-pricing preview, Kelly auto-sizing, tracker handoff |
| **Ops dashboard UI** | `frontend/src/app/admin/ops/OpsDashboard.tsx` — scheduler-first health + odds activity card |
| **Protected ops bridge** | `frontend/src/app/api/ops/status/route.ts` + `frontend/src/lib/server/admin-access.ts` |
| **Log Bet form** | `frontend/src/components/LogBetDrawer.tsx` — form, EV preview, vig handling |
| **Types** | `frontend/src/lib/types.ts` — mirrors backend Pydantic models |

---

## Conventions

### Naming

- **Files**: PascalCase for components (`LogBetDrawer.tsx`), kebab-case for lib (`auth-context.tsx`)
- **Components**: PascalCase
- **Hooks**: `use` prefix (`useBets`, `useAuth`)
- **API functions**: camelCase (`getBets`, `createBet`)
- **Backend**: snake_case for Python

### File Layout

- **Frontend**: `app/` for routes, `components/` for UI, `lib/` for shared logic
- **Backend**: Flat structure; `services/` for external integrations
- **Types**: Centralized in `frontend/src/lib/types.ts` to match backend models

### Styling

- Tailwind utility classes
- CSS variables in `globals.css` (e.g. `--background`, `--profit`, `--loss`)
- Sportsbook colors in `tailwind.config.js` (draftkings, fanduel, betmgm, etc.)
- “Vintage field notebook” theme (warm neutrals, paper texture)

### Coding Style

- TypeScript for frontend
- Pydantic for backend schemas
- React Query for server state
- Context for auth and Kelly settings

---

## Important Decisions

### Auth & Database

- **Service role key**: Backend uses `SUPABASE_SERVICE_ROLE_KEY`; RLS protects direct anon access.
- **JWT validation**: `supabase.auth.get_user(token)` in `auth.py`.
- **Retries**: `retry_supabase` in `backend/services/runtime_support.py` for transient Supabase/PostgREST transport errors.

### Odds Integration

- **The Odds API** for live odds.
- **Pinnacle** as sharp book; de-vig via multiplicative method in `devig_pinnacle`.
- **Target books**: DraftKings, FanDuel, BetMGM, Caesars, ESPN Bet.
- **Caching**: 5-minute TTL per sport in `get_cached_or_scan`.
- **Rate limiting**: 12 scans per 15 minutes per user (`require_scan_rate_limit`).
- **Dev mode**: `ENVIRONMENT=development` limits full scan to NBA to save API quota.

### Operational Hardening

- **Scheduler-first posture**: readiness and operator dashboards evaluate scheduler health/freshness first.
- **Cron fallback paths**: external schedulers can trigger board-refresh/settle safely through token-protected cron endpoints.
- **Operator endpoint protection**: backend `/api/ops/status` is protected by `X-Ops-Token`; frontend exposes data only through allowlisted, authenticated bridge routes.
- **Observability**: odds/scores calls are tracked in-memory with bounded recent history and one-hour summary counters.

### EV & Promo Logic

- **Promo types**: `standard`, `bonus_bet`, `no_sweat`, `promo_qualifier`, `boost_30`, `boost_50`, `boost_100`, `boost_custom`.
- **Vig**: From opposing odds when available; otherwise `DEFAULT_VIG = 0.045`.
- **K-factor**: User setting (default 0.78) for no-sweat EV conversion.

### Settings And Personalization

- **Theme preference**: persisted in `settings.theme_preference` and synced in `theme-context` so signed-in users keep light/dark preference across devices.
- **Onboarding state**: transitions are managed through `/onboarding/events`; direct blob updates are intentionally rejected in the settings patch route.

### Scanner UX

- **Straight-bet lenses**: Standard EV, Profit Boost, Bonus Bet, Qualifier.
- **Player props modes**: Sportsbooks and Pick'em behave as separate props views rather than promo lenses.
- **Client-side lens math**: Frontend applies promo-specific EV on top of raw scan data.
- **Kelly**: Recommended bet size from `base_kelly_fraction x kellyMultiplier x bankroll`, with scanner cards and the parlay builder using stealth-rounded stake suggestions.

---

## Environment Variables

### Backend (`.env`)

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (bypasses RLS) |
| `ODDS_API_KEY` | The Odds API key |
| `ENVIRONMENT` | `development` (limit scans) or `production` |
| `APP_ROLE` | Runtime role (`api` or `scheduler`) used by entrypoint orchestration and readiness behavior |
| `ENABLE_SCHEDULER` | `1` to run APScheduler jobs in this process; use `0` for `APP_ROLE=api` and `1` for `APP_ROLE=scheduler` in split-role deploys |
| `TESTING` | `1` disables scheduler startup for tests |
| `TEST_SUPABASE_URL` / `TEST_SUPABASE_SERVICE_ROLE_KEY` | Dedicated Supabase project for live integration tests |
| `ALLOW_PROD_TESTS` | Explicit one-off override to allow `TESTING=1` against production Supabase |
| `READINESS_DB_TIMEOUT_SECONDS` | Optional `/ready` DB probe timeout (`2.5` default) |
| `CRON_TOKEN` | Shared secret for backend cron/ops protected endpoints |
| `ANALYTICS_TEST_EMAILS` | Optional comma-separated emails excluded from default beta analytics as test accounts |
| `LIVE_TRACKING_ENABLED` | Toggle for `/bets/live` snapshots (`1` enabled by default) |
| `LIVE_TRACKING_PROVIDER_ORDER` | Optional provider priority list for live tracking lookups (default MVP order: `espn,mlb,api_sports,odds_scores`) |
| `AUTO_SETTLE_SCORE_SOURCE` | Auto-settle score source (`provider_first` by default; `odds_api` restores legacy Odds API score gating) |
| `AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS` | `1` keeps Odds API `/scores` as fallback when provider finals are unavailable or unsupported |
| `AUTO_SETTLE_PROVIDER_FINALITY_DELAY_MINUTES` | Minutes to wait after provider finality before auto-settle uses the final score (`15` default) |
| `DISCORD_ALERT_WEBHOOK_URL` | Optional dedicated webhook for scheduled board-drop alerts |
| `DISCORD_DEBUG_WEBHOOK_URL` | Optional dedicated webhook for ops, manual refresh, test, and heartbeat messages |
| `SCHEDULED_BOARD_DROP_ALERT_GRACE_MINUTES` | Optional freshness window for scheduled board-drop alert delivery (`30` by default) |
| `REDIS_URL` | Optional shared state backend for rate-limit/cache coordination |

### Frontend (`.env.local`)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Browser API base (`http://localhost:8000` locally, `/api/backend` on Vercel) |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key |
| `BACKEND_BASE_URL` | Hetzner backend origin used by server-side bridge/proxy routes |
| `CRON_SECRET` | Authorization secret for frontend cron bridge endpoints |
| `CRON_TOKEN` | Optional dedicated backend cron token for forwarded requests |
| `CRON_BACKEND_TIMEOUT_MS` | Optional timeout for frontend cron bridge backend trigger calls (`9000` default) |
| `OPS_ADMIN_EMAILS` | Comma-separated allowlist for `/admin/ops` and `/api/ops/status` |
| `BACKEND_PROXY_TIMEOUT_MS` | Optional timeout for `/api/backend/*` bridge calls (default `15000`) |
| `OPS_BRIDGE_TIMEOUT_MS` | Optional timeout for `/api/ops/status` frontend bridge calls (default `15000`) |
| `ADMIN_SCAN_BRIDGE_TIMEOUT_MS` | Optional timeout for `/api/admin/refresh-markets` bridge calls (default `180000`; falls back to `ADMIN_BRIDGE_TIMEOUT_MS`) |
| `ADMIN_BRIDGE_TIMEOUT_MS` | Optional timeout for admin trigger bridges (default `20000`) |

---

## See Also

- **README.md** — Setup instructions, EV formulas, deployment
- **docs/testing.md** — Testing strategy, what’s automated vs manual, and local commands
- **database/README.md** — Canonical database workflow and migration policy
- **database/migration_001_multi_tenant.sql** — Start of the multi-tenant schema history
