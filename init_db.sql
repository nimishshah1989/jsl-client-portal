-- JSL Client Portfolio Portal — Database Schema
-- Run: psql -h fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com -U fie_admin -d client_portal -f init_db.sql
-- All tables use cpp_ prefix to coexist on shared RDS instance

-- ══════════════════════════════════════════════
-- 1. CLIENTS (auth + profile)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_clients (
    id              SERIAL PRIMARY KEY,
    client_code     VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(200) NOT NULL,
    email           VARCHAR(200),
    phone           VARCHAR(20),
    username        VARCHAR(100) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    is_admin        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),
    last_login      TIMESTAMP,
    CONSTRAINT cpp_clients_username_lower CHECK (username = LOWER(username))
);

-- ══════════════════════════════════════════════
-- 2. PORTFOLIOS (one client can have multiple)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_portfolios (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    portfolio_name  VARCHAR(200) NOT NULL,
    benchmark       VARCHAR(50) DEFAULT 'NIFTY500',
    inception_date  DATE NOT NULL,
    status          VARCHAR(20) DEFAULT 'active',
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, portfolio_name)
);

CREATE INDEX IF NOT EXISTS idx_cpp_portfolios_client ON cpp_portfolios(client_id);

-- ══════════════════════════════════════════════
-- 3. NAV SERIES (daily time series — drives all charts)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_nav_series (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    portfolio_id    INTEGER NOT NULL REFERENCES cpp_portfolios(id) ON DELETE CASCADE,
    nav_date        DATE NOT NULL,
    nav_value       NUMERIC(18, 6) NOT NULL,
    invested_amount NUMERIC(18, 2) NOT NULL,
    current_value   NUMERIC(18, 2) NOT NULL,
    benchmark_value NUMERIC(18, 6),
    cash_pct        NUMERIC(8, 4),              -- Cash + liquid as % of NAV
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, portfolio_id, nav_date)
);

CREATE INDEX IF NOT EXISTS idx_cpp_nav_client_date 
    ON cpp_nav_series(client_id, portfolio_id, nav_date);

