-- EV Tracker Database Schema
-- Run this in Supabase SQL Editor (SQL Editor > New Query > Paste > Run)

-- Create the bets table
CREATE TABLE public.bets (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    
    -- Event date (game day) - defaults to today, editable in Advanced
    event_date DATE DEFAULT CURRENT_DATE NOT NULL,
    
    -- Settlement timestamp - auto-set when result changes from pending
    settled_at TIMESTAMP WITH TIME ZONE,
    
    -- Event details
    sport TEXT NOT NULL,           -- NFL, NBA, MLB, NHL, NCAAF, NCAAB, UFC, etc.
    event TEXT NOT NULL,           -- "Lakers -5" or "Bills SGP" (the selection)
    market TEXT NOT NULL,          -- ML, Spread, Total, SGP, Prop
    sportsbook TEXT NOT NULL,      -- DraftKings, FanDuel, BetMGM, etc.
    
    -- Promo type determines EV calculation
    promo_type TEXT NOT NULL DEFAULT 'standard',
    -- Valid values: standard, bonus_bet, no_sweat, boost_30, boost_50, boost_100, boost_custom
    
    -- The numbers
    odds_american NUMERIC NOT NULL,      -- User enters American odds (-110, +150, etc.)
    stake NUMERIC NOT NULL,              -- Wager amount in dollars
    boost_percent NUMERIC,               -- For custom boost percentage (e.g., 25 for 25%)
    winnings_cap NUMERIC,                -- Max extra winnings from boost
    
    -- Optional override for edge cases (like your Slip Payout Override column)
    payout_override NUMERIC,
    
    -- Outcome
    result TEXT NOT NULL DEFAULT 'pending',
    -- Valid values: pending, win, loss, push, void
    
    -- Notes
    notes TEXT
);

-- Create indexes for common queries
CREATE INDEX idx_bets_event_date ON public.bets(event_date DESC);
CREATE INDEX idx_bets_created_at ON public.bets(created_at DESC);
CREATE INDEX idx_bets_sportsbook ON public.bets(sportsbook);
CREATE INDEX idx_bets_sport ON public.bets(sport);
CREATE INDEX idx_bets_result ON public.bets(result);

-- Enable Row Level Security (required by Supabase)
ALTER TABLE public.bets ENABLE ROW LEVEL SECURITY;

-- Create a policy that allows all access (single-user app for now)
-- In V2 with auth, you'd check auth.uid() here
CREATE POLICY "Allow all access" ON public.bets
    FOR ALL USING (true) WITH CHECK (true);

-- Optional: Create a settings table for user preferences
CREATE TABLE public.settings (
    id INTEGER PRIMARY KEY DEFAULT 1,  -- Single row for single user
    k_factor NUMERIC DEFAULT 0.78,
    default_stake NUMERIC,
    preferred_sportsbooks TEXT[] DEFAULT ARRAY['DraftKings', 'FanDuel', 'BetMGM', 'Caesars', 'ESPN Bet', 'Fanatics', 'Hard Rock', 'bet365'],
    kelly_multiplier NUMERIC DEFAULT 0.25,
    bankroll_override NUMERIC DEFAULT 1000,
    use_computed_bankroll BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now())
);

ALTER TABLE public.settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all access" ON public.settings
    FOR ALL USING (true) WITH CHECK (true);

-- Insert default settings row
INSERT INTO public.settings (id) VALUES (1);

-- Transactions table for deposit/withdrawal tracking
CREATE TABLE public.transactions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    sportsbook TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('deposit', 'withdrawal')),
    amount NUMERIC NOT NULL,
    notes TEXT
);

CREATE INDEX idx_transactions_sportsbook ON public.transactions(sportsbook);
CREATE INDEX idx_transactions_created_at ON public.transactions(created_at DESC);

ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all access" ON public.transactions
    FOR ALL USING (true) WITH CHECK (true);

