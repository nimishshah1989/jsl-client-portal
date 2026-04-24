"""Run-once schema migration — safe to execute on every container start.

Uses ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS so it's idempotent.
"""

import logging
import sys

from sqlalchemy import create_engine, text

from backend.config import get_settings

logging.basicConfig(level=logging.INFO, format="[MIGRATE] %(message)s")
logger = logging.getLogger(__name__)

_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS cpp_audit_log (
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
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_user_id ON cpp_audit_log(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_target_client_id ON cpp_audit_log(target_client_id)",
    "CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_request_id ON cpp_audit_log(request_id)",
    "CREATE INDEX IF NOT EXISTS ix_cpp_audit_log_action_created ON cpp_audit_log(action, created_at)",
    """CREATE TABLE IF NOT EXISTS cpp_client_consents (
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
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cpp_client_consents_client_id ON cpp_client_consents(client_id)",
    "ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'CLIENT'",
    "ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
    "ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
    "ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
    "ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS deleted_by INTEGER REFERENCES cpp_clients(id) ON DELETE SET NULL",
    "ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
    "ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
    "ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
    "ALTER TABLE cpp_transactions ADD COLUMN IF NOT EXISTS deleted_by INTEGER REFERENCES cpp_clients(id) ON DELETE SET NULL",
    "ALTER TABLE cpp_portfolios ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
    "ALTER TABLE cpp_holdings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
    """CREATE TABLE IF NOT EXISTS cpp_bo_holdings_snapshot (
        id              SERIAL PRIMARY KEY,
        snapshot_type   VARCHAR(20) NOT NULL,
        market_date     DATE,
        filename        TEXT,
        uploaded_at     TIMESTAMP NOT NULL DEFAULT NOW(),
        records         JSONB NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cpp_bo_snapshot_type_uploaded ON cpp_bo_holdings_snapshot(snapshot_type, uploaded_at DESC)",
]


def run_migration() -> None:
    settings = get_settings()
    sync_url = settings.DATABASE_URL_SYNC
    if not sync_url:
        logger.error("No DATABASE_URL_SYNC — cannot run migration")
        sys.exit(1)

    logger.info("Connecting to database...")
    engine = create_engine(
        sync_url,
        pool_pre_ping=True,
        connect_args={"sslmode": "require"},
    )

    try:
        with engine.begin() as conn:
            for i, stmt in enumerate(_STATEMENTS, 1):
                conn.execute(text(stmt))
                logger.info("  [%d/%d] OK", i, len(_STATEMENTS))
        logger.info("Migration complete — all tables and columns verified")
    except Exception:
        logger.exception("Migration failed")
        sys.exit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
