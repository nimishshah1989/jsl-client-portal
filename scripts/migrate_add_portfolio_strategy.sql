-- Migration: tag each portfolio with its source UCC, strategy, and closed flag.
--
-- Strategy rule (single source of truth: backend/services/classification.py):
--   code ends 'PASS' -> PASSIVE, ends 'IND' -> IND11, else LEADERS;
--   code ends 'CLOSE'/'CLO' -> is_closed (archived, excluded from live views).
--
-- Additive + idempotent. Existing rows default to LEADERS / not-closed until the
-- backfill (scripts/backfill_portfolio_strategy.py) sets the real values.

ALTER TABLE cpp_portfolios ADD COLUMN IF NOT EXISTS client_code VARCHAR(50);
ALTER TABLE cpp_portfolios ADD COLUMN IF NOT EXISTS strategy VARCHAR(20) NOT NULL DEFAULT 'LEADERS';
ALTER TABLE cpp_portfolios ADD COLUMN IF NOT EXISTS is_closed BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN cpp_portfolios.client_code IS 'Source UCC for this portfolio (e.g. BJ53, BJ53PASS). Unique once backfilled.';
COMMENT ON COLUMN cpp_portfolios.strategy IS 'LEADERS | PASSIVE | IND11 (derived from client_code suffix)';
COMMENT ON COLUMN cpp_portfolios.is_closed IS 'Archived account (CLOSE/CLO suffix) - excluded from live aggregates and Combined view';

CREATE INDEX IF NOT EXISTS ix_cpp_portfolios_strategy ON cpp_portfolios (strategy);
CREATE INDEX IF NOT EXISTS ix_cpp_portfolios_is_closed ON cpp_portfolios (is_closed);

-- Enforce the valid strategy set at the DB (defence in depth — the app only
-- ever writes these via services/classification.py). Idempotent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cpp_portfolios_strategy'
    ) THEN
        ALTER TABLE cpp_portfolios
            ADD CONSTRAINT ck_cpp_portfolios_strategy
            CHECK (strategy IN ('LEADERS', 'PASSIVE', 'IND11'));
    END IF;
END $$;

-- One portfolio per UCC. NULLs are permitted during the transition (Postgres
-- allows multiple NULLs under a unique index); every row is unique post-backfill.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cpp_portfolios_client_code ON cpp_portfolios (client_code);
