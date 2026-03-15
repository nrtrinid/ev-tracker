-- ============================================================
-- Migration 001: Multi-Tenant Auth Support
-- ============================================================
-- Run this in the Supabase SQL Editor:
--   SQL Editor > New Query > Paste this entire file > Run
--
-- PREREQUISITE: Enable Email/Password auth in Supabase Dashboard:
--   Authentication > Providers > Email > Enable
--
-- BEFORE RUNNING: Replace 'PASTE_YOUR_COPIED_UUID_HERE' with your
--   auth.users.id from: Authentication > Users > copy your user's UUID
-- ============================================================

-- Step 1: Add user_id as nullable to bets
ALTER TABLE public.bets
  ADD COLUMN user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- Step 2: Add user_id as nullable to transactions
ALTER TABLE public.transactions
  ADD COLUMN user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- Step 3: Add user_id as nullable to settings (before restructure)
ALTER TABLE public.settings
  ADD COLUMN user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- Step 4: Assign all existing rows to your user
UPDATE public.bets SET user_id = 'PASTE_YOUR_COPIED_UUID_HERE' WHERE user_id IS NULL;
UPDATE public.transactions SET user_id = 'PASTE_YOUR_COPIED_UUID_HERE' WHERE user_id IS NULL;
UPDATE public.settings SET user_id = 'PASTE_YOUR_COPIED_UUID_HERE' WHERE user_id IS NULL;

-- Step 5: Make user_id NOT NULL
ALTER TABLE public.bets ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE public.transactions ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE public.settings ALTER COLUMN user_id SET NOT NULL;

-- Step 6: Restructure settings from single-row to per-user
ALTER TABLE public.settings DROP CONSTRAINT settings_pkey;
ALTER TABLE public.settings DROP COLUMN id;
ALTER TABLE public.settings ADD PRIMARY KEY (user_id);

-- Step 7: Add indexes for user-scoped queries
CREATE INDEX idx_bets_user_id ON public.bets(user_id);
CREATE INDEX idx_transactions_user_id ON public.transactions(user_id);

-- Step 8: Drop old permissive RLS policies
DROP POLICY IF EXISTS "Allow all access" ON public.bets;
DROP POLICY IF EXISTS "Allow all access" ON public.settings;
DROP POLICY IF EXISTS "Allow all access" ON public.transactions;

-- Step 9: Create per-user RLS policies for bets
CREATE POLICY "Users can view own bets" ON public.bets
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own bets" ON public.bets
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own bets" ON public.bets
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own bets" ON public.bets
  FOR DELETE USING (auth.uid() = user_id);

-- Step 10: Create per-user RLS policies for transactions
CREATE POLICY "Users can view own transactions" ON public.transactions
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own transactions" ON public.transactions
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own transactions" ON public.transactions
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own transactions" ON public.transactions
  FOR DELETE USING (auth.uid() = user_id);

-- Step 11: Create per-user RLS policies for settings
CREATE POLICY "Users can view own settings" ON public.settings
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own settings" ON public.settings
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own settings" ON public.settings
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own settings" ON public.settings
  FOR DELETE USING (auth.uid() = user_id);

-- Step 12: Grant service_role full access (backend uses service role key)
-- This is the default in Supabase — service_role bypasses RLS.
-- The RLS policies above protect against direct anon-key access.
