-- ============================================================
-- Migration 010: Protect global scanner cache with RLS
-- ============================================================
-- The frontend only needs authenticated read access for realtime
-- invalidation. The backend uses the service-role key and bypasses RLS.

CREATE TABLE IF NOT EXISTS public.global_scan_cache (
  key TEXT PRIMARY KEY,
  surface TEXT NOT NULL DEFAULT 'straight_bets',
  payload JSONB NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc', now())
);

ALTER TABLE public.global_scan_cache
  ADD COLUMN IF NOT EXISTS surface TEXT NOT NULL DEFAULT 'straight_bets';

ALTER TABLE public.global_scan_cache ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Authenticated users can read global scan cache" ON public.global_scan_cache;
CREATE POLICY "Authenticated users can read global scan cache" ON public.global_scan_cache
  FOR SELECT TO authenticated USING (true);
