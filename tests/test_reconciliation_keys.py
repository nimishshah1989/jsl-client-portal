"""Reconciliation must key by the PORTFOLIO's source code, not the client's.

After the unified-login merge a single client owns several portfolios, each
carrying its own source UCC (cpp_portfolios.client_code). The reconciliation
loaders must bucket holdings / NAVs by that per-sleeve code — keying by the
owning client's code collapses every sleeve under the survivor's code, which
floods one BO sheet with EXTRA_IN_OURS and leaves the other codes MISSING.
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
from backend.models.holding import Holding
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from backend.models.transaction import Transaction
from backend.services.reconciliation_service import (
    _load_latest_navs,
    _load_our_holdings,
)


@pytest_asyncio.fixture(scope="function")
async def merged_db():
    """One survivor client (code BJ53) owning TWO sleeves with distinct source
    codes (BJ53 + BJ53MF) — the post-merge shape. Each sleeve holds a different
    stock and has its own NAV row."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    tables = [
        Client.__table__, Portfolio.__table__, NavSeries.__table__,
        Holding.__table__, Transaction.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        # Survivor client (code BJ53) owns both sleeves after the merge.
        s.add(Client(id=1, client_code="BJ53", name="BHADERESH JITENDRA JHAVERI",
                     username="bj53", password_hash="x", is_active=True, is_admin=False))
        s.add_all([
            Portfolio(id=10, client_id=1, portfolio_name="PMS Equity",
                      inception_date=dt.date(2024, 1, 1), client_code="BJ53",
                      strategy="LEADERS", is_closed=False),
            Portfolio(id=11, client_id=1, portfolio_name="PMS Equity (BJ53MF)",
                      inception_date=dt.date(2024, 1, 1), client_code="BJ53MF",
                      strategy="LEADERS", is_closed=False),
        ])
        # Each sleeve holds a DIFFERENT stock (both owned by client 1).
        s.add(Holding(client_id=1, portfolio_id=10, symbol="RELIANCE", isin="INE002A01018",
                      quantity=Decimal("10"), avg_cost=Decimal("100"),
                      current_price=Decimal("120"), current_value=Decimal("1200")))
        s.add(Holding(client_id=1, portfolio_id=11, symbol="TCS", isin="INE467B01029",
                      quantity=Decimal("5"), avg_cost=Decimal("200"),
                      current_price=Decimal("210"), current_value=Decimal("1050")))
        s.add_all([
            NavSeries(client_id=1, portfolio_id=10, nav_date=dt.date(2026, 6, 12),
                      nav_value=Decimal("1200"), current_value=Decimal("1200"),
                      invested_amount=Decimal("1000"), benchmark_value=Decimal("100")),
            NavSeries(client_id=1, portfolio_id=11, nav_date=dt.date(2026, 6, 12),
                      nav_value=Decimal("1050"), current_value=Decimal("1050"),
                      invested_amount=Decimal("1000"), benchmark_value=Decimal("100")),
        ])
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_holdings_keyed_by_sleeve_code_not_survivor(merged_db):
    async with merged_db() as s:
        by_symbol, by_isin, names = await _load_our_holdings(s)

    # Each sleeve's holdings sit under its OWN code — not collapsed under BJ53.
    assert set(by_symbol.keys()) == {"BJ53", "BJ53MF"}
    assert set(by_symbol["BJ53"].keys()) == {"RELIANCE"}
    assert set(by_symbol["BJ53MF"].keys()) == {"TCS"}
    # The merge-bug symptom would be: BJ53 holds BOTH stocks, BJ53MF absent.
    assert "TCS" not in by_symbol["BJ53"]
    assert names["BJ53MF"] == "BHADERESH JITENDRA JHAVERI"


@pytest.mark.asyncio
async def test_navs_keyed_by_sleeve_code_not_survivor(merged_db):
    async with merged_db() as s:
        navs = await _load_latest_navs(s)

    assert set(navs.keys()) == {"BJ53", "BJ53MF"}
    assert navs["BJ53"]["nav_value"] == Decimal("1200")
    assert navs["BJ53MF"]["nav_value"] == Decimal("1050")
