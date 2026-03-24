-- ============================================================
-- Migration 008: Kelly Settings Persistence
-- ============================================================

ALTER TABLE public.settings
    ADD COLUMN IF NOT EXISTS kelly_multiplier NUMERIC DEFAULT 0.25,
    ADD COLUMN IF NOT EXISTS bankroll_override NUMERIC DEFAULT 1000,
    ADD COLUMN IF NOT EXISTS use_computed_bankroll BOOLEAN DEFAULT TRUE;
