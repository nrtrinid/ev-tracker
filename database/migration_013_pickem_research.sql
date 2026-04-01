-- ============================================================
-- Migration 013: Pick'em research shadow-tracking
-- ============================================================

CREATE TABLE IF NOT EXISTS public.pickem_research_observations (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
  observation_key TEXT NOT NULL UNIQUE,
  comparison_key TEXT NOT NULL,
  observation_kind TEXT NOT NULL DEFAULT 'board_pickem_consensus',
  surface TEXT NOT NULL DEFAULT 'player_props',
  sport TEXT NOT NULL,
  event TEXT NOT NULL,
  commence_time TEXT NOT NULL,
  market TEXT NOT NULL,
  market_key TEXT NOT NULL,
  event_id TEXT,
  player_name TEXT NOT NULL,
  team TEXT,
  opponent TEXT,
  selection_side TEXT NOT NULL,
  line_value DOUBLE PRECISION NOT NULL,
  calibration_bucket TEXT NOT NULL,
  first_source TEXT NOT NULL,
  last_source TEXT NOT NULL,
  surfaced_count INTEGER NOT NULL DEFAULT 1,
  first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
  last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
  first_display_probability DOUBLE PRECISION NOT NULL,
  last_display_probability DOUBLE PRECISION NOT NULL,
  first_fair_odds_american DOUBLE PRECISION,
  last_fair_odds_american DOUBLE PRECISION,
  first_books_matched_count INTEGER NOT NULL DEFAULT 0,
  last_books_matched_count INTEGER NOT NULL DEFAULT 0,
  first_confidence_label TEXT,
  last_confidence_label TEXT,
  ev_basis TEXT NOT NULL DEFAULT 'best_market_price',
  first_selected_sportsbook TEXT,
  last_selected_sportsbook TEXT,
  first_selected_market_odds DOUBLE PRECISION,
  last_selected_market_odds DOUBLE PRECISION,
  first_projected_edge_pct DOUBLE PRECISION,
  last_projected_edge_pct DOUBLE PRECISION,
  latest_reference_odds DOUBLE PRECISION,
  latest_reference_updated_at TIMESTAMP WITH TIME ZONE,
  close_reference_odds DOUBLE PRECISION,
  close_opposing_reference_odds DOUBLE PRECISION,
  close_true_prob DOUBLE PRECISION,
  close_quality TEXT,
  close_captured_at TIMESTAMP WITH TIME ZONE,
  close_edge_pct DOUBLE PRECISION,
  actual_result TEXT,
  settled_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_pickem_research_first_seen_at
  ON public.pickem_research_observations (first_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_pickem_research_open_close
  ON public.pickem_research_observations (sport, commence_time)
  WHERE close_captured_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_pickem_research_unsettled
  ON public.pickem_research_observations (sport, commence_time)
  WHERE actual_result IS NULL;

CREATE INDEX IF NOT EXISTS idx_pickem_research_market_bucket
  ON public.pickem_research_observations (market_key, calibration_bucket, first_books_matched_count);
