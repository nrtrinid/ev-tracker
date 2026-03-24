-- ============================================================
-- Migration 007: Saved Parlay Slips
-- ============================================================

CREATE TABLE IF NOT EXISTS public.parlay_slips (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    sportsbook TEXT NOT NULL,
    stake NUMERIC,
    legs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    pricing_preview_json JSONB,
    logged_bet_id UUID REFERENCES public.bets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_parlay_slips_user_updated
    ON public.parlay_slips (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_parlay_slips_logged_bet_id
    ON public.parlay_slips (logged_bet_id)
    WHERE logged_bet_id IS NOT NULL;

ALTER TABLE public.parlay_slips ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own parlay slips" ON public.parlay_slips;
DROP POLICY IF EXISTS "Users can insert own parlay slips" ON public.parlay_slips;
DROP POLICY IF EXISTS "Users can update own parlay slips" ON public.parlay_slips;
DROP POLICY IF EXISTS "Users can delete own parlay slips" ON public.parlay_slips;

CREATE POLICY "Users can view own parlay slips" ON public.parlay_slips
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own parlay slips" ON public.parlay_slips
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own parlay slips" ON public.parlay_slips
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own parlay slips" ON public.parlay_slips
  FOR DELETE USING (auth.uid() = user_id);
