-- ============================================================
-- Migration 017: Keep global scan cache updated_at current
-- ============================================================
-- Migration 010 created the durable cache table + read policy.
-- This adds the update trigger previously documented only in a
-- manual backend/sql script.

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_global_scan_cache_updated_at ON public.global_scan_cache;
CREATE TRIGGER trg_global_scan_cache_updated_at
BEFORE UPDATE ON public.global_scan_cache
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

