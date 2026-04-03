-- ============================================================
-- Migration 015: Settings personalization + onboarding state
-- ============================================================
-- Adds persisted controls for automatic k-factor tuning plus a
-- durable onboarding state blob used by the frontend.

ALTER TABLE public.settings
  ADD COLUMN IF NOT EXISTS k_factor_mode TEXT NOT NULL DEFAULT 'baseline',
  ADD COLUMN IF NOT EXISTS k_factor_min_stake NUMERIC NOT NULL DEFAULT 300,
  ADD COLUMN IF NOT EXISTS k_factor_smoothing NUMERIC NOT NULL DEFAULT 700,
  ADD COLUMN IF NOT EXISTS k_factor_clamp_min NUMERIC NOT NULL DEFAULT 0.50,
  ADD COLUMN IF NOT EXISTS k_factor_clamp_max NUMERIC NOT NULL DEFAULT 0.95,
  ADD COLUMN IF NOT EXISTS onboarding_state JSONB NOT NULL DEFAULT jsonb_build_object(
    'version', 1,
    'completed', '[]'::jsonb,
    'dismissed', '[]'::jsonb,
    'last_seen_at', null
  );

