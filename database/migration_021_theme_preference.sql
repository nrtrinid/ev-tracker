-- ============================================================
-- Migration 021: Persist theme preference per user
-- ============================================================

ALTER TABLE public.settings
  ADD COLUMN IF NOT EXISTS theme_preference TEXT NOT NULL DEFAULT 'light';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'settings_theme_preference_check'
  ) THEN
    ALTER TABLE public.settings
      ADD CONSTRAINT settings_theme_preference_check
      CHECK (theme_preference IN ('light', 'dark'));
  END IF;
END;
$$;
