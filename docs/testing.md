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

These cover:

- scheduler heartbeat and readiness behavior
- protected ops payloads
- Discord routing and failure diagnostics
- scanner / ops contract-shape drift

#### Backend integration tests

Prereqs:

- `backend/.env` has `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- a real test auth user exists
- `TESTING=1` disables scheduler startup during tests

Windows PowerShell:

- `$env:TESTING="1"; $env:TEST_USER_ID="<uuid>"; pytest tests/test_api.py -v`
- `$env:TESTING="1"; $env:TEST_USER_ID="<uuid>"; pytest -m integration -v`

macOS/Linux:

- `TESTING=1 TEST_USER_ID=<uuid> pytest tests/test_api.py -v`
- `TESTING=1 TEST_USER_ID=<uuid> pytest -m integration -v`

#### Frontend build / type checks

From `frontend/`:

- `npm run build`
- `npx tsc --noEmit`

#### Frontend Playwright checks

From `frontend/`:

- `npm run test:e2e`
- `npm run test:ops-utils`
- `npm run test:ops-access`

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

### Trusted Beta Checklist

Before sharing `main` with testers:

- run backend unit and hardening tests
- run Discord backend tests
- run backend integration tests against a dedicated test user
- run frontend `build` and `tsc`
- run Playwright smoke tests where credentials are available
- confirm production migrations are applied through `database/migration_013_pickem_research.sql`
- confirm `backend/sql/add_v2_surface_fields.sql` is applied if needed
- trigger:
  - `POST /api/ops/trigger/test-discord`
  - `POST /api/ops/trigger/test-discord-alert`
- manually verify:
  - sign up / sign in
  - home board loads
  - promos, game lines, and player props make sense
  - a bet can be logged and settled
  - one straight bet and one player prop get watched through the next CLV close window
