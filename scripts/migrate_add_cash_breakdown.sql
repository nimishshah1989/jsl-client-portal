-- Migration: Add cash breakdown columns to cpp_nav_series
-- Purpose: Store ETF, cash, and bank values separately so true cash % can be computed
-- (Liquidity% from PMS file excludes LIQUIDBEES)

ALTER TABLE cpp_nav_series ADD COLUMN IF NOT EXISTS etf_value NUMERIC(18,2) DEFAULT 0;
ALTER TABLE cpp_nav_series ADD COLUMN IF NOT EXISTS cash_value NUMERIC(18,2) DEFAULT 0;
ALTER TABLE cpp_nav_series ADD COLUMN IF NOT EXISTS bank_balance NUMERIC(18,2) DEFAULT 0;

COMMENT ON COLUMN cpp_nav_series.etf_value IS 'Investments in ETF (LIQUIDBEES etc)';
COMMENT ON COLUMN cpp_nav_series.cash_value IS 'Cash And Cash Equivalent from NAV file';
COMMENT ON COLUMN cpp_nav_series.bank_balance IS 'Bank Balance from NAV file';
