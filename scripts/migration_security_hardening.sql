-- ══════════════════════════════════════════════════════════════════
-- SECURITY HARDENING MIGRATION
-- Run: psql -h $DB_HOST -U fie_admin -d client_portal -f scripts/migration_security_hardening.sql
-- ══════════════════════════════════════════════════════════════════

BEGIN;

-- ──────────────────────────────────────────────
-- 1. AUDIT LOG TABLE (SEBI compliance)
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cpp_audit_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES cpp_clients(id) ON DELETE SET NULL,
    action          VARCHAR(50) NOT NULL,
    resource_type   VARCHAR(50) NOT NULL,
    resource_id     INTEGER,
    target_client_id INTEGER REFERENCES cpp_clients(id) ON DELETE SET NULL,
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(500),
    request_id      VARCHAR(36),
    details         JSONB,
    created_at      TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_user_id ON cpp_audit_log(user_id);
CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_target_client_id ON cpp_audit_log(target_client_id);
CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_request_id ON cpp_audit_log(request_id);
CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_action_created ON cpp_audit_log(action, created_at);
CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_target_created ON cpp_audit_log(target_client_id, created_at);

-- ──────────────────────────────────────────────
-- 2. CLIENT CONSENT TABLE (SEBI compliance)
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cpp_client_consents (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES cpp_clients(id) ON DELETE CASCADE,
    consent_type    VARCHAR(100) NOT NULL,
    accepted        BOOLEAN NOT NULL DEFAULT FALSE,
    accepted_at     TIMESTAMP,
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(500),
    document_version VARCHAR(20) NOT NULL DEFAULT '1.0',
    revoked_at      TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_cpp_client_consents_client_id ON cpp_client_consents(client_id);

-- ──────────────────────────────────────────────
-- 3. SOFT DELETE + RBAC on cpp_clients
-- ──────────────────────────────────────────────
ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'CLIENT';
ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS deleted_by INTEGER REFERENCES cpp_clients(id) ON DELETE SET NULL;

-- ──────────────────────────────────────────────
-- 4. SOFT DELETE + updated_at on cpp_transactions
-- ──────────────────────────────────────────────
ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS deleted_by INTEGER REFERENCES cpp_clients(id) ON DELETE SET NULL;

-- ──────────────────────────────────────────────
-- 5. updated_at on cpp_portfolios
-- ──────────────────────────────────────────────
ALTER TABLE cpp_portfolios ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- ──────────────────────────────────────────────
-- 6. updated_at on cpp_holdings
-- ──────────────────────────────────────────────
ALTER TABLE cpp_holdings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- ──────────────────────────────────────────────
-- VERIFICATION
-- ──────────────────────────────────────────────
SELECT 'cpp_audit_log' AS tbl, count(*) FROM cpp_audit_log
UNION ALL
SELECT 'cpp_client_consents', count(*) FROM cpp_client_consents;

SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'cpp_clients' AND column_name IN ('role', 'updated_at', 'is_deleted', 'deleted_at', 'deleted_by')
ORDER BY column_name;

COMMIT;
