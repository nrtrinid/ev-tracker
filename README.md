# EV Tracker

A modern web app for tracking sports betting Expected Value (EV) from sportsbook promos.

## Tech Stack

- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS, TanStack Query
- **Backend**: FastAPI (Python), Pydantic
- **Database**: PostgreSQL via Supabase
- **Deployment**: Vercel (frontend) + Railway (backend)

## Project Structure

```
ev-tracker/
├── backend/           # FastAPI Python backend
│   ├── main.py        # API routes
│   ├── models.py      # Pydantic schemas
│   ├── calculations.py # EV math
│   └── database.py    # Supabase connection
├── frontend/          # Next.js React frontend
│   └── src/
│       ├── app/       # Next.js app router
│       ├── components/ # React components
│       └── lib/       # Utilities, API client, hooks
└── database/
    └── schema.sql     # PostgreSQL schema
```

## Setup Instructions

### 1. Database Setup (Supabase)

1. Go to your Supabase project dashboard
2. Open **SQL Editor** → **New Query**
3. Paste the contents of `database/schema.sql`
4. Click **Run**

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
copy .env.example .env   # Windows
# cp .env.example .env   # Mac/Linux

# Edit .env with your Supabase credentials
```

Edit `backend/.env`:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
```

Run the backend:
```bash
python main.py
```

Backend will be at http://localhost:8000

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Create .env.local
copy .env.example .env.local   # Windows
# cp .env.example .env.local   # Mac/Linux
```

Run the frontend:
```bash
npm run dev
```

Frontend will be at http://localhost:3000

## EV Formulas

### Bonus Bets
```
EV = stake × (1 - 1/decimal_odds)
```
You're not risking real money, just potential winnings.

### No-Sweat Bets
```
EV = stake × K × (1 - 1/decimal_odds)
```
Where K ≈ 0.78 (conversion factor for bonus bet refund if you lose).

### Percentage Boosts (30%, 50%, 100%)
```
EV = (stake / decimal_odds) × min(boost% × (decimal_odds - 1), winnings_cap / stake)
```
The boost only provides value proportional to win probability.

### Odds Conversion
```
American to Decimal:
  if odds ≥ 100: decimal = 1 + (odds / 100)
  if odds < 0:   decimal = 1 + (100 / |odds|)
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /health | Health check |
| GET | /bets | List all bets (with filters) |
| POST | /bets | Create new bet |
| GET | /bets/{id} | Get single bet |
| PATCH | /bets/{id} | Update bet |
| PATCH | /bets/{id}/result | Quick result update |
| DELETE | /bets/{id} | Delete bet |
| GET | /summary | Dashboard stats |
| GET | /settings | Get settings |
| PATCH | /settings | Update settings |
| GET | /calculate-ev | Preview EV calculation |

## Development

Both servers need to be running:

**Terminal 1 (Backend):**
```bash
cd backend
venv\Scripts\activate  # Windows
python main.py
```

**Terminal 2 (Frontend):**
```bash
cd frontend
npm run dev
```

## Future Enhancements (V2)

- [ ] DFS/PrizePicks mode
- [ ] The Odds API integration
- [ ] Bet recommendation engine
- [ ] Multi-user authentication
- [ ] Export to CSV/PDF
- [ ] Dark mode
