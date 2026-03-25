-- Creates a durable store for the latest global scanner payload.
-- Run this once in Supabase SQL editor (or your migration system).
create table if not exists public.global_scan_cache (
  key text primary key,
  surface text not null default 'straight_bets',
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.global_scan_cache
  add column if not exists surface text not null default 'straight_bets';

alter table public.global_scan_cache enable row level security;

drop policy if exists "Authenticated users can read global scan cache" on public.global_scan_cache;
create policy "Authenticated users can read global scan cache"
on public.global_scan_cache
for select
to authenticated
using (true);

-- Automatically keep updated_at current on upserts/updates.
create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_global_scan_cache_updated_at on public.global_scan_cache;
create trigger trg_global_scan_cache_updated_at
before update on public.global_scan_cache
for each row execute function public.set_updated_at();

