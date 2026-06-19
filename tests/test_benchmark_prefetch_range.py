"""Benchmark pre-fetch range must cover existing history, not just the file.

An incremental upload (file spans a few days) must still pre-fetch the Nifty
benchmark back to the earliest NAV already on record — otherwise
update_benchmark_values re-pulls each client's full multi-year range from
yfinance, 200+ times, and the upload crawls.
"""

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
from backend.services.ingestion_service import _benchmark_prefetch_range


@pytest_asyncio.fixture(scope="function")
async def db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(
            c, tables=[Client.__table__, Portfolio.__table__, NavSeries.__table__]))
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add(Client(id=1, client_code="BJ53", name="B", username="b",
                     password_hash="x", is_active=True, is_admin=False))
        s.add(Portfolio(id=10, client_id=1, portfolio_name="PMS Equity",
                        inception_date=dt.date(2021, 1, 4), client_code="BJ53",
                        strategy="LEADERS", is_closed=False))
        # Existing history goes back to 2021.
        s.add(NavSeries(client_id=1, portfolio_id=10, nav_date=dt.date(2021, 1, 4),
                        nav_value=Decimal("100"), current_value=Decimal("100"),
                        invested_amount=Decimal("100"), benchmark_value=Decimal("100")))
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_prefetch_widens_to_earliest_existing_nav(db):
    # Incremental file spans only 3 recent days...
    file_dates = {dt.date(2026, 6, 15), dt.date(2026, 6, 16), dt.date(2026, 6, 18)}
    async with db() as s:
        rng = await _benchmark_prefetch_range(s, file_dates)
    # ...but the pre-fetch must reach back to 2021 (the earliest stored NAV).
    assert rng == (dt.date(2021, 1, 4), dt.date(2026, 6, 18))


@pytest.mark.asyncio
async def test_prefetch_uses_file_range_when_no_history(db):
    # A first-ever upload (no earlier NAV than the file) keeps the file range.
    file_dates = {dt.date(2020, 1, 1), dt.date(2020, 1, 2)}
    async with db() as s:
        rng = await _benchmark_prefetch_range(s, file_dates)
    assert rng == (dt.date(2020, 1, 1), dt.date(2020, 1, 2))


@pytest.mark.asyncio
async def test_prefetch_none_when_no_dates(db):
    async with db() as s:
        assert await _benchmark_prefetch_range(s, set()) is None
