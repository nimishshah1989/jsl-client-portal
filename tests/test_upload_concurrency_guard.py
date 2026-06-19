"""A second upload of the same type must be rejected while one is processing.

Prevents a double-click / re-submit from spawning concurrent ingestion jobs
(prod incident 2026-06-19: 3 parallel jobs thrashing the DB + yfinance).
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import datetime as dt
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.routers.admin_upload import _UPLOAD_STALE_MINUTES, _active_upload_in_progress

# cpp_upload_log has a Postgres JSONB column that won't compile on SQLite, so
# build a minimal table with just the columns the guard query reads.
_DDL = """
    CREATE TABLE cpp_upload_log (
        id INTEGER PRIMARY KEY,
        file_type TEXT,
        status TEXT,
        started_at TIMESTAMP
    )
"""


@pytest_asyncio.fixture(scope="function")
async def db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.execute(text(_DDL))
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield Session
    finally:
        await engine.dispose()


async def _insert(s, file_type, status, started_at):
    await s.execute(
        text("INSERT INTO cpp_upload_log (file_type, status, started_at) "
             "VALUES (:ft, :st, :sa)"),
        {"ft": file_type, "st": status, "sa": started_at},
    )
    await s.commit()


@pytest.mark.asyncio
async def test_blocks_when_same_type_processing(db):
    now = dt.datetime.utcnow()
    async with db() as s:
        await _insert(s, "NAV", "processing", now - dt.timedelta(minutes=2))
        assert await _active_upload_in_progress(s, "NAV", now=now) is True
        # A different file type is independent.
        assert await _active_upload_in_progress(s, "TRANSACTIONS", now=now) is False


@pytest.mark.asyncio
async def test_completed_does_not_block(db):
    now = dt.datetime.utcnow()
    async with db() as s:
        await _insert(s, "NAV", "completed", now - dt.timedelta(minutes=2))
        assert await _active_upload_in_progress(s, "NAV", now=now) is False


@pytest.mark.asyncio
async def test_stale_processing_does_not_block(db):
    """An orphaned 'processing' row (older than the window — e.g. killed by a
    restart) must not wedge uploads forever."""
    now = dt.datetime.utcnow()
    async with db() as s:
        await _insert(s, "NAV", "processing",
                      now - dt.timedelta(minutes=_UPLOAD_STALE_MINUTES + 5))
        assert await _active_upload_in_progress(s, "NAV", now=now) is False
