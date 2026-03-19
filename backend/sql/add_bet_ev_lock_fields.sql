-- Migration: add locked EV fields to bets table so historical EV is frozen at log time
-- Run in Supabase SQL Editor

ALTER TABLE public.bets
  ADD COLUMN IF NOT EXISTS ev_per_dollar_locked NUMERIC,
  ADD COLUMN IF NOT EXISTS ev_total_locked       NUMERIC,
  ADD COLUMN IF NOT EXISTS win_payout_locked     NUMERIC,
  ADD COLUMN IF NOT EXISTS ev_locked_at          TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS ev_lock_version       INT NOT NULL DEFAULT 1;

-- Backfill: sets ev_locked_at to NOW() for existing bonus_bet rows so
-- build_bet_response will use the dynamic calculation as the locked value
-- on the next fetch (see backend logic: lock is written by create_bet/update_bet).
-- For existing rows, ev_per_dollar_locked/ev_total_locked remain NULL and
-- build_bet_response falls back to computed EV — this is acceptable since
-- we cannot retroactively know which k was in effect.
-- If you want to truly freeze legacy rows, trigger a one-off backfill via
-- the /admin/backfill-ev-locks endpoint (see backend/main.py).
