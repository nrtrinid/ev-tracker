# EV Betting Tracker

Track sports betting Expected Value from promos (bonus bets, no-sweat, boosts). Log bets, see EV per dollar, run +EV scans via The Odds API.

**Stack:** Next.js + FastAPI + Supabase (PostgreSQL + Auth)

**Run locally:**
```bash
# Backend
cd backend && pip install -r requirements.txt && copy .env.example .env
# Edit .env with Supabase + Odds API keys, then:
python main.py

# Frontend
cd frontend && npm install && copy .env.example .env.local
npm run dev
```

→ **PROJECT.md** for architecture, conventions, key logic, and setup details.
