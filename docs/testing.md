## Testing

This project touches EV math, real-money-adjacent recordkeeping, background automation, and operator tooling. The goal is to prevent regressions without pretending the product is fully frozen.

### Strategy

- **Backend unit tests** for calculations and service logic
- **Backend contract / hardening tests** for scheduler, ops, Discord, and payload shape
- **Backend integration tests** against a real test Supabase project
- **Frontend build and type checks**
- **Playwright smoke tests** for critical user flows
- **Manual beta smoke** for live data, CLV, Discord routing, and deploy health

### Run Tests Locally

#### Backend unit / service tests

From `backend/` with your venv activated:

- `pytest tests/test_calculations.py -v`
- `pytest tests/test_odds_api_activity.py -v`
- `pytest tests/test_discord_alerts.py -v`
- `pytest -m "not integration" -v`

#### Backend hardening / contract tests

From `backend/`:

- `pytest tests/test_scheduler.py -v`
- `pytest tests/test_scan_ops_contracts.py -v`
- `pytest tests/test_bet_live_routes.py tests/test_bet_live_tracking_services.py -v`

These cover:

- scheduler heartbeat and readiness behavior
- protected ops payloads
- Discord routing and failure diagnostics
- scanner / ops contract-shape drift
- `/bets/live` auth + response contract behavior
- live provider normalization, unsupported-sport fallback, and compact stat snapshot shaping

Quick local readiness smoke (optional):

- PowerShell: `Invoke-WebRequest -Uri http://localhost:8000/ready`
- macOS/Linux: `curl -i http://localhost:8000/ready`

Role-aware readiness checks (split-role deployments):

- API role (`APP_ROLE=api`, `ENABLE_SCHEDULER=0`): scheduler freshness is advisory and should not fail readiness.
- Scheduler role (`APP_ROLE=scheduler`, `ENABLE_SCHEDULER=1`): stale scheduler freshness should fail readiness.

#### Backend integration tests

Prereqs:

- `TEST_SUPABASE_URL` and `TEST_SUPABASE_SERVICE_ROLE_KEY` point at a dedicated test project
- a real test auth user exists
- `TESTING=1` disables scheduler startup during tests
- the test harness refuses to initialize the known production Supabase project while `TESTING=1`; set `ALLOW_PROD_TESTS=1` only for a deliberate one-off production check

Windows PowerShell:

- `$env:TESTING="1"; $env:TEST_USER_ID="<uuid>"; pytest tests/test_api.py -v`
- `$env:TESTING="1"; $env:TEST_USER_ID="<uuid>"; pytest -m integration -v`

macOS/Linux:

- `TESTING=1 TEST_USER_ID=<uuid> pytest tests/test_api.py -v`
- `TESTING=1 TEST_USER_ID=<uuid> pytest -m integration -v`

#### Frontend build / type checks

From `frontend/`:

- `npm run build`
- `npm run typecheck`

#### Frontend Playwright checks

From `frontend/`:

- `npm run test:e2e`
- `npx playwright test tests/bet-live-state.spec.ts`
- `npm run test:ops-utils`
- `npm run test:ops-access`
- `npm run test:route-timeouts`
- `npm run test:quarantined`

The ops-access flow needs real non-admin credentials. The smoke flow needs a real login.

### What This Suite Gives You

- high confidence in math and pricing helpers
- good confidence in CRUD and summary routes
- good confidence in scheduler / ops / Discord contract behavior
- reasonable confidence that the shipped frontend still builds and the core paths still load

### Known Gaps

- live market correctness against real odds on a given slate
- broader UI regression coverage
- performance and load behavior
- CI-hosted Playwright

### Operator Pre-Release Checks

Before sharing `main` with testers:

- run backend unit and hardening tests
- verify readiness semantics in split-role mode (`api` role tolerant to stale scheduler freshness; `scheduler` role strict)
- run Discord backend tests
- run backend integration tests against a dedicated test user
- run frontend `build` and `typecheck`
- run Playwright smoke tests where credentials are available
- confirm migration parity and apply order via [database/README.md](../database/README.md)
- run production health/ops/Discord verification via [DEPLOY.md](../DEPLOY.md#discord-verification-required)
- run tester-facing launch checks via [docs/trusted-beta.md](./trusted-beta.md#launch-day-checklist)
