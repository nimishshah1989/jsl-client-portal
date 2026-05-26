"""Tests for audit-log integrity (M7).

The critical invariant exercised here is:

    A rolled-back BUSINESS transaction must NOT roll back the audit row.

This is mandated by SEBI — every attempted (even failed) mutation must
leave a trace. To meet this, ``log_audit`` writes on a fresh short-lived
connection from the engine via ``engine.begin()`` instead of using the
caller's request-scoped session.

We exercise the behaviour against an in-memory SQLite engine. The
``cpp_audit_log`` table uses JSONB in production, so the test mirrors the
schema with a portable JSON column rather than re-using the ORM model.
"""

from __future__ import annotations

import os

# Stub env vars BEFORE importing backend modules.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import pytest
import pytest_asyncio
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


# Portable audit-log table for SQLite (mirrors cpp_audit_log columns minus
# the Fernet-encrypted IP wrapper, which is unimportant for this test).
_test_metadata = MetaData()
_test_audit_table = Table(
    "cpp_audit_log",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=True),
    Column("action", String(50), nullable=False),
    Column("resource_type", String(50), nullable=False),
    Column("resource_id", Integer, nullable=True),
    Column("target_client_id", Integer, nullable=True),
    Column("ip_address", String(200), nullable=True),
    Column("user_agent", String(500), nullable=True),
    Column("request_id", String(36), nullable=True),
    Column("details", JSON, nullable=True),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)


@pytest_asyncio.fixture
async def audit_engine(monkeypatch):
    """In-memory engine shared by audit_service and the test assertions.

    We patch ``backend.services.audit_service.async_engine`` so that the
    real ``log_audit`` writes to our SQLite engine. The same engine is then
    used to assert the row is durable.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(_test_metadata.create_all)

    # Patch the engine reference inside audit_service. We must also patch
    # the insert statement to target our portable Table rather than the
    # ORM's AuditLog (whose JSONB column SQLite can't handle).
    from backend.services import audit_service

    monkeypatch.setattr(audit_service, "async_engine", engine)

    # Replace the imported insert target — the function body builds
    # ``insert(AuditLog).values(...)``. We re-bind ``AuditLog`` in that
    # module to our portable Table so insert() compiles for SQLite.
    monkeypatch.setattr(audit_service, "AuditLog", _test_audit_table)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def business_session(audit_engine) -> AsyncSession:
    """A separate session representing the caller's business transaction.

    Note: this binds to the SAME engine we patched into audit_service, but
    the test exercises the invariant that audit_service uses ``engine.begin()``
    (a fresh connection / transaction) rather than this session.
    """
    factory = async_sessionmaker(bind=audit_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── Tests ──


@pytest.mark.asyncio
async def test_audit_row_written_on_independent_transaction(audit_engine, business_session):
    """Baseline: log_audit writes a row even with no commit on business_session."""
    from backend.services.audit_service import log_audit

    await log_audit(
        business_session,
        user_id=42,
        action="VIEW",
        resource_type="PORTFOLIO",
        resource_id=7,
    )

    # Read back via a NEW connection — proves the row was actually committed,
    # not just buffered inside business_session's transaction.
    async with audit_engine.connect() as conn:
        result = await conn.execute(select(_test_audit_table))
        rows = result.fetchall()

    assert len(rows) == 1
    assert rows[0].user_id == 42
    assert rows[0].action == "VIEW"
    assert rows[0].resource_type == "PORTFOLIO"
    assert rows[0].resource_id == 7


@pytest.mark.asyncio
async def test_audit_row_survives_business_transaction_rollback(
    audit_engine, business_session
):
    """THE compliance invariant: if the business txn rolls back, the audit
    row must still be present.

    Sequence:
      1. business_session starts a transaction and dirties some state.
      2. log_audit() is called inside that transaction.
      3. business_session.rollback() throws away its own work.
      4. The audit row must still be visible from a fresh connection.
    """
    from backend.services.audit_service import log_audit

    # Force-open a transaction on the business session (so rollback() is meaningful).
    await business_session.execute(select(1))

    await log_audit(
        business_session,
        user_id=99,
        action="UPDATE",
        resource_type="HOLDINGS",
        resource_id=123,
        details={"reason": "simulated_failure"},
    )

    # Caller's business txn fails and is rolled back.
    await business_session.rollback()

    # Audit row must still be there — visible from a fresh connection.
    async with audit_engine.connect() as conn:
        result = await conn.execute(select(_test_audit_table))
        rows = result.fetchall()

    assert len(rows) == 1, (
        "Audit row was lost when the business transaction rolled back — "
        "SEBI compliance requires the audit trail to outlive failed mutations."
    )
    assert rows[0].user_id == 99
    assert rows[0].action == "UPDATE"
    assert rows[0].resource_type == "HOLDINGS"
    assert rows[0].resource_id == 123


@pytest.mark.asyncio
async def test_audit_failure_is_swallowed(audit_engine, business_session, monkeypatch):
    """If the audit write itself raises, the caller path must not break
    (fire-and-forget semantics). We simulate a broken engine and confirm
    log_audit returns normally."""
    from backend.services import audit_service

    class _BrokenEngine:
        def begin(self):  # noqa: D401 — simulate failure path
            raise RuntimeError("engine is down")

    monkeypatch.setattr(audit_service, "async_engine", _BrokenEngine())

    # Should NOT raise.
    await audit_service.log_audit(
        business_session,
        user_id=1,
        action="VIEW",
        resource_type="PORTFOLIO",
    )


@pytest.mark.asyncio
async def test_audit_accepts_none_session(audit_engine):
    """log_audit must accept db=None — new call sites shouldn't have to
    pass a session at all, since the function uses its own engine."""
    from backend.services.audit_service import log_audit

    await log_audit(
        None,
        user_id=5,
        action="LOGIN",
        resource_type="SYSTEM",
    )

    async with audit_engine.connect() as conn:
        result = await conn.execute(select(_test_audit_table))
        rows = result.fetchall()

    assert len(rows) == 1
    assert rows[0].action == "LOGIN"
