-- Add clv_event_id for deterministic auto-settlement matching.
ALTER TABLE public.bets
  ADD COLUMN IF NOT EXISTS clv_event_id TEXT;

CREATE INDEX IF NOT EXISTS idx_bets_clv_event_id_pending
  ON public.bets (clv_event_id, result)
  WHERE clv_event_id IS NOT NULL AND result = 'pending';
