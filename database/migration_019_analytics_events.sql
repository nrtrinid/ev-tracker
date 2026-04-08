-- ============================================================
-- Migration 019: Lightweight analytics events for beta
-- ============================================================

CREATE TABLE IF NOT EXISTS public.analytics_events (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc', now()),
    event_name TEXT NOT NULL,
    source TEXT NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id TEXT,
    route TEXT,
    app_area TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_analytics_events_event_captured
    ON public.analytics_events (event_name, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_events_user_captured
    ON public.analytics_events (user_id, captured_at DESC)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_analytics_events_session_captured
    ON public.analytics_events (session_id, captured_at DESC)
    WHERE session_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_events_dedupe_key
    ON public.analytics_events (dedupe_key)
    WHERE dedupe_key IS NOT NULL;

ALTER TABLE public.analytics_events ENABLE ROW LEVEL SECURITY;
