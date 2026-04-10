-- ============================================================
-- Migration 020: Trusted beta invite-code access state
-- ============================================================

ALTER TABLE public.settings
  ADD COLUMN IF NOT EXISTS beta_access_granted BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS beta_access_granted_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS beta_access_method TEXT;
