-- ============================================================
-- Migration 003: V1 Paper Autolog Metadata
-- ============================================================
-- Adds minimal experiment fields for scanner duplicate state and paper autolog
-- tracking. Defaults keep existing/manual bet behavior unchanged.
--
-- Run in Supabase SQL Editor as a single script.
-- ============================================================

ALTER TABLE public.bets
  ADD COLUMN IF NOT EXISTS is_paper                BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS strategy_cohort         TEXT,
  ADD COLUMN IF NOT EXISTS auto_logged             BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS auto_log_run_at         TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS auto_log_run_key        TEXT,
  ADD COLUMN IF NOT EXISTS scan_ev_percent_at_log  NUMERIC,
  ADD COLUMN IF NOT EXISTS book_odds_at_log        NUMERIC,
  ADD COLUMN IF NOT EXISTS reference_odds_at_log   NUMERIC;

-- Narrow indexes for V1 query paths
CREATE INDEX IF NOT EXISTS idx_bets_user_result_cohort
  ON public.bets (user_id, result, strategy_cohort);

CREATE INDEX IF NOT EXISTS idx_bets_user_autolog_run_at
  ON public.bets (user_id, auto_logged, auto_log_run_at DESC);

CREATE INDEX IF NOT EXISTS idx_bets_user_autolog_run_key
  ON public.bets (user_id, auto_log_run_key)
  WHERE auto_log_run_key IS NOT NULL;
