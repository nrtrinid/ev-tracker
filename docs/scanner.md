# Scanner: End-to-End Pipeline

This document describes how the scanner works from button press to displayed result.

---

## Architecture Overview

```
User taps "Full Scan"
        │
        ▼
frontend/src/app/scanner/page.tsx
        → React Query load latest persisted scan payload (staleTime: 1 min)
        │
        ▼
GET /api/scan-markets  (FastAPI)
  → Rate limit check (12 req / 15 min / user)
  → Auth: Supabase JWT required
        │
        ▼
For each sport in SUPPORTED_SPORTS:
  get_cached_or_scan(sport)
  → Hit cache (5-min TTL, asyncio.Lock per sport)
  → OR: fetch_odds() → The Odds API /v4/sports/{sport}/odds
        │
        ▼
scan_all_sides(sport)
  → devig_pinnacle() per event
  → calculate_edge() per side × target book
  → Append all sides (regardless of EV sign)
        │
        ▼
  → Record compact Odds API activity event (source, status, cache-hit/live)
          │
          ▼
API response: { sides[], events_fetched, events_with_both_books, scanned_at }
        │
        ▼
frontend: lens ranking + result filters (client-side)
        → Rank per lens (Standard EV / Profit Boost / Bonus Bet / Qualifier)
        → Apply result filters (Search / Time / Edge / More)
        → Distinguish backend-empty vs filter-empty null states
        → Display top 10 (load more in batches)
```

---

## Backend: `GET /api/scan-markets`

**Route file:** `backend/routes/scan_routes.py`

**Handler implementation:** `backend/main.py`

**Auth:** Requires a valid Supabase JWT in the `Authorization: Bearer` header.

**Rate limit:** 12 requests per 15 minutes per user.

Rate-limit dependency is centralized in `backend/dependencies.py` and can use shared state when `REDIS_URL` is configured.

**Request parameters:**
- `sport` (optional): If provided, scans only that sport. If omitted, scans all supported sports.

**Dev mode safeguard:** If `ENVIRONMENT=development`, a full scan (no `sport` param) only fetches `basketball_nba`. This protects the 500-request/month free tier during local development. Set `ENVIRONMENT=production` to scan all sports.

**Source tagging:** Scanner calls are tagged by source (`manual_scan`, `scheduled_scan`, `cron_scan`) and propagated into Odds API activity telemetry so operator dashboards can attribute traffic correctly.

**Supported sports:**
```
basketball_nba, basketball_ncaab
```

Sports that are out of season return a 404 from The Odds API. The scanner catches these silently and continues — they don't fail the entire scan.

---

## Server-Side Cache

**File:** `backend/services/odds_api.py`

Each sport has its own in-memory cache entry (`_cache: dict[str, dict]`) and its own `asyncio.Lock` (`_locks: dict[str, asyncio.Lock]`).

**TTL:** 5 minutes (`CACHE_TTL_SECONDS = 300`).

**Behavior:**
- First request for a sport after cache expiry → hits The Odds API, costs 1 token, stores result.
- All subsequent requests within 5 minutes → served from cache, cost 0 tokens.
- With 4 supported sports and a 5-min TTL, a worst-case full scan costs 4 tokens. In practice, with multiple users, each sport's cache is shared, so 10 users scanning within 5 minutes costs the same as 1.

**Thread safety:** `asyncio.Lock` per sport prevents duplicate simultaneous API calls (e.g., two users hitting "scan" at the same time for the same sport). Only one request goes through; the other waits and receives the cached result.

**Observability note:** Cache hits still create a lightweight activity record (`cache_hit=true`, `outbound_call_made=false`) so the operator console can distinguish user traffic from actual outbound API calls.

---

## Odds Fetching: `fetch_odds()`

**File:** `backend/services/odds_api.py`

Calls: `GET https://api.the-odds-api.com/v4/sports/{sport}/odds`

This request path also records compact activity metadata in-memory (bounded ring buffer) for `/api/ops/status`.

---

## Ops Observability for Scans

`GET /api/ops/status` includes `ops.odds_api_activity` with:

- `summary.calls_last_hour`
- `summary.errors_last_hour`
- `summary.last_success_at`
- `summary.last_error_at`
- `recent_calls[]` with timestamp/source/endpoint/sport/cache_hit/outbound_call_made/status/duration/error fields

Notes:

- Recent calls are bounded (`max 50` in snapshot output).
- Events are sanitized by design (no raw payload bodies, no secrets).
- UI includes fallback derivation from scan snapshots if the dedicated activity block is unavailable.

**Parameters:**
```
regions=us,us2
markets=h2h
oddsFormat=american
bookmakers=pinnacle,draftkings,fanduel,betmgm,williamhill_us,espnbet
```

All target books are fetched in a single API call per sport. There's no additional token cost for scanning 5 books vs. 1.

The response includes `x-requests-remaining` in the headers, which is surfaced to the frontend as `api_requests_remaining`.

---

## De-Vig and Edge: `scan_all_sides()`

For every event:

1. Extract Pinnacle's home/away odds.
2. De-vig Pinnacle to get true probabilities (supports both 2-way and 3-way H2H when present).
3. For each of the 5 target books:
   - Extract that book's home/away odds.
   - Call `calculate_edge(true_prob, book_odds)` for each side (and include Draw/Tie when present).
   - Append both sides to `all_sides[]`, regardless of whether EV is positive or negative.
4. Include `base_kelly_fraction`, `sportsbook`, `book_decimal`, `ev_percentage`, `true_prob` on each side.

Unlike the older `scan_for_ev()`, this function returns **all sides** (including negative EV). The frontend applies promo-specific lens math to decide what's relevant. A side that's −2% standard EV might be the right pick for a qualifier.

---

## Frontend: Ranking And Result Filters

**Page file:** `frontend/src/app/scanner/page.tsx`

**Filter component:** `frontend/src/app/scanner/components/ScannerResultFilters.tsx`

**Filter utilities:** `frontend/src/lib/scanner-filters.ts`

The scanner pipeline is now split into two client-side stages with no extra backend fetch:

1. Lens ranking stage (`fullResults`): selected books, then lens-specific ranking/sorting.
2. Result filter stage (`filteredResults`): Search, Time presets, Standard-only Edge threshold, and More controls (Hide Longshots, Hide Already Logged, risk presets).

When result count is zero, the page distinguishes:

- **backend_empty**: source data has no lens results.
- **filter_empty**: source has lens results, but active filters removed all visible rows.

`hideAlreadyLogged` is persisted via localStorage (`scanner_hide_already_logged`).

```ts
// Stage 1: rank by active lens (book-filtered source)
// Stage 2: apply result filters client-side
const filtered = applyScannerResultFilters({
  sides: fullResults,
  activeLens,
  filters,
  longshotMaxAmerican: 500,
});

const visible = filtered.slice(0, visibleCount);
```

See [promos.md](./promos.md) for the mathematical rationale behind each lens.

---

## Scan → Log Workflow

1. **Scan** — hit Full Scan, review the top results.
2. **Log** — tap "Log Bet" on any result. The drawer pre-fills: sportsbook, event, American odds, Pinnacle odds, sport, and promo type.
3. **Place** — go to the book and place the bet. You're now logged before placing, creating a clean record.
4. **Settle** — come back after the game and mark win/loss. The system calculates your actual P&L vs. expected EV.

Front-end fetch staleness (1 minute) and server-side cache freshness (5 minutes) are intentionally decoupled:

- Frontend can revalidate the latest persisted payload frequently.
- Backend still protects The Odds API with per-sport TTL caching.
