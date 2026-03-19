-- Migration: add personalized k-factor auto fields to settings table
-- Run in Supabase SQL Editor

ALTER TABLE public.settings
  ADD COLUMN IF NOT EXISTS k_factor_mode        TEXT    NOT NULL DEFAULT 'baseline',
  ADD COLUMN IF NOT EXISTS k_factor_min_stake   NUMERIC NOT NULL DEFAULT 300,
  ADD COLUMN IF NOT EXISTS k_factor_smoothing   NUMERIC NOT NULL DEFAULT 700,
  ADD COLUMN IF NOT EXISTS k_factor_clamp_min   NUMERIC NOT NULL DEFAULT 0.50,
  ADD COLUMN IF NOT EXISTS k_factor_clamp_max   NUMERIC NOT NULL DEFAULT 0.95;

-- k_factor_mode values: 'baseline' | 'auto'
-- baseline = always use the user-set k_factor (0.78 default)
-- auto     = blend observed retention with baseline after sample threshold
