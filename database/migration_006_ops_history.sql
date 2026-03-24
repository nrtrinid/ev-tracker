CREATE TABLE IF NOT EXISTS public.ops_job_runs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    job_kind TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT,
    scan_session_id TEXT,
    surface TEXT,
    scan_scope TEXT,
    requested_sport TEXT,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    duration_ms NUMERIC,
    events_fetched INTEGER,
    events_with_both_books INTEGER,
    total_sides INTEGER,
    alerts_scheduled INTEGER,
    hard_errors INTEGER,
    error_count INTEGER,
    settled INTEGER,
    api_requests_remaining TEXT,
    checks JSONB,
    skipped_totals JSONB,
    errors JSONB,
    meta JSONB
);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_kind_captured_at
    ON public.ops_job_runs (job_kind, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_source_captured_at
    ON public.ops_job_runs (source, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_run_id
    ON public.ops_job_runs (run_id);

CREATE INDEX IF NOT EXISTS idx_ops_job_runs_scan_session_id
    ON public.ops_job_runs (scan_session_id);

ALTER TABLE public.ops_job_runs ENABLE ROW LEVEL SECURITY;


CREATE TABLE IF NOT EXISTS public.odds_api_activity_events (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    activity_kind TEXT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    scan_session_id TEXT,
    source TEXT NOT NULL,
    surface TEXT,
    scan_scope TEXT,
    requested_sport TEXT,
    sport TEXT,
    actor_label TEXT,
    run_id TEXT,
    endpoint TEXT,
    cache_hit BOOLEAN,
    outbound_call_made BOOLEAN,
    duration_ms NUMERIC,
    events_fetched INTEGER,
    events_with_both_books INTEGER,
    sides_count INTEGER,
    api_requests_remaining TEXT,
    status_code INTEGER,
    error_type TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_captured_at
    ON public.odds_api_activity_events (captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_kind_captured_at
    ON public.odds_api_activity_events (activity_kind, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_scan_session_id
    ON public.odds_api_activity_events (scan_session_id, captured_at ASC);

CREATE INDEX IF NOT EXISTS idx_odds_api_activity_events_source_captured_at
    ON public.odds_api_activity_events (source, captured_at DESC);

ALTER TABLE public.odds_api_activity_events ENABLE ROW LEVEL SECURITY;
