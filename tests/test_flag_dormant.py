"""Tests for dormant/empty portfolio detection (flag_dormant_portfolios)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import datetime as dt
import tempfile
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from scripts.flag_dormant_portfolios import find_dormant_portfolios


@pytest_asyncio.fixture(scope="function")
async def db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(
            c, tables=[Client.__table__, Portfolio.__table__, NavSeries.__table__]))
    today = dt.date.today()

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add(Client(id=1, client_code="C", name="C", username="c",
                     password_hash="x", is_active=True, is_admin=False))
        s.add_all([
            Portfolio(id=10, client_id=1, portfolio_name="current", inception_date=today,
                      client_code="CUR", strategy="LEADERS", is_closed=False),
            Portfolio(id=11, client_id=1, portfolio_name="dormant", inception_date=today,
                      client_code="DORM", strategy="LEADERS", is_closed=False),
            Portfolio(id=12, client_id=1, portfolio_name="empty", inception_date=today,
                      client_code="JA59", strategy="LEADERS", is_closed=False),
            Portfolio(id=13, client_id=1, portfolio_name="already-closed", inception_date=today,
                      client_code="OLD", strategy="LEADERS", is_closed=True),
        ])

        def nav(pid, d, v):
            return NavSeries(client_id=1, portfolio_id=pid, nav_date=d,
                             nav_value=Decimal(v), current_value=Decimal(v),
                             invested_amount=Decimal(v))
        # current: through today; dormant: ended 200 days ago; closed: through today
        s.add_all([
            nav(10, today, "1000"),
            nav(11, today - dt.timedelta(days=200), "500"),
            nav(13, today, "9999"),
        ])
        # pf 12 (empty) has NO nav rows
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_finds_stale_and_empty_not_current_or_closed(db):
    async with db() as s:
        found = await find_dormant_portfolios(s, days=90, include_empty=True)
    ids = {r["id"] for r in found}
    assert ids == {11, 12}                     # dormant + empty
    assert 10 not in ids                        # current → kept
    assert 13 not in ids                        # already closed → not re-flagged


@pytest.mark.asyncio
async def test_no_empty_flag_excludes_no_nav_stub(db):
    async with db() as s:
        found = await find_dormant_portfolios(s, days=90, include_empty=False)
    ids = {r["id"] for r in found}
    assert ids == {11}                          # only the stale one; empty stub skipped
