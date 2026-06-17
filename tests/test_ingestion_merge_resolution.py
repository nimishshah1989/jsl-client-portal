"""Ingestion must resolve merged (retired) codes to the survivor and reuse the
existing portfolio — the PR7b idempotency that the first post-merge upload needs.

Reproduces the prod failure: uploading data for code AC04 (retired onto survivor
AC04MF by the unified-login merge) raised
``duplicate key value violates unique constraint "uq_cpp_portfolios_client_code"``
because ingestion tried to recreate AC04's portfolio under the retired client.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import datetime as dt
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models.client import Client
from backend.models.portfolio import Portfolio
from backend.services.ingestion_helpers import (
    find_or_create_client,
    find_or_create_portfolio,
)


@pytest_asyncio.fixture(scope="function")
async def merged_db():
    """Post-merge shape: AMITKUMAR's two codes unified onto survivor AC04MF (id 13).

    - Survivor (13) owns "PMS Equity" (code AC04MF) + the re-parented
      "PMS Equity (AC04)" (code AC04, renamed during the merge).
    - Retired client (14, code AC04) has merged_into=13 and owns NO portfolio.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Client.__table__, Portfolio.__table__]
            )
        )
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add_all([
            Client(id=13, client_code="AC04MF", name="AMITKUMAR MANHARLAL CHOKSHI",
                   username="ac04mf", password_hash="x", is_active=True),
            Client(id=14, client_code="AC04", name="AMITKUMAR MANHARLAL CHOKSHI",
                   username="ac04", password_hash="x", is_active=True, merged_into=13),
        ])
        s.add_all([
            Portfolio(id=100, client_id=13, portfolio_name="PMS Equity",
                      client_code="AC04MF", strategy="LEADERS", is_closed=False,
                      inception_date=dt.date(2024, 1, 1)),
            Portfolio(id=101, client_id=13, portfolio_name="PMS Equity (AC04)",
                      client_code="AC04", strategy="LEADERS", is_closed=False,
                      inception_date=dt.date(2024, 1, 1)),
        ])
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_retired_code_resolves_to_survivor_and_reuses_portfolio(merged_db):
    async with merged_db() as s:
        # A new upload for the RETIRED code AC04:
        cid = await find_or_create_client(s, "AC04", "AMITKUMAR MANHARLAL CHOKSHI")
        assert cid == 13, "retired code must follow merged_into to the survivor"

        pid = await find_or_create_portfolio(s, cid, dt.date(2026, 6, 12), "AC04")
        assert pid == 101, "must reuse the re-parented portfolio, not recreate it"

        # The survivor's OWN code still maps to its own portfolio.
        pid_own = await find_or_create_portfolio(s, cid, dt.date(2026, 6, 12), "AC04MF")
        assert pid_own == 100

        await s.commit()  # would raise IntegrityError under the old code path

        # No phantom portfolios created.
        n = (await s.execute(select(func.count()).select_from(Portfolio))).scalar()
        assert n == 2


@pytest.mark.asyncio
async def test_new_code_still_creates_client_and_portfolio(merged_db):
    """Regression guard: a genuinely new code still creates its client + portfolio."""
    async with merged_db() as s:
        cid = await find_or_create_client(s, "ZZ99", "BRAND NEW CLIENT")
        assert cid not in (13, 14)
        pid = await find_or_create_portfolio(s, cid, dt.date(2026, 6, 12), "ZZ99")
        await s.commit()
        code = (await s.execute(
            text("SELECT client_code FROM cpp_portfolios WHERE id = :id"), {"id": pid}
        )).scalar()
        assert code == "ZZ99"
        n = (await s.execute(select(func.count()).select_from(Portfolio))).scalar()
        assert n == 3  # the two seeded + the new one
