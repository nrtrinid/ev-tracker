# Scanner: End-to-End Pipeline

This document describes how the scanner works from button press to displayed result.

---

## Architecture Overview

```
User taps "Full Scan"
        │
        ▼
frontend/src/app/scanner/page.tsx
  → React Query refetch (staleTime: 5 min)
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
API response: { sides[], events_fetched, events_with_both_books, scanned_at }
        │
        ▼
frontend: lens filtering + sorting (useMemo)
  → Standard EV / Profit Boost / Bonus Bet / Qualifier
  → Filter by selected books
  → Display top 10
```

---

## Backend: `GET /api/scan-markets`

**File:** `backend/main.py`

**Auth:** Requires a valid Supabase JWT in the `Authorization: Bearer` header.

**Rate limit:** 12 requests per 15 minutes per user (in-memory, resets on server restart).

**Request parameters:**
- `sport` (optional): If provided, scans only that sport. If omitted, scans all supported sports.

**Dev mode safeguard:** If `ENVIRONMENT=development`, a full scan (no `sport` param) only fetches `basketball_nba`. This protects the 500-request/month free tier during local development. Set `ENVIRONMENT=production` to scan all sports.

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

---

## Odds Fetching: `fetch_odds()`

**File:** `backend/services/odds_api.py`

Calls: `GET https://api.the-odds-api.com/v4/sports/{sport}/odds`

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

## Frontend: Lens Logic

**File:** `frontend/src/app/scanner/page.tsx`

All filtering and sorting runs in a `useMemo()` that re-runs whenever `scanData`, `activeLens`, `boostPercent`, or `selectedBooks` changes. There's no re-fetch — the same scan data is re-sliced per lens.

```ts
// Standard EV
sides.filter(s => s.ev_percentage > 0)
     .sort((a, b) => b.ev_percentage - a.ev_percentage)
     .slice(0, 10)

// Profit Boost
sides.map(s => ({ ...s, _boostedEV: calculateBoostedEV(s, boostPercent) }))
     .filter(s => s._boostedEV > 0)
     .sort((a, b) => b._boostedEV - a._boostedEV)
     .slice(0, 10)

// Bonus Bet
sides.map(s => ({ ...s, _retention: (s.book_decimal - 1) * s.true_prob }))
     .sort((a, b) => b._retention - a._retention)
     .slice(0, 10)

// Qualifier
sides.filter(s => s.book_odds >= -250 && s.book_odds <= 150)
     .sort((a, b) => b.ev_percentage - a.ev_percentage)
     .slice(0, 10)
```

See [promos.md](./promos.md) for the mathematical rationale behind each lens.

---

## Scan → Log Workflow

1. **Scan** — hit Full Scan, review the top results.
2. **Log** — tap "Log Bet" on any result. The drawer pre-fills: sportsbook, event, American odds, Pinnacle odds, sport, and promo type.
3. **Place** — go to the book and place the bet. You're now logged before placing, creating a clean record.
4. **Settle** — come back after the game and mark win/loss. The system calculates your actual P&L vs. expected EV.

The 5-minute front-end `staleTime` (React Query) and the 5-minute server-side cache are intentionally aligned. If you switch away from the scanner and come back within 5 minutes, you see the same results without triggering a re-fetch or a cooldown timer reset.
