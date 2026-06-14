"""Tests for the admin dashboard analytics — per-portfolio aggregation.

Guards the PR7 unified-login regression: once a person owns several portfolios
(merge re-parents their sleeves onto one survivor client), the firm StatCards
must sum EVERY sleeve, not one-per-client. The old ``DISTINCT ON (client_id)``
query would have returned only one of the unified client's sleeves and
undercounted Total AUM / Invested / blended CAGR.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import datetime as dt
import tempfile
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from backend.models.risk_metric import RiskMetric
from backend.services import aggregate_service
from backend.services.admin_analytics import _finite, compute_dashboard_analytics
from backend.services.aggregate_service import get_aggregate_risk_metrics

# cpp_upload_log uses a Postgres JSONB column that won't compile on SQLite, so we
# create a minimal version (just the columns the analytics query reads) by hand.
_UPLOAD_LOG_DDL = """
    CREATE TABLE cpp_upload_log (
        id INTEGER PRIMARY KEY,
        file_type TEXT,
        filename TEXT,
        rows_processed INTEGER,
        clients_affected INTEGER,
        uploaded_at TEXT
    )
"""


@pytest_asyncio.fixture(scope="function")
async def analytics_db():
    """Seed a post-merge-shaped DB:

    - UNIFIED (client 1): one survivor owning THREE active sleeves (LEADERS,
      PASSIVE, IND11) — simulates a merged person. AUM 1000 + 500 + 300 = 1800.
    - SOLO (client 2): a single-sleeve LEADERS client. AUM 400.
    - CLOSED (client 3): a closed sleeve — must be excluded everywhere.
    - STALE (client 4): a dormant sleeve (last NAV 60 days ago) — excluded by
      default, included only when include_inactive=True. AUM 200.
    - ADMIN (client 9): excluded (is_admin).
    """
    # The composite is cached module-globally by (strategy, active); clear it so
    # one test's data can't leak into another now that compute_dashboard_analytics
    # delegates the headline metrics to get_aggregate_risk_metrics.
    aggregate_service._cache.clear()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    tables = [
        Client.__table__, Portfolio.__table__, NavSeries.__table__,
        RiskMetric.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        await conn.execute(text(_UPLOAD_LOG_DDL))

    today = dt.date.today()

    def ago(n):
        return today - dt.timedelta(days=n)

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add_all([
            Client(id=1, client_code="UNI", name="Unified Person", username="uni",
                   password_hash="x", is_active=True, is_admin=False),
            Client(id=2, client_code="SOLO", name="Solo Person", username="solo",
                   password_hash="x", is_active=True, is_admin=False),
            Client(id=3, client_code="CLO", name="Closed Person", username="clo",
                   password_hash="x", is_active=True, is_admin=False),
            Client(id=4, client_code="STALE", name="Stale Person", username="stale",
                   password_hash="x", is_active=True, is_admin=False),
            Client(id=9, client_code="ADM", name="Admin", username="adm",
                   password_hash="x", is_active=True, is_admin=True),
        ])
        # Unified person's three sleeves (all owned by client 1 post-merge).
        s.add_all([
            Portfolio(id=10, client_id=1, portfolio_name="PMS Equity (UNI)",
                      inception_date=ago(400), client_code="UNI",
                      strategy="LEADERS", is_closed=False),
            Portfolio(id=11, client_id=1, portfolio_name="PMS Equity (UNIPASS)",
                      inception_date=ago(400), client_code="UNIPASS",
                      strategy="PASSIVE", is_closed=False),
            Portfolio(id=12, client_id=1, portfolio_name="PMS Equity (UNIIND)",
                      inception_date=ago(400), client_code="UNIIND",
                      strategy="IND11", is_closed=False),
            Portfolio(id=20, client_id=2, portfolio_name="PMS Equity (SOLO)",
                      inception_date=ago(400), client_code="SOLO",
                      strategy="LEADERS", is_closed=False),
            Portfolio(id=30, client_id=3, portfolio_name="PMS Equity (CLO)",
                      inception_date=ago(400), client_code="CLO",
                      strategy="LEADERS", is_closed=True),
            Portfolio(id=40, client_id=4, portfolio_name="PMS Equity (STALE)",
                      inception_date=ago(400), client_code="STALE",
                      strategy="LEADERS", is_closed=False),
            Portfolio(id=90, client_id=9, portfolio_name="PMS Equity (ADM)",
                      inception_date=ago(400), client_code="ADM",
                      strategy="LEADERS", is_closed=False),
        ])

        def nav(pid, cid, d, v, inv, cash=None):
            return NavSeries(
                client_id=cid, portfolio_id=pid, nav_date=d,
                nav_value=Decimal(v), current_value=Decimal(v),
                invested_amount=Decimal(inv), benchmark_value=Decimal("100"),
                cash_value=Decimal(cash) if cash is not None else None,
            )

        # Each portfolio gets an older + a latest row, so per-portfolio-latest
        # selection (not just "any row") is exercised.
        seeds = [
            (10, 1, "1000", "800", "100"),   # latest AUM 1000, invested 800, cash 100
            (11, 1, "500", "450", "50"),     # latest AUM 500,  invested 450, cash 50
            (12, 1, "300", "250", "0"),      # latest AUM 300,  invested 250
            (20, 2, "400", "350", "40"),     # solo
            (30, 3, "9999", "9999", "0"),    # closed — must never count
            (90, 9, "7777", "7777", "0"),    # admin — must never count
        ]
        for pid, cid, v, inv, cash in seeds:
            s.add(nav(pid, cid, ago(10), str(int(v) - 50), inv, cash))  # older
            s.add(nav(pid, cid, ago(2), v, inv, cash))                  # latest
        # Stale sleeve: last NAV 60 days ago → inactive under the 30-day window.
        s.add(nav(40, 4, ago(65), "200", "180", "20"))
        s.add(nav(40, 4, ago(60), "200", "180", "20"))

        def risk(pid, cid, cagr, dd, sharpe, xirr):
            return RiskMetric(
                client_id=cid, portfolio_id=pid, computed_date=ago(2),
                cagr=Decimal(cagr), max_drawdown=Decimal(dd),
                sharpe_ratio=Decimal(sharpe), xirr=Decimal(xirr),
            )

        s.add_all([
            risk(10, 1, "20", "-10", "1.5", "21"),
            risk(11, 1, "10", "-5", "0.8", "11"),
            risk(12, 1, "30", "-15", "2.0", "31"),
            risk(20, 2, "12", "-8", "1.0", "13"),
            risk(30, 3, "99", "-1", "9.0", "99"),    # closed
            risk(40, 4, "5", "-20", "0.2", "5"),     # stale
            risk(90, 9, "88", "-1", "8.0", "88"),    # admin
        ])
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_statcards_sum_every_sleeve_of_a_unified_client(analytics_db):
    """The core fix: Total AUM/Invested sum all of a unified client's sleeves."""
    async with analytics_db() as s:
        out = await compute_dashboard_analytics(s, "COMBINED", include_inactive=False)

    # Unified (1000+500+300) + Solo (400) = 2200. Closed/admin/stale excluded.
    assert out["total_aum"] == 2200.0
    # Invested: 800+450+250 + 350 = 1850.
    assert out["total_invested"] == 1850.0
    # Two distinct people in scope (unified counts once, not 3×).
    assert out["total_clients"] == 2
    # Cash: 100+50+0 + 40 = 190.
    assert out["total_cash"] == 190.0