-- ══════════════════════════════════════════════
-- 4. TRANSACTIONS (buy/sell/SIP/dividend)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_transactions (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    portfolio_id    INTEGER NOT NULL REFERENCES cpp_portfolios(id) ON DELETE CASCADE,
    txn_date        DATE NOT NULL,
    txn_type        VARCHAR(20) NOT NULL,       -- BUY, SELL, BONUS, CORPUS_IN
    symbol          VARCHAR(100) NOT NULL,       -- e.g., "RELIANCE" (cleaned from "RELIANCE     EQ")
    asset_name      VARCHAR(300),
    asset_class     VARCHAR(50),                 -- EQUITY, CASH (for LIQUIDBEES etc.)
    instrument_type VARCHAR(10) DEFAULT 'EQ',    -- EQ, BE, etc.
    exchange        VARCHAR(10),                 -- CM (Cash Market)
    settlement_no   VARCHAR(50),                 -- Settlement number or "Corpus"/"BONUS"
    quantity        NUMERIC(18, 4),
    price           NUMERIC(18, 4),              -- Net Rate per share
    cost_rate       NUMERIC(18, 4),              -- All-in cost rate (incl. taxes)
    amount          NUMERIC(18, 2) NOT NULL,     -- Total amount with all costs
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cpp_txn_client 
    ON cpp_transactions(client_id, portfolio_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_cpp_txn_type 
    ON cpp_transactions(txn_type);

-- ══════════════════════════════════════════════
-- 5. HOLDINGS (current snapshot — recomputed after every transaction upload)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_holdings (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    portfolio_id    INTEGER NOT NULL REFERENCES cpp_portfolios(id) ON DELETE CASCADE,
    symbol          VARCHAR(100) NOT NULL,
    asset_name      VARCHAR(300),
    asset_class     VARCHAR(50),
    quantity        NUMERIC(18, 4) NOT NULL,
    avg_cost        NUMERIC(18, 4) NOT NULL,
    current_price   NUMERIC(18, 4),
    current_value   NUMERIC(18, 2),
    unrealized_pnl  NUMERIC(18, 2),
    weight_pct      NUMERIC(8, 4),
    sector          VARCHAR(100),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, portfolio_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_cpp_holdings_client 
    ON cpp_holdings(client_id, portfolio_id);

-- ══════════════════════════════════════════════
-- 6. RISK METRICS (computed from NAV series — one row per computation date)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_risk_metrics (
    id                  SERIAL PRIMARY KEY,
    client_id           INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    portfolio_id        INTEGER NOT NULL REFERENCES cpp_portfolios(id) ON DELETE CASCADE,
    computed_date       DATE NOT NULL,
    
    -- Return metrics
    absolute_return     NUMERIC(12, 4),
    cagr                NUMERIC(12, 4),
    xirr                NUMERIC(12, 4),
    
    -- Risk metrics
    volatility          NUMERIC(10, 4),
    sharpe_ratio        NUMERIC(10, 4),
    sortino_ratio       NUMERIC(10, 4),
    max_drawdown        NUMERIC(10, 4),
    max_dd_start        DATE,
    max_dd_end          DATE,
    max_dd_recovery     DATE,
    
    -- Benchmark-relative
    alpha               NUMERIC(10, 4),
    beta                NUMERIC(10, 4),
    information_ratio   NUMERIC(10, 4),
    tracking_error      NUMERIC(10, 4),
    up_capture          NUMERIC(10, 4),
    down_capture        NUMERIC(10, 4),
    
    -- Stress & drawdown
    ulcer_index         NUMERIC(10, 4),
    max_consecutive_loss INTEGER,
    avg_cash_held       NUMERIC(8, 4),
    max_cash_held       NUMERIC(8, 4),
    market_correlation  NUMERIC(8, 4),
    
    -- Monthly return profile
    monthly_hit_rate    NUMERIC(8, 4),
    best_month          NUMERIC(10, 4),
    worst_month         NUMERIC(10, 4),
    avg_positive_month  NUMERIC(10, 4),
    avg_negative_month  NUMERIC(10, 4),
    
    -- Rolling period returns
    return_1m           NUMERIC(12, 4),
    return_3m           NUMERIC(12, 4),
    return_6m           NUMERIC(12, 4),
    return_1y           NUMERIC(12, 4),
    return_2y           NUMERIC(12, 4),
    return_3y           NUMERIC(12, 4),
    return_5y           NUMERIC(12, 4),
    return_inception    NUMERIC(12, 4),
    
    -- Benchmark period returns (for comparison)
    bench_return_1m     NUMERIC(12, 4),
    bench_return_3m     NUMERIC(12, 4),
    bench_return_6m     NUMERIC(12, 4),
    bench_return_1y     NUMERIC(12, 4),
    bench_return_2y     NUMERIC(12, 4),
    bench_return_3y     NUMERIC(12, 4),
    bench_return_5y     NUMERIC(12, 4),
    bench_return_inception NUMERIC(12, 4),
    
    -- Benchmark risk metrics (for comparison)
    bench_volatility    NUMERIC(10, 4),
    bench_max_drawdown  NUMERIC(10, 4),
    bench_sharpe        NUMERIC(10, 4),
    bench_sortino       NUMERIC(10, 4),
    
    -- Config
    risk_free_rate      NUMERIC(6, 4) DEFAULT 6.50,
    
    created_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, portfolio_id, computed_date)
);

CREATE INDEX IF NOT EXISTS idx_cpp_risk_client 
    ON cpp_risk_metrics(client_id, portfolio_id, computed_date DESC);

-- ══════════════════════════════════════════════
-- 7. DRAWDOWN SERIES (for underwater chart)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_drawdown_series (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    portfolio_id    INTEGER NOT NULL REFERENCES cpp_portfolios(id) ON DELETE CASCADE,
    dd_date         DATE NOT NULL,
    drawdown_pct    NUMERIC(10, 6) NOT NULL,
    peak_nav        NUMERIC(18, 6),
    current_nav     NUMERIC(18, 6),
    bench_drawdown  NUMERIC(10, 6),           -- Benchmark drawdown for overlay
    UNIQUE(client_id, portfolio_id, dd_date)
);

CREATE INDEX IF NOT EXISTS idx_cpp_dd_client 
    ON cpp_drawdown_series(client_id, portfolio_id, dd_date);

-- ══════════════════════════════════════════════
-- 8. UPLOAD LOG (admin audit trail)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_upload_log (
    id              SERIAL PRIMARY KEY,
    uploaded_by     INTEGER REFERENCES cpp_clients(id),
    file_type       VARCHAR(20) NOT NULL,       -- NAV, TRANSACTIONS
    filename        VARCHAR(500),
    rows_processed  INTEGER DEFAULT 0,
    rows_failed     INTEGER DEFAULT 0,
    clients_affected INTEGER DEFAULT 0,
    errors          JSONB DEFAULT '[]'::jsonb,
    uploaded_at     TIMESTAMP DEFAULT NOW()
);

-- ══════════════════════════════════════════════
-- 9. CASH FLOWS (capital inflows/outflows from PMS backoffice)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cpp_cash_flows (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    portfolio_id    INTEGER NOT NULL REFERENCES cpp_portfolios(id) ON DELETE CASCADE,
    flow_date       DATE NOT NULL,
    flow_type       VARCHAR(20) NOT NULL,       -- INFLOW, OUTFLOW
    amount          NUMERIC(18, 2) NOT NULL,
    description     VARCHAR(300),
    source_ucc      VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, portfolio_id, flow_date, flow_type, amount)
);

CREATE INDEX IF NOT EXISTS idx_cpp_cashflows_client
    ON cpp_cash_flows(client_id, portfolio_id, flow_date);

-- ══════════════════════════════════════════════
-- 10. SEED ADMIN USER
-- Password: change-me-immediately (bcrypt hash below)
-- Generate new hash: python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('change-me-immediately'))"
-- ══════════════════════════════════════════════
-- INSERT INTO cpp_clients (client_code, name, username, password_hash, is_admin)
-- VALUES ('ADMIN-001', 'System Admin', 'admin', '$2b$12$PLACEHOLDER_HASH_HERE', TRUE);

-- ══════════════════════════════════════════════
-- VERIFICATION
-- ══════════════════════════════════════════════
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' AND table_name LIKE 'cpp_%'
ORDER BY table_name;
