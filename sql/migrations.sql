-- ════════════════════════════════════════════════════════════════════
-- Migrations — June 2026 feature round (cost basis, alerts, history,
-- prediction logging). Run once in Supabase → SQL Editor.
-- The app degrades gracefully until this runs (features simply hidden).
-- ════════════════════════════════════════════════════════════════════

-- 1) Crypto cost basis + price alerts
ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS avg_price    numeric;
ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS target_above numeric;
ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS target_below numeric;

-- 2) Daily portfolio value history (powers the "value over time" chart)
CREATE TABLE IF NOT EXISTS portfolio_history (
    date        date PRIMARY KEY,
    total_value numeric NOT NULL,
    pnl_24h     numeric DEFAULT 0,
    updated_at  timestamptz DEFAULT now()
);

-- 3) Full prediction log (ALL daily predictions, not just ticket picks —
--    accrues data for model calibration / backtesting)
CREATE TABLE IF NOT EXISTS predictions (
    fixture_id  bigint PRIMARY KEY,
    date        date NOT NULL,
    match       text NOT NULL,
    league      text,
    market      text NOT NULL,
    confidence  numeric,
    ev          numeric,
    real_ev     numeric,
    odds        numeric,
    value_bet   boolean DEFAULT false,
    result      text DEFAULT 'pending',
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions (date);