@pytest.mark.asyncio
async def test_unified_client_is_one_performer_row_with_combined_aum(analytics_db):
    """Performer lists roll a person's sleeves into ONE row (UI keys on client_id)."""
    async with analytics_db() as s:
        out = await compute_dashboard_analytics(s, "COMBINED", include_inactive=False)

    ids = [p["client_id"] for p in out["top_by_nav"]]
    assert ids.count(1) == 1, "unified client must appear exactly once"
    uni = next(p for p in out["top_by_nav"] if p["client_id"] == 1)
    assert uni["aum"] == 1800.0          # 1000 + 500 + 300
    assert uni["invested"] == 1500.0     # 800 + 450 + 250
    # AUM-weighted CAGR: (20*1000 + 10*500 + 30*300)/1800 = 34000/1800 = 18.89
    assert uni["cagr"] == pytest.approx(18.89, abs=0.01)


@pytest.mark.asyncio
async def test_closed_and_admin_excluded(analytics_db):
    """Closed sleeves and admin accounts never contribute to any total."""
    async with analytics_db() as s:
        out = await compute_dashboard_analytics(s, "COMBINED", include_inactive=True)
    # Even with include_inactive, the 9999 closed + 7777 admin must be absent.
    assert out["total_aum"] == 2400.0   # 2200 + stale 200; NOT +9999/+7777
    codes = {p["client_code"] for p in out["top_by_nav"]}
    assert "CLO" not in codes
    assert "ADM" not in codes


@pytest.mark.asyncio
async def test_stale_sleeve_excluded_by_default_included_when_flagged(analytics_db):
    """Dormant sleeves drop out of active-only and reappear with include_inactive."""
    async with analytics_db() as s:
        active = await compute_dashboard_analytics(s, "COMBINED", include_inactive=False)
        allp = await compute_dashboard_analytics(s, "COMBINED", include_inactive=True)
    assert active["total_aum"] == 2200.0          # stale excluded
    assert allp["total_aum"] == 2400.0            # + stale 200
    assert active["total_clients"] == 2
    assert allp["total_clients"] == 3             # stale person now counted


@pytest.mark.asyncio
async def test_strategy_filter_scopes_to_one_sleeve(analytics_db):
    """A single-strategy view sums only that strategy's portfolios."""
    async with analytics_db() as s:
        passive = await compute_dashboard_analytics(s, "PASSIVE", include_inactive=False)
    # Only the unified client's PASSIVE sleeve (AUM 500).
    assert passive["total_aum"] == 500.0
    assert passive["total_clients"] == 1


@pytest.mark.asyncio
async def test_headline_metrics_come_from_composite_not_avg_of_cagrs(analytics_db):
    """Firm CAGR/Sharpe/MaxDD on the StatCards must be the COMPOSITE TWR (same
    source as the Strategy Summary table), not an AUM-weighted average of
    per-portfolio stored CAGRs.

    Regression guard for the live bug where the card showed +11.48% while the
    composite (and reality) was ~+24%. On this fixture the composite differs from
    the avg-of-stored-CAGRs, so a revert to the old method would break this.
    """
    async with analytics_db() as s:
        comp = await get_aggregate_risk_metrics(s, "COMBINED", False)
        out = await compute_dashboard_analytics(s, "COMBINED", False)

    # Card delegates the headline figures to the composite (same coercion).
    assert out["blended_cagr"] == round(_finite(comp["cagr"]), 2)
    assert out["avg_max_drawdown"] == round(_finite(comp["max_drawdown"]), 2)
    assert out["blended_sharpe"] == round(_finite(comp["sharpe_ratio"]), 2)

    # The old method (AUM-weighted mean of the seeded 20/10/30/12% sleeve CAGRs,
    # ≈ +17.64%) would NOT match the composite — so a revert breaks this.
    avg_of_stored = (20 * 1000 + 10 * 500 + 30 * 300 + 12 * 400) / 2200
    assert out["blended_cagr"] != round(avg_of_stored, 2)
