# EV Betting Tracker

**Find +EV bets, log them, and track real P&L across every sportsbook.**

EV Betting Tracker is a multi-tenant SaaS application for sharp sports bettors. It uses live odds from [The Odds API](https://the-odds-api.com) and Pinnacle as a sharp-line reference to surface positive expected value (+EV) opportunities across DraftKings, FanDuel, BetMGM, Caesars, and ESPN Bet — then gives you the math to size them.

> **Status:** Active development. Local setup fully functional. Hosted demo coming soon.

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

---

## Screenshot

> _UI screenshot coming soon. Run locally to see the full interface._

---

## Feature Set

### Scanner (Promo Decision Engine)
- Full scan across NBA, NFL, MLB, NHL, MMA, MLS, and more
- **Standard EV** lens: top +EV moneylines sorted by edge
- **Profit Boost** lens: recalculates EV after applying a 30% or 50% profit multiplier
- **Bonus Bet** lens: sorts by retention rate (`true_prob × decimal_odds`) to maximize free-bet conversion
- **Qualifier** lens: filters odds between −250 and +150, minimizing expected qualifying loss
- Per-book badges (DK, FD, MGM, CZR, ESPN)
- "Fair Odds" line shows the de-vigged Pinnacle line for every result
- One-tap pre-fill into the log drawer

### Bet Logging
- Log bets with full promo context (standard, boost %, bonus bet, no-sweat, qualifier)
- Supports winnings cap for boosted bets
- Settle bets (win/loss/push/void) and see real P&L vs. expected

### Dashboard & Analytics
- Total P&L, EV earned, edge vs. actual
- Balance tracking per sportsbook
- EV per dollar by promo type

### Settings
- Configure Kelly multiplier (10%, 25%, 50%, full)
- Set bankroll: use computed (sum of logged balances) or override manually
- Persisted to `localStorage`

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Browser                          │
│   Next.js 14 (App Router)  ·  React Query  ·  Tailwind │
│   /scanner  /dashboard  /bets  /settings             │
└───────────────────┬─────────────────────────────────┘
                    │  HTTPS / JSON
┌───────────────────▼─────────────────────────────────┐
│                 FastAPI (Python)                      │
│   /api/scan-markets   /api/bets   /api/balances      │
│   Auth via Supabase JWT  ·  Rate limiting  ·  Cache  │
└───────────┬──────────────────────┬───────────────────┘
            │                      │
┌───────────▼──────┐   ┌──────────▼──────────────────┐
│  Supabase Postgres│   │      The Odds API            │
│  bets · balances  │   │  Live h2h odds — Pinnacle +  │
│  users · RLS      │   │  DK, FD, MGM, CZR, ESPN Bet  │
└───────────────────┘   └──────────────────────────────┘
```

**Key files:**
- `backend/services/odds_api.py` — fetch, de-vig, edge calculation, cache
- `backend/calculations.py` — EV math, Kelly criterion, odds conversion
- `backend/main.py` — FastAPI endpoints, auth, rate limiting
- `frontend/src/app/scanner/page.tsx` — scanner UI, lens logic
- `frontend/src/lib/kelly-context.tsx` — global Kelly/bankroll state

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
```

```bash
python main.py
# → http://localhost:8000
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
```

```bash
npm run dev
# → http://localhost:3000
```

---

## Docs

| Document | What it covers |
|---|---|
| [docs/methodology.md](./docs/methodology.md) | How Pinnacle lines are de-vigged and EV is calculated |
| [docs/scanner.md](./docs/scanner.md) | End-to-end scanner pipeline |
| [docs/promos.md](./docs/promos.md) | Math behind each promo lens |
| [PROJECT.md](./PROJECT.md) | Architecture, conventions, key decisions |

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, shadcn/ui, React Query |
| Backend | FastAPI, Python 3.11+, Pydantic, httpx |
| Database | Supabase (PostgreSQL + Auth + RLS) |
| Odds data | The Odds API v4 |

---

## Security

See [SECURITY.md](./SECURITY.md) for our vulnerability disclosure policy.

---

## License

[MIT](./LICENSE)
