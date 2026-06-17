"""Per-sleeve dashboard summary (all the client's portfolios at a glance)."""

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
from backend.models.risk_metric import RiskMetric
from backend.services.combined_service import get_portfolios_summary


@pytest_asyncio.fixture(scope="function")
async def db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    tables = [Client.__table__, Portfolio.__table__, NavSeries.__table__, RiskMetric.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    today = dt.date.today()
    def ago(n):
        return today - dt.timedelta(days=n)

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add(Client(id=1, client_code="BJ53", name="Bhadresh", username="bj53",
                     password_hash="x", is_active=True, is_admin=False))
        s.add_all([
            Portfolio(id=10, client_id=1, portfolio_name="PMS Equity", inception_date=ago(400),
                      client_code="BJ53", strategy="LEADERS", is_closed=False),
            Portfolio(id=11, client_id=1, portfolio_name="PMS Equity (BJ53PASS)", inception_date=ago(400),
                      client_code="BJ53PASS", strategy="PASSIVE", is_closed=False),
            Portfolio(id=12, client_id=1, portfolio_name="PMS Equity (BJ53CLO)", inception_date=ago(400),
                      client_code="BJ53CLO", strategy="LEADERS", is_closed=True),  # excluded
        ])

        def nav(pid, d, v, inv):
            return NavSeries(client_id=1, portfolio_id=pid, nav_date=d, nav_value=Decimal(v),
                             current_value=Decimal(v), invested_amount=Decimal(inv),
                             benchmark_value=Decimal("100"))
        # pf10: invested 1000 → latest 2000 (+100%); pf11: invested 500 → latest 550 (+10%).
        for d, v in ((ago(60), "1500"), (ago(30), "1800"), (ago(2), "2000")):
            s.add(nav(10, d, v, "1000"))
        for d, v in ((ago(60), "510"), (ago(30), "530"), (ago(2), "550")):
            s.add(nav(11, d, v, "500"))
        s.add(nav(12, ago(2), "9999", "9999"))  # closed sleeve — must not appear
        s.add_all([
            RiskMetric(client_id=1, portfolio_id=10, computed_date=ago(2), cagr=Decimal("25.0")),
            RiskMetric(client_id=1, portfolio_id=11, computed_date=ago(2), cagr=Decimal("8.0")),
        ])
        await s.commit()
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_portfolios_summary_lists_live_sleeves_with_metrics(db):
    async with db() as s:
        out = await get_portfolios_summary(s, 1)

    pfs = out["portfolios"]
    # Closed sleeve excluded; ordered by current value desc (2000 > 550).
    assert [p["client_code"] for p in pfs] == ["BJ53", "BJ53PASS"]

    bj53 = pfs[0]
    assert bj53["strategy"] == "LEADERS"
    assert float(bj53["current_value"]) == 2000.0
    assert float(bj53["invested"]) == 1000.0
    assert float(bj53["return_pct"]) == 100.0       # (2000/1000 - 1) * 100
    assert float(bj53["cagr"]) == 25.0

    pas = pfs[1]
    assert float(pas["return_pct"]) == 10.0          # (550/500 - 1) * 100
    assert float(pas["cagr"]) == 8.0

    # Combined block present and additive on ₹.
    assert "combined" in out
    assert float(out["combined"]["invested"]) == 1500.0   # 1000 + 500


@pytest.mark.asyncio
async def test_portfolios_summary_empty_for_client_with_no_live_portfolios(db):
    async with db() as s:
        out = await get_portfolios_summary(s, 999)  # unknown client
    assert out == {"portfolios": [], "combined": {}}
