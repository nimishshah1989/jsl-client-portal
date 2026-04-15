-- Migration: Add ISIN to cpp_transactions and cpp_holdings
-- Run once against the RDS database.
-- Safe to run multiple times (uses IF NOT EXISTS / DO NOTHING).
--
-- After running this migration:
--   1. Upload the new transaction files (Apr 2026 format) via admin
--   2. System will populate ISIN for all new ingestions
--   3. Re-ingesting existing clients will backfill ISIN from the new files

-- ── cpp_transactions: add ISIN column ────────────────────────────────────────
ALTER TABLE cpp_transactions
    ADD COLUMN IF NOT EXISTS isin VARCHAR(20) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_cpp_txn_isin
    ON cpp_transactions (isin)
    WHERE isin IS NOT NULL;

-- ── cpp_holdings: add ISIN column ────────────────────────────────────────────
ALTER TABLE cpp_holdings
    ADD COLUMN IF NOT EXISTS isin VARCHAR(20) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_cpp_holdings_isin
    ON cpp_holdings (isin)
    WHERE isin IS NOT NULL;

-- ── Backfill ISIN in cpp_holdings from cpp_transactions (where available) ───
-- Uses the most recently traded transaction for each (client_id, symbol) pair.
UPDATE cpp_holdings h
SET isin = t.isin
FROM (
    SELECT DISTINCT ON (client_id, portfolio_id, symbol)
        client_id, portfolio_id, symbol, isin
    FROM cpp_transactions
    WHERE isin IS NOT NULL AND isin != ''
    ORDER BY client_id, portfolio_id, symbol, txn_date DESC
) t
WHERE h.client_id = t.client_id
  AND h.portfolio_id = t.portfolio_id
  AND h.symbol = t.symbol
  AND (h.isin IS NULL OR h.isin = '');

-- Verify
SELECT
    'cpp_transactions' AS tbl,
    COUNT(*) AS total_rows,
    COUNT(isin) AS rows_with_isin,
    COUNT(DISTINCT isin) AS unique_isins
FROM cpp_transactions
UNION ALL
SELECT
    'cpp_holdings' AS tbl,
    COUNT(*) AS total_rows,
    COUNT(isin) AS rows_with_isin,
    COUNT(DISTINCT isin) AS unique_isins
FROM cpp_holdings;
