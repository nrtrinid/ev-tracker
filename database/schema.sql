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
