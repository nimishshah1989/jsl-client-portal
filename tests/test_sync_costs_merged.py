"""Sync Costs must update holdings keyed by the PORTFOLIO's source code.

Reconciliation reports each COST_MISMATCH against the sleeve's source UCC
(cpp_portfolios.client_code). After the unified-login merge that code may be a
retired alias whose client_id differs from the survivor that owns the holding
row. The old endpoint joined cpp_clients.client_code, so the UPDATE matched
zero rows for every merged client (prod 2026-06-19: ATHERENERG on BJ53MF never
synced). The fix joins cpp_portfolios.client_code instead.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import datetime as dt
import sqlite3
import tempfile
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# asyncpg (prod) binds Decimal natively; the SQLite test driver does not, so
# teach it to accept Decimal for the raw-text UPDATE the endpoint runs.
sqlite3.register_adapter(Decimal, str)

from backend.database import Base
from backend.models.client import Client
from backend.models.holding import Holding
from backend.models.portfolio import Portfolio
from backend.routers.admin_reconciliation import _apply_cost_sync


@pytest_asyncio.fixture(scope="function")
async def merged_db():
    """Survivor client BJ53 (id 1) owns a sleeve whose source code is the
    retired alias BJ53MF — the post-merge shape. The holding row's client_id is
    the survivor (1), NOT the alias (2)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    tables = [Client.__table__, Portfolio.__table__, Holding.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add(Client(id=1, client_code="BJ53", name="BHADERESH JITENDRA JHAVERI",
                     username="bj53", password_hash="x", is_active=True, is_admin=False))
        # Retired alias for the MF sleeve — merged into the survivor.
        s.add(Client(id=2, client_code="BJ53MF", name="BHADERESH JITENDRA JHAVERI",
                     username="bj53mf", password_hash="x", is_active=False,
                     is_admin=False, merged_into=1))
        # The sleeve carries its own source code but lives under the survivor.
        s.add(Portfolio(id=11, client_id=1, portfolio_name="PMS Equity (BJ53MF)",
                        inception_date=dt.date(2024, 1, 1), client_code="BJ53MF",
                        strategy="LEADERS", is_closed=False))
        # Holding row's client_id is the SURVIVOR (1), not the alias (2).
        s.add(Holding(client_id=1, portfolio_id=11, symbol="ATHERENERG",
                      isin="INE0LEZ01016", quantity=Decimal("60"),
                      avg_cost=Decimal("1051.5524"),
                      current_price=Decimal("963.85"),
                      current_value=Decimal("57831.00")))
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_costs_updates_merged_sleeve(merged_db):
    """A COST_MISMATCH reported against the sleeve code BJ53MF must land on the
    survivor-owned holding — the regression updated zero rows."""
    async with merged_db() as s:
        changed = await _apply_cost_sync(
            s, [("BJ53MF", "ATHERENERG", Decimal("1058.53"))]
        )
        await s.commit()

        assert changed == 1, "expected the survivor-owned holding to be updated"

        h = (await s.execute(
            select(Holding).where(Holding.symbol == "ATHERENERG")
        )).scalar_one()
        assert h.avg_cost == Decimal("1058.53")
        # P&L recomputed off the new cost: (963.85 - 1058.53) * 60 = -5680.80.
        # SQLite does the arithmetic in float, so compare with a cent tolerance.
        expected_pnl = (Decimal("963.85") - Decimal("1058.53")) * 60
        assert abs(h.unrealized_pnl - expected_pnl) < Decimal("0.01")


@pytest.mark.asyncio
async def test_sync_costs_no_match_reports_zero(merged_db):
    """An unknown sleeve code changes nothing and is reported honestly as 0 —
    not silently counted as 'processed'."""
    async with merged_db() as s:
        changed = await _apply_cost_sync(
            s, [("NOSUCHCODE", "ATHERENERG", Decimal("999"))]
        )
        await s.commit()
        assert changed == 0
        h = (await s.execute(
            select(Holding).where(Holding.symbol == "ATHERENERG")
        )).scalar_one()
        assert h.avg_cost == Decimal("1051.5524")  # untouched
