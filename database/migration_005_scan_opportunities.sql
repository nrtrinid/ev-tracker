-- ============================================================
-- Migration 005: Research scan opportunities + stricter CLV refs
-- ============================================================
-- Adds:
-- 1. latest Pinnacle reference fields on bets
-- 2. global scan_opportunities ledger for straight-bet research capture
-- ============================================================

ALTER TABLE public.bets
  ADD COLUMN IF NOT EXISTS latest_pinnacle_odds       NUMERIC,
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
