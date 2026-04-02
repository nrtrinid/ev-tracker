# Scanner: End-to-End Pipeline

This document describes the manual scanner flow under `/scanner/*`. The home page daily board is a separate scheduled path that serves persisted board snapshots, but it reuses the same pricing ideas.

---

## Architecture Overview

```text
User opens /scanner/straight_bets or /scanner/player_props
        |
        v
frontend/src/app/scanner/[surface]/page.tsx
        -> ScannerSurfacePage.tsx orchestrates filters, ranking, and props modes
        |
        v
GET /api/scan-markets (FastAPI)
  -> rate limit check
  -> Supabase JWT auth
        |
        v
For each requested sport:
  get_cached_or_scan(sport)
  -> cache hit (5-minute TTL, shared per sport)
  -> or live Odds API fetch
        |
        v
scan_all_sides(sport)
  -> sharp reference extraction
  -> no-vig probability calculation
  -> per-book edge calculation across h2h / spreads / totals
        |
        v
API response: { sides[], events_fetched, events_with_both_books, scanned_at }
        |
        v
frontend ranking + filters
  -> lens ranking
  -> book/time/search/more filters
  -> null-state classification
  -> visible card list
```

---

## Backend: `GET /api/scan-markets`

**Route file:** `backend/routes/scan_routes.py`

**Handler implementation:** `backend/main.py`

**Auth:** Requires a valid Supabase JWT in the `Authorization: Bearer` header.

**Rate limit:** 12 requests per 15 minutes per user.

Rate-limit dependency is centralized in `backend/dependencies.py` and can use shared state when `REDIS_URL` is configured.

**Request parameters:**

- `sport` (optional): if provided, scans only that sport
- `surface` (optional): straight bets vs player props handling

**Dev mode safeguard:** If `ENVIRONMENT=development`, a full straight-bet scan limits itself to `basketball_nba` to protect Odds API quota.

**Supported straight-bet sports in production:**

```text
basketball_nba, basketball_ncaab, baseball_mlb
```

Out-of-season sports can return a 404 from The Odds API. The scanner handles that per sport rather than failing the full request.

---

## Server-Side Cache

**File:** `backend/services/odds_api.py`

Each sport has its own in-memory cache entry and `asyncio.Lock`.

**TTL:** 5 minutes (`CACHE_TTL_SECONDS = 300`).

**Behavior:**

- First request after expiry hits The Odds API and repopulates cache.
- Subsequent requests inside the TTL are served from cache.
- With 3 supported straight-bet sports and a 5-minute TTL, a worst-case full scan costs 3 tokens.
- Cache hits still emit lightweight activity telemetry so ops can distinguish user traffic from outbound API calls.

---

## Odds Fetching: `fetch_odds()`

**File:** `backend/services/odds_api.py`

Calls:

`GET https://api.the-odds-api.com/v4/sports/{sport}/odds`

Current straight-bet parameters:

```text
regions=us,us2
markets=h2h,spreads,totals
oddsFormat=american
bookmakers=pinnacle,draftkings,fanduel,betmgm,williamhill_us,espnbet
```

The request path records compact activity metadata for `/api/ops/status`.

---

## Straight-Bet Reference Math: `scan_all_sides()`

For every event:

1. Extract Pinnacle reference prices for `h2h`, `spreads`, and `totals`.
2. Build no-vig probabilities from the sharp two-way market.
3. For each target book:
   - compare against the same market type
   - for spreads and totals, require exact-line matches
   - append all eligible sides, even if the EV is negative
4. Include `surface`, `market_key`, `selection_key`, `selection_side`, `line_value`, `true_prob`, `book_decimal`, `ev_percentage`, and `base_kelly_fraction`.

Returning all sides is intentional. The frontend decides what is useful for standard EV, boosts, bonus bets, qualifiers, browse mode, promos, and card filtering.

---

## Frontend: Ranking And Filters

**Route entry:** `frontend/src/app/scanner/[surface]/page.tsx`

**Surface orchestration:** `frontend/src/app/scanner/ScannerSurfacePage.tsx`

**Filter component:** `frontend/src/app/scanner/components/ScannerResultFilters.tsx`

**Filter utilities:** `frontend/src/lib/scanner-filters.ts`

The scanner pipeline is split into two client-side stages:

1. Rank by active lens and selected books.
2. Apply result filters such as Search, Time, Edge, and More controls.

When result count is zero, the UI distinguishes:

- `backend_empty`: source data has no lens results
- `filter_empty`: source data exists, but active filters removed all visible rows

`hideAlreadyLogged` is persisted locally.

---

## Player Props Notes

Player props are curated differently from straight bets:

- sportsbook props use cross-book consensus rather than Pinnacle
- surfaced cards require a stronger peer-book threshold
- the props experience includes both `Sportsbooks` and `Pick'em` views

See [player-props-v2.md](./player-props-v2.md) for the props-specific runtime.

---

## Scan To Log Workflow

1. Scan a surface and review the top cards.
2. Tap `Log Bet` on a result.
3. The drawer pre-fills sportsbook, event, surface, market identity, odds, and reference context.
4. Place the bet at the book.
5. Later settle it and review P&L, analytics, and CLV when available.

Frontend fetch staleness and backend cache freshness are intentionally decoupled:

- the frontend can revalidate frequently
- the backend still protects the Odds API with per-sport TTL caching

---

## Related Board Flow

- The home page uses a scheduled daily board, not a live manual scan.
- `Promos` merges promo-ranked game lines and player props from the board.
- `Game Lines` uses the straight-bets surface and can include moneylines, spreads, and totals.
- `Player Props` uses curated sportsbook props plus the Pick'em board.
