"""Tests for the combined-view service.

Covers the pure holdings merge and the DB-backed reconciliation invariant:
combined == sum of the client's LIVE portfolios (closed excluded).
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
from backend.services.combined_analytics import (
    get_combined_allocation,
    get_combined_drawdown_series,
    get_combined_performance_table,
    get_combined_risk_metrics,
)
from backend.services.combined_service import (
    get_combined_holdings,
    get_combined_nav_series,
    get_combined_summary,
    merge_holdings,
)


# ── Pure: merge_holdings ──

class TestMergeHoldings:
    def test_same_symbol_quantities_sum(self):
        rows = [
            {"symbol": "RELIANCE", "quantity": 10, "avg_cost": 100, "current_value": 1200,
             "current_price": 120, "unrealized_pnl": 200},
            {"symbol": "RELIANCE", "quantity": 4, "avg_cost": 110, "current_value": 480,
             "current_price": 120, "unrealized_pnl": 40},
        ]
        out = merge_holdings(rows)
        assert len(out) == 1
        assert out[0]["quantity"] == Decimal("14")
        assert out[0]["current_value"] == Decimal("1680")

    def test_weighted_average_cost(self):
        rows = [
            {"symbol": "X", "quantity": 10, "avg_cost": 100, "current_value": 0, "current_price": 0, "unrealized_pnl": 0},
            {"symbol": "X", "quantity": 30, "avg_cost": 200, "current_value": 0, "current_price": 0, "unrealized_pnl": 0},
        ]
        # (10*100 + 30*200) / 40 = 175
        assert merge_holdings(rows)[0]["avg_cost"] == Decimal("175")

    def test_distinct_symbols_and_weights_sum_to_100(self):
        rows = [
            {"symbol": "A", "quantity": 1, "avg_cost": 1, "current_value": 750, "current_price": 1, "unrealized_pnl": 0},
            {"symbol": "B", "quantity": 1, "avg_cost": 1, "current_value": 250, "current_price": 1, "unrealized_pnl": 0},
        ]
        out = merge_holdings(rows)
        weights = {o["symbol"]: o["weight_pct"] for o in out}
        assert weights["A"] == Decimal("75")
        assert weights["B"] == Decimal("25")
        assert sum(o["weight_pct"] for o in out) == Decimal("100")

    def test_sorted_by_value_desc(self):
        rows = [
            {"symbol": "small", "quantity": 1, "avg_cost": 1, "current_value": 10, "current_price": 1, "unrealized_pnl": 0},
            {"symbol": "big", "quantity": 1, "avg_cost": 1, "current_value": 90, "current_price": 1, "unrealized_pnl": 0},
        ]
        assert [o["symbol"] for o in merge_holdings(rows)] == ["big", "small"]


# ── DB-backed reconciliation ──

@pytest_asyncio.fixture(scope="function")
async def combined_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    tables = [Client.__table__, Portfolio.__table__, NavSeries.__table__, Holding.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add(Client(id=1, client_code="X1", name="X", username="x1", password_hash="x",
                     is_active=True, is_admin=False))
        # Two LIVE portfolios + one CLOSED (must be excluded).
        s.add(Portfolio(id=10, client_id=1, portfolio_name="Leaders", inception_date=dt.date(2024, 1, 1),
                        client_code="X1", strategy="LEADERS", is_closed=False))
        s.add(Portfolio(id=11, client_id=1, portfolio_name="Passive", inception_date=dt.date(2024, 1, 1),
                        client_code="X1PASS", strategy="PASSIVE", is_closed=False))
        s.add(Portfolio(id=12, client_id=1, portfolio_name="Closed", inception_date=dt.date(2024, 1, 1),
                        client_code="X1CLOSE", strategy="LEADERS", is_closed=True))

        def nav(pid, d, navv, inv, bench):
            return NavSeries(client_id=1, portfolio_id=pid, nav_date=d,
                             nav_value=Decimal(navv), current_value=Decimal(navv),
                             invested_amount=Decimal(inv), benchmark_value=Decimal(bench))
        d1, d2 = dt.date(2024, 1, 1), dt.date(2024, 6, 1)
        s.add_all([
            nav(10, d1, "100", "100", "200"), nav(10, d2, "120", "100", "210"),
            nav(11, d1, "50", "50", "200"),   nav(11, d2, "55", "50", "210"),
            nav(12, d2, "9999", "9999", "210"),  # CLOSED — must not appear
        ])

        def hold(pid, sym, qty, val):
            return Holding(client_id=1, portfolio_id=pid, symbol=sym, quantity=Decimal(qty),
                           avg_cost=Decimal("10"), current_price=Decimal("12"),
                           current_value=Decimal(val), unrealized_pnl=Decimal("0"))
        s.add_all([
            hold(10, "RELIANCE", "10", "120"), hold(10, "TCS", "5", "60"),
            hold(11, "RELIANCE", "4", "48"),   hold(11, "INFY", "3", "30"),
            hold(12, "RELIANCE", "999", "9999"),  # CLOSED — excluded
        ])
        await s.commit()
        try:
            yield Session
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_combined_nav_excludes_closed_and_sums(combined_db):
    async with combined_db() as s:
        pts = await get_combined_nav_series(s, client_id=1)
    last = pts[-1]
    assert last["nav"] == "175.00"        # 120 + 55, NOT + 9999
    assert last["invested"] == "150.00"   # 100 + 50


@pytest.mark.asyncio
async def test_combined_summary_reconciles(combined_db):
    async with combined_db() as s:
        summ = await get_combined_summary(s, client_id=1)
    assert summ["invested"] == "150.00"
    assert summ["current_value"] == "175.00"
    assert summ["profit_amount"] == "25.00"
    assert summ["portfolio_count"] == 2   # closed excluded


@pytest.mark.asyncio
async def test_combined_holdings_merge_excludes_closed(combined_db):
    async with combined_db() as s:
        rows = await get_combined_holdings(s, client_id=1)
    by_sym = {r["symbol"]: r for r in rows}
    # RELIANCE = 10 (Leaders) + 4 (Passive); the 999 from the closed portfolio is excluded.
    assert by_sym["RELIANCE"]["quantity"] == "14.00"
    assert by_sym["RELIANCE"]["current_value"] == "168.00"
    assert set(by_sym) == {"RELIANCE", "TCS", "INFY"}


@pytest.mark.asyncio
async def test_combined_allocation_excludes_closed_and_sums(combined_db):
    async with combined_db() as s:
        alloc = await get_combined_allocation(s, client_id=1)
    # All seeded holdings have no sector -> 'Other'. Live total 120+60+48+30 = 258
    # (the closed portfolio's 9999 is excluded).
    assert alloc["by_sector"] == [{"name": "Other", "value": "258.00", "weight_pct": "100.00"}]


@pytest.mark.asyncio
async def test_combined_analytics_run_and_exclude_closed(combined_db):
    async with combined_db() as s:
        risk = await get_combined_risk_metrics(s, client_id=1)
        perf = await get_combined_performance_table(s, client_id=1)
        dd = await get_combined_drawdown_series(s, client_id=1)
    # Built from the combined TWR series (live only: 150 -> 175), no exceptions.
    assert "cagr" in risk and "max_drawdown" in risk
    assert float(risk["cagr"]) > 0          # 150 -> 175 is a gain
    assert risk["max_drawdown"] == "0.00"   # monotonic up -> no drawdown
    assert isinstance(perf, list) and len(perf) >= 1
    assert len(dd) == 2                       # one point per nav date
