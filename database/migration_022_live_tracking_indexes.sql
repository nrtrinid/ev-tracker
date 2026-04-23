-- Live tracking reads pending bets by user, sport, and event window.
-- Live score/stat snapshots are cached, not persisted, in the MVP.
CREATE INDEX IF NOT EXISTS idx_bets_user_pending_live_window
  ON public.bets (user_id, clv_sport_key, commence_time)
  WHERE result = 'pending' AND commence_time IS NOT NULL;

