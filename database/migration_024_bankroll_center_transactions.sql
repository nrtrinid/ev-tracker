-- ============================================================
-- Migration 024: Bankroll Center transaction metadata
-- ============================================================
-- Extends the existing manual bankroll transaction ledger so the
-- app can log signed tracked-balance adjustments alongside deposits
-- and withdrawals. Bet settlement remains represented by bets, not by
-- generated transactions.

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS transaction_date TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc', now());

UPDATE public.transactions
SET transaction_date = created_at
WHERE transaction_date IS NULL;

ALTER TABLE public.transactions
  ALTER COLUMN transaction_date SET DEFAULT timezone('utc', now()),
  ALTER COLUMN transaction_date SET NOT NULL;

ALTER TABLE public.transactions
  DROP CONSTRAINT IF EXISTS transactions_type_check;

ALTER TABLE public.transactions
  ADD CONSTRAINT transactions_type_check
  CHECK (type IN ('deposit', 'withdrawal', 'adjustment'));

CREATE INDEX IF NOT EXISTS idx_transactions_user_transaction_date
  ON public.transactions(user_id, transaction_date DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_user_sportsbook_transaction_date
  ON public.transactions(user_id, sportsbook, transaction_date DESC);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_transactions_updated_at ON public.transactions;

CREATE TRIGGER trg_transactions_updated_at
BEFORE UPDATE ON public.transactions
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
