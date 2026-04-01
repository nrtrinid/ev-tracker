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
3. **EV**: `calculate_ev` in `calculations.py` → `build_bet_response` in `main.py` → frontend.
4. **Scanner**: Frontend `scanMarkets()` → `/api/scan-markets` → `services/odds_api.get_cached_or_scan` → The Odds API → de-vig Pinnacle → compare to target books.
5. **Operator status**: `/admin/ops` → protected frontend bridge `/api/ops/status` → backend `/api/ops/status` (server-side ops token).
6. **Automation fallback**: scheduler or external trigger → `/api/ops/trigger/scan` and `/api/ops/trigger/auto-settle`.

### Multi-Tenancy

- `user_id` on `bets`, `transactions`, `settings`.
- RLS policies enforce per-user access.
- Migration script: `database/migration_001_multi_tenant.sql`.

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

- **The Odds API** (`api.the-odds-api.com/v4`) — live odds for +EV scanning.

---

## Project Structure

```
ev-betting-tracker/
├── backend/                 # FastAPI Python backend
│   ├── main.py              # App, routes, CORS, rate limiting
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
│       ├── components/      # UI (Dashboard, BetList, LogBetDrawer, EditBetModal, TopNav, SmartOddsInput, ui/)
│       ├── lib/             # api.ts, auth-context, hooks, kelly-context, supabase, types, utils
│       └── middleware.ts    # Auth redirects
├── database/
│   └── migration_001_multi_tenant.sql
└── PROJECT.md               # This file
```

---

## API Layout

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/ready` | Readiness check (env, DB, scheduler freshness) |
| GET | `/bets` | List bets (filters: sport, sportsbook, result) |
| POST | `/bets` | Create bet |
| GET | `/bets/{id}` | Get bet |
| PATCH | `/bets/{id}` | Update bet |
| PATCH | `/bets/{id}/result` | Quick result update |
| DELETE | `/bets/{id}` | Delete bet |
| GET | `/summary` | Dashboard stats |
| GET | `/settings` | User settings |
| PATCH | `/settings` | Update settings |
| GET | `/calculate-ev` | EV preview (no save) |
| POST | `/transactions` | Create transaction |
| GET | `/transactions` | List transactions |
| DELETE | `/transactions/{id}` | Delete transaction |
| GET | `/balances` | Per-sportsbook balances |
| GET | `/api/scan-bets` | +EV scan (single sport) |
| GET | `/api/scan-markets` | Full market scan (all sports, cached) |
| POST | `/api/ops/trigger/scan` | Operator-triggered cache warm + alert scheduling |
| POST | `/api/ops/trigger/auto-settle` | Operator-triggered auto-settle run |
| POST | `/api/ops/trigger/test-discord` | Test Discord message |
| GET | `/api/ops/status` | Protected operator status payload |

---

## Key Logic Locations

| Concern | Location |
|---------|----------|
| **EV calculations** | `backend/calculations.py` — `calculate_ev`, `american_to_decimal`, `kelly_fraction`, `calculate_real_profit`, `calculate_hold_from_odds` |
| **Bet CRUD + response building** | `backend/main.py` — `build_bet_response`, `get_user_settings`, handler implementations |
| **Router ownership** | `backend/routes/*.py` — APIRouter endpoint registration by domain |
| **Shared dependencies** | `backend/dependencies.py` — current-user, scan-rate-limit, ops-token checks |
| **Odds / scanner** | `backend/services/odds_api.py` — `fetch_odds`, `devig_pinnacle`, `calculate_edge`, `scan_for_ev`, `scan_all_sides`, `get_cached_or_scan` |
| **Odds API activity** | `backend/services/odds_api.py` — `_append_odds_api_activity`, `get_odds_api_activity_snapshot` |
| **Automation/scheduler health** | `backend/main.py` — scheduler jobs, heartbeats, readiness freshness, ops status |
| **Auth** | `backend/auth.py` — `get_current_user`; `frontend/src/lib/auth-context.tsx`; `frontend/src/middleware.ts` |
| **Frontend API** | `frontend/src/lib/api.ts` — `fetchAPI`, all API wrappers |
| **React Query hooks** | `frontend/src/lib/hooks.ts` — `useBets`, `useCreateBet`, `useSummary`, etc. |
| **Kelly settings** | `frontend/src/lib/kelly-context.tsx` — bankroll, multiplier, backend-backed sync, local cache |
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
- **Retries**: `_retry_supabase` in `main.py` for transient `RemoteProtocolError`.

### Odds Integration

- **The Odds API** for live odds.
- **Pinnacle** as sharp book; de-vig via multiplicative method in `devig_pinnacle`.
- **Target books**: DraftKings, FanDuel, BetMGM, Caesars, ESPN Bet.
- **Caching**: 5-minute TTL per sport in `get_cached_or_scan`.
- **Rate limiting**: 12 scans per 15 minutes per user (`require_scan_rate_limit`).
- **Dev mode**: `ENVIRONMENT=development` limits full scan to NBA to save API quota.

### Operational Hardening

- **Scheduler-first posture**: readiness and operator dashboards evaluate scheduler health/freshness first.
- **Cron fallback paths**: external schedulers can trigger scan/settle safely through token-protected cron endpoints.
- **Operator endpoint protection**: backend `/api/ops/status` is protected by `X-Ops-Token`; frontend exposes data only through allowlisted, authenticated bridge routes.
- **Observability**: odds/scores calls are tracked in-memory with bounded recent history and one-hour summary counters.

### EV & Promo Logic

- **Promo types**: `standard`, `bonus_bet`, `no_sweat`, `promo_qualifier`, `boost_30`, `boost_50`, `boost_100`, `boost_custom`.
- **Vig**: From opposing odds when available; otherwise `DEFAULT_VIG = 0.045`.
- **K-factor**: User setting (default 0.78) for no-sweat EV conversion.

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
| `ENABLE_SCHEDULER` | `1` to run APScheduler jobs in this process |
| `TESTING` | `1` disables scheduler startup for tests |
| `CRON_TOKEN` | Shared secret for backend cron/ops protected endpoints |
| `DISCORD_WEBHOOK_URL` | Optional webhook for scan/settle alerts |
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
| `OPS_ADMIN_EMAILS` | Comma-separated allowlist for `/admin/ops` and `/api/ops/status` |

---

## See Also

- **README.md** — Setup instructions, EV formulas, deployment
- **docs/testing.md** — Testing strategy, what’s automated vs manual, and local commands
- **database/migration_001_multi_tenant.sql** — Multi-tenant schema and RLS policies
