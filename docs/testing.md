## Testing

This project touches money-adjacent calculations (EV, profit, balances) and user-facing recordkeeping (bets/transactions). The goal of testing here is to prevent regressions in the EV math, settlement/profit logic, core route behavior, and a couple critical UI flows—without over-claiming maturity.

### Strategy (lean pyramid)

- **Unit (backend, fast)**: deterministic tests for the calculation engine.
- **Integration (backend routes, Supabase-backed)**: route-level behavior against a real Supabase DB + Auth user.
- **Smoke (frontend, Playwright)**: a couple critical UI flows against local dev servers.
- **Manual dogfooding**: scanner realism, scheduler behavior, and UX edge cases.

### Live vs mocked

- **Mocked/overridden**:
  - Backend integration tests override `get_current_user` (no full JWT flow).
- **Live**:
  - Supabase Postgres + Auth are real in backend integration tests (writes real rows; tests clean up after themselves).
  - The Odds API is intentionally not covered by automated tests in this repo’s current scope.

### Run tests locally

#### Backend unit tests

From `backend/` with your venv activated:

- `pytest tests/test_calculations.py -v`
- Or exclude integration: `pytest -m "not integration" -v`

#### Backend integration tests (Supabase-backed)

Prereqs:

- `backend/.env` has `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- A Supabase Auth user exists for testing; set its UUID as `TEST_USER_ID`
- Run with `TESTING=1` so the scheduler is disabled during test startup

Windows PowerShell (from `backend/`):

- `$env:TESTING="1"; $env:TEST_USER_ID="<uuid>"; pytest tests/test_api.py -v`
- `$env:TESTING="1"; $env:TEST_USER_ID="<uuid>"; pytest -m integration -v`

macOS/Linux (from `backend/`):

- `TESTING=1 TEST_USER_ID=<uuid> pytest tests/test_api.py -v`
- `TESTING=1 TEST_USER_ID=<uuid> pytest -m integration -v`

Notes:

- Tests tag created records with a short `run_id` and delete created bets/transactions in teardown.
- If env vars are missing, the integration module skips with a clear message.

#### Frontend smoke tests (Playwright)

Prereqs:

- Backend running: `http://localhost:8000`
- Frontend running: `http://localhost:3000`
- A real test user email + password

From `frontend/`:

- One-time install: `npm install` and `npx playwright install`
- Run (Windows PowerShell):
  - `$env:PLAYWRIGHT_TEST_EMAIL="<email>"; $env:PLAYWRIGHT_TEST_PASSWORD="<password>"; npm run test:e2e`

### What this suite gives you (today)

- High confidence in EV math and profit computation.
- Good confidence that core CRUD + summary-style backend routes behave correctly against a real database.
- Basic “does it still work?” coverage for a couple critical UI flows.

### Known gaps (intentionally not automated yet)

- Scanner end-to-end correctness against live odds + market mapping edge cases.
- Scheduler jobs (CLV, auto-settle) and time-based behavior.
- Performance/load, rate-limit behavior, and broader UI regression coverage.
- Running integration + Playwright in CI (requires secrets + services; kept out for now).

### Pre-beta checklist (quick)

- Run unit tests.
- Run backend integration tests against a dedicated test user.
- Run Playwright smokes with a test login.
- Manually: scan a sport in dev mode and spot-check a handful of edges/“fair odds.”
- Manually: log a bet → settle → verify summary and balances change as expected.

