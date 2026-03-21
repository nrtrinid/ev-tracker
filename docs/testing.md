## Testing

This project touches money-adjacent calculations (EV, profit, balances), user-facing recordkeeping (bets/transactions), and background automation (scan/settle scheduling and ops observability). The goal of testing is to prevent regressions in EV math, settlement/profit logic, scheduler behavior, protected ops routes, and critical UI flows without over-claiming maturity.

### Strategy (lean pyramid)

- **Unit (backend, fast)**: deterministic tests for the calculation engine.
- **Unit (backend, fast)**: deterministic tests for calculation and odds-activity summarization logic.
- **Integration (backend routes, Supabase-backed)**: route-level behavior against a real Supabase DB + Auth user.
- **Automation route checks (backend)**: cron/ops/scheduler status behavior with controlled fixtures.
- **Contract checks (backend/frontend)**: scanner and ops payload shape/null-state guardrails to prevent silent contract drift.
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
- `pytest tests/test_odds_api_activity.py -v`
- Or exclude integration: `pytest -m "not integration" -v`

#### Backend hardening / scheduler tests

From `backend/` with your venv activated:

- `pytest tests/test_scheduler.py -v`
- `pytest tests/test_scheduler.py tests/test_odds_api_activity.py -v`
- `pytest tests/test_scan_ops_contracts.py -v`

What these cover:

- Scheduler heartbeat/status payload behavior.
- Protected ops status response expectations.
- Odds API activity summary and recent-call sanitization.
- Scanner/ops payload contract-shape parity against golden fixtures.

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

#### Frontend scanner contract/filter helper tests

From `frontend/`:

- `npx playwright test tests/scanner-contract.spec.ts tests/scanner-filters.spec.ts`

What these cover:

- Scan payload shape guard checks (`isScanResultContractShape`).
- Null-state classification (`backend_empty` vs `filter_empty`).
- Search normalization, time presets, edge/lens behavior, and active-filter chip generation.

#### Frontend operator-access tests

These tests cover the new ops hardening layer:

- Utility behavior for allowlist normalization + fail-closed logic
- Non-admin denial for `/admin/ops` and `/api/ops/status`

From `frontend/`:

- Utility tests (no credentials required):
  - `npm run test:ops-utils`

- Non-admin denial e2e (requires a real non-admin account):
  - Windows PowerShell:
    - `$env:PLAYWRIGHT_NON_ADMIN_EMAIL="<email>"; $env:PLAYWRIGHT_NON_ADMIN_PASSWORD="<password>"; npm run test:ops-access`

Notes:

- `test:ops-access` intentionally skips if non-admin credentials are not set.
- Keep one dedicated non-admin test user to avoid false positives.

### What this suite gives you (today)

- High confidence in EV math and profit computation.
- Good confidence that core CRUD + summary-style backend routes behave correctly against a real database.
- Better confidence that automation/ops hardening paths behave correctly.
- Better confidence that scanner payload and null-state/filter semantics stay stable.
- Basic “does it still work?” coverage for a couple critical UI flows.

### Known gaps (intentionally not automated yet)

- Scanner end-to-end correctness against live odds + market mapping edge cases.
- Full time-based scheduler execution lifecycle in CI-like environments.
- Performance/load, rate-limit behavior, and broader UI regression coverage.
- Playwright in CI (requires browser/auth secrets/services; kept local for now).

### Pre-beta checklist (quick)

- Run unit tests.
- Run scheduler/odds-activity backend tests.
- Run backend scan/ops contract fixture tests.
- Run backend integration tests against a dedicated test user.
- Run frontend scanner contract/filter helper tests.
- Run Playwright smokes with a test login.
- Run `npm run test:ops-utils`.
- Run `npm run test:ops-access` with non-admin credentials.
- Manually: scan a sport in dev mode and spot-check a handful of edges/“fair odds.”
- Manually: log a bet → settle → verify summary and balances change as expected.

