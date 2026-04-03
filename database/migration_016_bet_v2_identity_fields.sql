-- ============================================================
-- Migration 016: V2 bet identity + scanner surface fields
-- ============================================================
-- Stores richer selection identity for duplicate detection,
-- CLV tracking, parlay leg metadata, and player-prop settlement.

ALTER TABLE public.bets
  ADD COLUMN IF NOT EXISTS surface TEXT NOT NULL DEFAULT 'straight_bets',
  ADD COLUMN IF NOT EXISTS source_event_id TEXT,
  ADD COLUMN IF NOT EXISTS source_market_key TEXT,
  ADD COLUMN IF NOT EXISTS source_selection_key TEXT,
  ADD COLUMN IF NOT EXISTS participant_name TEXT,
  ADD COLUMN IF NOT EXISTS participant_id TEXT,
  ADD COLUMN IF NOT EXISTS selection_side TEXT,
  ADD COLUMN IF NOT EXISTS line_value DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS selection_meta JSONB;

