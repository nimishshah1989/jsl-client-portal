"""Tests for the active/inactive portfolio filter + admin summary table."""

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
from backend.models.cash_flow import CashFlow
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from backend.services import aggregate_service
from backend.services.aggregate_service import get_aggregate_summary_table
from backend.services.strategy_filter import active_clause, active_params


# ── Pure helpers ──

def test_active_clause_and_params_gate_together():
    cutoff = dt.date(2026, 5, 1)
    # active-only with a cutoff → clause emitted, bind present
    assert ":active_cutoff" in active_clause(False, cutoff, "n")
    assert active_params(False, cutoff) == {"active_cutoff": cutoff}
    # include_inactive → no clause, no bind
    assert active_clause(True, cutoff, "n") == ""
    assert active_params(True, cutoff) == {}
    # no cutoff (no NAV data) → no clause, no bind (avoids an unbound :active_cutoff)
    assert active_clause(False, None, "n") == ""
    assert active_params(False, None) == {}


# ── DB-backed: active filter + summary table ──

@pytest_asyncio.fixture(scope="function")
async def agg_db():
    aggregate_service._cache.clear()  # module-global cache is keyed by strategy only
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    tables = [Client.__table__, Portfolio.__table__, NavSeries.__table__, CashFlow.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    today = dt.date.today()
    def ago(n): return today - dt.timedelta(days=n)

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add_all([
            Client(id=1, client_code="ACT", name="Active", username="act",
                   password_hash="x", is_active=True, is_admin=False),
            Client(id=2, client_code="STALE", name="Stale", username="stale",
                   password_hash="x", is_active=True, is_admin=False),
        ])
        s.add_all([
            Portfolio(id=10, client_id=1, portfolio_name="A", inception_date=ago(5),
                      client_code="ACT", strategy="LEADERS", is_closed=False),
            Portfolio(id=11, client_id=2, portfolio_name="B", inception_date=ago(65),
                      client_code="STALE", strategy="LEADERS", is_closed=False),
        ])

        def nav(pid, cid, d, v, inv):
            return NavSeries(client_id=cid, portfolio_id=pid, nav_date=d,
                             nav_value=Decimal(v), current_value=Decimal(v),
                             invested_amount=Decimal(inv), benchmark_value=Decimal("100"))
        # Active sleeve: reports through today.
        for i in range(6):
            s.add(nav(10, 1, ago(5 - i), str(950 + i * 10), "900"))
        # Stale sleeve: last NAV 60 days ago (> 30-day window → inactive).
        for i in range(6):
            s.add(nav(11, 2, ago(65 - i), "500", "500"))
        # Flows in the rolling-30-day window on the active sleeve.
        s.add(CashFlow(client_id=1, portfolio_id=10, flow_date=ago(10),
                       flow_type="INFLOW", amount=Decimal("200")))
        s.add(CashFlow(client_id=1, portfolio_id=10, flow_date=ago(5),
                       flow_type="OUTFLOW", amount=Decimal("50")))
        # Old flow on the stale sleeve — outside the 30-day window.
        s.add(CashFlow(client_id=2, portfolio_id=11, flow_date=ago(62),
                       flow_type="INFLOW", amount=Decimal("999")))
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_summary_table_excludes_inactive_by_default(agg_db):
    async with agg_db() as s:
        table = await get_aggregate_summary_table(s, include_inactive=False)
    combined = table["buckets"]["COMBINED"]
    # Active-only: stale sleeve (₹500) excluded → AUM = active sleeve's latest (₹1000).
    assert combined["total_aum"] == 1000
    assert combined["deposits_30d"] == 200      # the ₹999 inflow is 62 days old
    assert combined["withdrawals_30d"] == 50
    assert "cagr" in combined and "max_drawdown" in combined


@pytest.mark.asyncio
async def test_summary_table_includes_inactive_when_flagged(agg_db):
    async with agg_db() as s:
        table = await get_aggregate_summary_table(s, include_inactive=True)
    combined = table["buckets"]["COMBINED"]
    # Include all: stale sleeve's last value (₹500) is added → AUM = 1500.
    assert combined["total_aum"] == 1500
    assert table["include_inactive"] is True
    assert table["window_days"] == 30
