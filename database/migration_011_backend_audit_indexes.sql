-- ============================================================
-- Migration 011: Backend audit / CLV close-window indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_bets_pending_clv_commence_time
  ON public.bets (commence_time)
  WHERE result = 'pending' AND clv_sport_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scan_opportunities_pending_commence_time
  ON public.scan_opportunities (commence_time, surface, sport)
  WHERE reference_odds_at_close IS NULL OR close_captured_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_scan_opportunities_prop_lookup
  ON public.scan_opportunities (event_id, source_market_key, selection_side, line_value)
  WHERE surface = 'player_props';
