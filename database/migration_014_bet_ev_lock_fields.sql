-- ============================================================
-- Migration 014: Locked EV fields for historical bet snapshots
-- ============================================================
-- Freezes EV / payout values at bet-log time so later settings
-- or formula changes do not rewrite historical analytics.

ALTER TABLE public.bets
  ADD COLUMN IF NOT EXISTS ev_per_dollar_locked NUMERIC,
  ADD COLUMN IF NOT EXISTS ev_total_locked NUMERIC,
  ADD COLUMN IF NOT EXISTS win_payout_locked NUMERIC,
  ADD COLUMN IF NOT EXISTS ev_locked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS ev_lock_version INT NOT NULL DEFAULT 1;

