-- Migration: V2 scanner surfaces, player props logging identity, onboarding state.

alter table public.bets
  add column if not exists surface text not null default 'straight_bets',
  add column if not exists source_event_id text,
  add column if not exists source_market_key text,
  add column if not exists source_selection_key text,
  add column if not exists participant_name text,
  add column if not exists participant_id text,
  add column if not exists selection_side text,
  add column if not exists line_value double precision,
  add column if not exists selection_meta jsonb;

alter table public.settings
  add column if not exists onboarding_state jsonb not null default jsonb_build_object(
    'version', 1,
    'completed', '[]'::jsonb,
    'dismissed', '[]'::jsonb,
    'last_seen_at', null
  );
