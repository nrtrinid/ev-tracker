-- ============================================================
-- Migration 002: CLV (Closing Line Value) Tracking
-- ============================================================
-- Run this in the Supabase SQL Editor:
--   SQL Editor > New Query > Paste this entire file > Run
--
-- This migration adds six columns to the bets table to enable
-- the Piggyback + Safety Net CLV architecture. No existing rows
-- are modified; all new columns default to NULL.
-- ============================================================

-- CLV metadata columns
ALTER TABLE public.bets
  ADD COLUMN IF NOT EXISTS pinnacle_odds_at_entry  NUMERIC,
  ADD COLUMN IF NOT EXISTS pinnacle_odds_at_close  NUMERIC,
  ADD COLUMN IF NOT EXISTS clv_updated_at          TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS commence_time           TEXT,       -- ISO-8601 from Odds API (stored as text to avoid TZ normalisation)
  ADD COLUMN IF NOT EXISTS clv_team                TEXT,       -- Team name for snapshot matching
  ADD COLUMN IF NOT EXISTS clv_sport_key           TEXT,       -- Odds API sport key (e.g. basketball_nba) for daily job
  ADD COLUMN IF NOT EXISTS true_prob_at_entry      NUMERIC;    -- De-vigged Pinnacle probability at bet time — used for accurate EV on standard bets

-- Partial index: only pending bets with CLV enabled matter for the update loop
CREATE INDEX IF NOT EXISTS idx_bets_clv_pending
  ON public.bets (result, clv_team)
  WHERE clv_team IS NOT NULL;

-- Index for the daily safety-net job (pending bets grouped by sport key)
CREATE INDEX IF NOT EXISTS idx_bets_clv_sport_key
  ON public.bets (clv_sport_key, result)
  WHERE clv_sport_key IS NOT NULL AND result = 'pending';