-- Research ledger + stricter CLV reference tracking
ALTER TABLE public.bets
    ADD COLUMN IF NOT EXISTS pinnacle_odds_at_entry NUMERIC,
    ADD COLUMN IF NOT EXISTS pinnacle_odds_at_close NUMERIC,
    ADD COLUMN IF NOT EXISTS clv_updated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS commence_time TEXT,
    ADD COLUMN IF NOT EXISTS clv_team TEXT,
    ADD COLUMN IF NOT EXISTS clv_sport_key TEXT,
    ADD COLUMN IF NOT EXISTS clv_event_id TEXT,
    ADD COLUMN IF NOT EXISTS true_prob_at_entry NUMERIC,
    ADD COLUMN IF NOT EXISTS latest_pinnacle_odds NUMERIC,
    ADD COLUMN IF NOT EXISTS latest_pinnacle_updated_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_bets_clv_latest_pending
    ON public.bets (clv_sport_key, commence_time)
    WHERE result = 'pending' AND clv_sport_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.scan_opportunities (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    opportunity_key TEXT NOT NULL UNIQUE,
    surface TEXT NOT NULL,
    sport TEXT NOT NULL,
    event TEXT NOT NULL,
    commence_time TEXT NOT NULL,
    team TEXT NOT NULL,
    sportsbook TEXT NOT NULL,
    market TEXT NOT NULL,
    event_id TEXT,
    first_source TEXT NOT NULL,
    last_source TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
    best_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
    first_book_odds NUMERIC NOT NULL,
    last_book_odds NUMERIC NOT NULL,
    best_book_odds NUMERIC NOT NULL,
    first_reference_odds NUMERIC NOT NULL,
    last_reference_odds NUMERIC NOT NULL,
    best_reference_odds NUMERIC NOT NULL,
    first_ev_percentage NUMERIC NOT NULL,
    last_ev_percentage NUMERIC NOT NULL,
    best_ev_percentage NUMERIC NOT NULL,
    latest_reference_odds NUMERIC,
    latest_reference_updated_at TIMESTAMP WITH TIME ZONE,
    reference_odds_at_close NUMERIC,
    close_captured_at TIMESTAMP WITH TIME ZONE,
    clv_ev_percent NUMERIC,
    beat_close BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_scan_opportunities_sport
    ON public.scan_opportunities (sport);

CREATE INDEX IF NOT EXISTS idx_scan_opportunities_first_seen_at
    ON public.scan_opportunities (first_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_scan_opportunities_open_close
    ON public.scan_opportunities (sport, commence_time)
    WHERE reference_odds_at_close IS NULL;

ALTER TABLE public.scan_opportunities ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.ops_job_runs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    job_kind TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT,
    scan_session_id TEXT,
    surface TEXT,
    scan_scope TEXT,
    requested_sport TEXT,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    duration_ms NUMERIC,
    events_fetched INTEGER,
    events_with_both_books INTEGER,
    total_sides INTEGER,
    alerts_scheduled INTEGER,
    hard_errors INTEGER,
    error_count INTEGER,
    settled INTEGER,
    api_requests_remaining TEXT,
    checks JSONB,
    skipped_totals JSONB,
    errors JSONB,
    meta JSONB
);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_kind_captured_at
    ON public.ops_job_runs (job_kind, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_source_captured_at
    ON public.ops_job_runs (source, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_run_id
    ON public.ops_job_runs (run_id);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_scan_session_id
    ON public.ops_job_runs (scan_session_id);

ALTER TABLE public.ops_job_runs ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.odds_api_activity_events (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    activity_kind TEXT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    scan_session_id TEXT,
    source TEXT NOT NULL,
    surface TEXT,
    scan_scope TEXT,
    requested_sport TEXT,
    sport TEXT,
    actor_label TEXT,
    run_id TEXT,
    endpoint TEXT,
    cache_hit BOOLEAN,
    outbound_call_made BOOLEAN,
    duration_ms NUMERIC,
    events_fetched INTEGER,
    events_with_both_books INTEGER,
    sides_count INTEGER,
    api_requests_remaining TEXT,
    status_code INTEGER,
    error_type TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_captured_at
    ON public.odds_api_activity_events (captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_kind_captured_at
    ON public.odds_api_activity_events (activity_kind, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_scan_session_id
    ON public.odds_api_activity_events (scan_session_id, captured_at ASC);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_source_captured_at
    ON public.odds_api_activity_events (source, captured_at DESC);

ALTER TABLE public.odds_api_activity_events ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.parlay_slips (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    sportsbook TEXT NOT NULL,
    stake NUMERIC,
    legs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    pricing_preview_json JSONB,
    logged_bet_id UUID REFERENCES public.bets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_parlay_slips_user_updated
    ON public.parlay_slips (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_parlay_slips_logged_bet_id
    ON public.parlay_slips (logged_bet_id)
    WHERE logged_bet_id IS NOT NULL;

ALTER TABLE public.parlay_slips ENABLE ROW LEVEL SECURITY;
