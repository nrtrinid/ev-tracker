-- ============================================================
-- Migration 009: Research tracker exact-line player prop CLV
-- ============================================================

ALTER TABLE public.scan_opportunities
  ADD COLUMN IF NOT EXISTS player_name TEXT,
  ADD COLUMN IF NOT EXISTS source_market_key TEXT,
  ADD COLUMN IF NOT EXISTS selection_side TEXT,
  ADD COLUMN IF NOT EXISTS line_value NUMERIC;
