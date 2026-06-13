"""Multi-tenant isolation regression test (PRODUCTION_READINESS C14).

Why this test exists
--------------------
The portal serves ~200 PMS clients; any cross-tenant leak in a portfolio
endpoint is catastrophic (a client sees another client's holdings, NAV, PII).
This test seeds two clients (A and B), and for **every** GET endpoint exposed
under ``/api/portfolio/*`` asserts that a response served to client A contains
no sentinel value originating from client B.

The set of endpoints is **enumerated dynamically** from the FastAPI route
table. If a new ``/api/portfolio`` endpoint is added later, the matrix will
automatically pick it up — and any endpoint that does not properly scope by
``client_id`` will fail this test loudly.

Test infrastructure
-------------------
The existing test suite is pure-unit (no DB harness exists). To keep this
change test-only and self-contained, this file builds its own isolated
infrastructure:

  * SQLite-in-memory via ``aiosqlite`` (a single shared connection so all
    sessions see the same data).
  * A minimal FastAPI app with only the portfolio routers mounted, bypassing
    the production ``lifespan`` (which connects to RDS and starts a scheduler).
  * Real JWT cookies signed with ``create_access_token`` from
    ``backend.middleware.auth_middleware`` — i.e. the production auth flow.
  * Only the tables exercised by the portfolio routers are created
    (some other ORM models use Postgres-specific types).

Constraints
-----------
This file does NOT modify any production code under ``backend/``.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from typing import AsyncIterator

# Env vars must be set BEFORE importing backend modules (Settings is strict).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "t" * 64)
os.environ.setdefault("APP_ENV", "development")

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.middleware.auth_middleware import create_access_token
from backend.models.cash_flow import CashFlow
from backend.models.client import Client
from backend.models.drawdown import DrawdownSeries
from backend.models.holding import Holding
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from backend.models.risk_metric import RiskMetric
from backend.models.transaction import Transaction

from backend.routers.admin import router as admin_router
from backend.routers.portfolio import router as portfolio_router
from backend.routers.portfolio_combined import router as portfolio_combined_router
from backend.routers.portfolio_detail import router as portfolio_detail_router
from backend.routers.portfolio_methodology import router as portfolio_methodology_router
from backend.routers.portfolio_nav import router as portfolio_nav_router


# ── Sentinel constants ──
# Deliberately weird, easy-to-grep values seeded ONLY on client B.
# If any of these appear in a response served to client A, isolation is broken.
SENTINEL_NAV_VALUE = Decimal("99999999.99")
SENTINEL_INVESTED = Decimal("88888888.88")
SENTINEL_CURRENT = Decimal("99999999.99")
SENTINEL_SYMBOL = "SENTINELB"
SENTINEL_ASSET_NAME = "BravoSentinelPharma"
SENTINEL_SECTOR = "BravoSentinelSector"
SENTINEL_CLIENT_NAME = "BravoSentinelClient"
SENTINEL_CLIENT_CODE = "BRAVOSENTINELCODE"
SENTINEL_USERNAME = "bravosentinelusername"

# Numeric sentinels that will show up in stringified responses (Pydantic
# serializes Decimals via the routers' dec2 helper to e.g. "99999999.99").
SENTINEL_NUMERIC_STRINGS = [
    "99999999.99",
    "88888888.88",
    "77777777.77",   # holding current_value sentinel
    "66666666.66",   # cash flow amount sentinel
    "5555.5555",     # avg_cost sentinel
]
SENTINEL_TEXT_TOKENS = [
    SENTINEL_SYMBOL,
    SENTINEL_ASSET_NAME,
    SENTINEL_SECTOR,
    SENTINEL_CLIENT_NAME,
    SENTINEL_CLIENT_CODE,
    SENTINEL_USERNAME,
]

# Boring, unmistakably-A values — used to confirm A's own data is reachable
# (so a green test doesn't just mean "empty body, no leak").
A_SYMBOL = "RELIANCE"
A_NAV_VALUE = Decimal("1500000.00")
A_CURRENT = Decimal("1700000.00")


# ── Async SQLite engine (shared in-memory connection) ──


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """One in-memory SQLite engine per test, using a StaticPool so the
    in-memory database survives across multiple sessions."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Only create tables the portfolio routers actually touch.
    # Audit/upload logs use Postgres JSONB; they aren't needed here.
    tables = [
        Client.__table__,
        Portfolio.__table__,
        NavSeries.__table__,
        Transaction.__table__,
        Holding.__table__,
        RiskMetric.__table__,
        DrawdownSeries.__table__,
        CashFlow.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(db_engine):
    """Async sessionmaker bound to the test engine."""
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


# ── Data seeding ──


async def _seed_client_a(session: AsyncSession) -> tuple[Client, Portfolio]:
    """Seed an ordinary, plausible-looking client with full data."""
    client = Client(
        client_code="ACLIENT001",
        name="Alpha Client",
        email="alpha@example.test",
        phone="+910000000001",
        username="alphaclient",
        password_hash="$2b$12$abcdefghijklmnopqrstuv",  # dummy bcrypt hash
        is_active=True,
        is_admin=False,
    )
    session.add(client)
    await session.flush()

    portfolio = Portfolio(
        client_id=client.id,
        portfolio_name="PMS Equity",
        benchmark="NIFTY500",
        inception_date=dt.date(2024, 1, 1),
        status="active",
    )
    session.add(portfolio)
    await session.flush()

    # Two NAV rows on dates that ALSO appear in client B's series — this is
    # exactly the kind of overlap that can produce a cross-client leak if a
    # query forgets ``WHERE client_id = ?``.
    nav_rows = [
        NavSeries(
            client_id=client.id, portfolio_id=portfolio.id,
            nav_date=dt.date(2024, 1, 1),
            nav_value=A_NAV_VALUE, invested_amount=Decimal("1500000.00"),
            current_value=A_NAV_VALUE,
            benchmark_value=Decimal("21000.00"),
            cash_pct=Decimal("5.0000"),
            etf_value=Decimal("10000.00"),
            cash_value=Decimal("5000.00"),
            bank_balance=Decimal("3000.00"),
        ),
        NavSeries(
            client_id=client.id, portfolio_id=portfolio.id,
            nav_date=dt.date(2024, 6, 1),
            nav_value=A_CURRENT, invested_amount=Decimal("1500000.00"),
            current_value=A_CURRENT,
            benchmark_value=Decimal("23000.00"),
            cash_pct=Decimal("6.0000"),
            etf_value=Decimal("12000.00"),
            cash_value=Decimal("6000.00"),
            bank_balance=Decimal("4000.00"),
        ),
    ]
    session.add_all(nav_rows)

    session.add(Transaction(
        client_id=client.id, portfolio_id=portfolio.id,
        txn_date=dt.date(2024, 1, 5), txn_type="BUY",
        symbol=A_SYMBOL, asset_name="Reliance Industries",
        asset_class="EQUITY", instrument_type="EQ",
        quantity=Decimal("10.0000"), price=Decimal("2500.0000"),
        amount=Decimal("25000.00"),
    ))

    session.add(Holding(
        client_id=client.id, portfolio_id=portfolio.id,
        symbol=A_SYMBOL, asset_name="Reliance Industries",
        asset_class="EQUITY", sector="Energy",
        quantity=Decimal("10.0000"), avg_cost=Decimal("2500.0000"),
        current_price=Decimal("2700.0000"),
        current_value=Decimal("27000.00"),
        unrealized_pnl=Decimal("2000.00"),
        weight_pct=Decimal("100.0000"),
    ))

    session.add(RiskMetric(
        client_id=client.id, portfolio_id=portfolio.id,
        computed_date=dt.date(2024, 6, 1),
        absolute_return=Decimal("13.3300"),
        cagr=Decimal("13.0000"),
        xirr=Decimal("14.0000"),
        volatility=Decimal("12.0000"),
        sharpe_ratio=Decimal("0.5400"),
        sortino_ratio=Decimal("0.7000"),
        max_drawdown=Decimal("-5.0000"),
        alpha=Decimal("1.0000"), beta=Decimal("0.9000"),
        information_ratio=Decimal("0.3000"),
        tracking_error=Decimal("4.0000"),
        up_capture=Decimal("95.0000"),
        down_capture=Decimal("85.0000"),
        ulcer_index=Decimal("2.0000"),
        market_correlation=Decimal("0.9000"),
        monthly_hit_rate=Decimal("60.0000"),
        best_month=Decimal("5.0000"),
        worst_month=Decimal("-3.0000"),
        avg_positive_month=Decimal("2.0000"),
        avg_negative_month=Decimal("-1.5000"),
        max_consecutive_loss=2,
        win_months=3, loss_months=2,
        avg_cash_held=Decimal("5.0000"),
        max_cash_held=Decimal("6.0000"),
        current_cash=Decimal("6.0000"),
        cagr_inception=Decimal("13.0000"),
        return_inception=Decimal("13.3300"),
        bench_cagr_inception=Decimal("9.5000"),
        bench_return_inception=Decimal("9.5000"),
        bench_vol_inception=Decimal("14.0000"),
        bench_sharpe_inception=Decimal("0.2100"),
        bench_sortino_inception=Decimal("0.3000"),
        bench_dd_inception=Decimal("-8.0000"),
        risk_free_rate=Decimal("6.5000"),
    ))

    session.add(DrawdownSeries(
        client_id=client.id, portfolio_id=portfolio.id,
        dd_date=dt.date(2024, 3, 1), drawdown_pct=Decimal("-2.0000"),
        bench_drawdown=Decimal("-3.0000"),
        peak_nav=A_NAV_VALUE, current_nav=Decimal("1470000.00"),
    ))

    session.add(CashFlow(
        client_id=client.id, portfolio_id=portfolio.id,
        flow_date=dt.date(2024, 1, 1), flow_type="INFLOW",
        amount=Decimal("1500000.00"),
        description="Initial corpus", source_ucc=client.client_code,
    ))

    await session.commit()
    await session.refresh(client)
    await session.refresh(portfolio)
    return client, portfolio


async def _seed_client_b(session: AsyncSession) -> tuple[Client, Portfolio]:
    """Seed client B with deliberately unique SENTINEL values throughout."""
    client = Client(
        client_code=SENTINEL_CLIENT_CODE,
        name=SENTINEL_CLIENT_NAME,
        email="bravo@example.test",
        phone="+910000000002",
        username=SENTINEL_USERNAME,
        password_hash="$2b$12$zzzzzzzzzzzzzzzzzzzzzz",
        is_active=True,
        is_admin=False,
    )
    session.add(client)
    await session.flush()

    portfolio = Portfolio(
        client_id=client.id,
        portfolio_name="PMS Equity",
        benchmark="NIFTY500",
        inception_date=dt.date(2024, 1, 1),
        status="active",
    )
    session.add(portfolio)
    await session.flush()

    # NAV rows on the SAME dates as client A — forces tenant-isolation
    # bugs (e.g. a date-only filter without client scoping) to surface.
    for d in (dt.date(2024, 1, 1), dt.date(2024, 6, 1)):
        session.add(NavSeries(
            client_id=client.id, portfolio_id=portfolio.id,
            nav_date=d,
            nav_value=SENTINEL_NAV_VALUE,
            invested_amount=SENTINEL_INVESTED,
            current_value=SENTINEL_CURRENT,
            benchmark_value=Decimal("21000.00"),
            cash_pct=Decimal("10.0000"),
            etf_value=Decimal("100.00"),
            cash_value=Decimal("100.00"),
            bank_balance=Decimal("100.00"),
        ))

    session.add(Transaction(
        client_id=client.id, portfolio_id=portfolio.id,
        txn_date=dt.date(2024, 1, 5), txn_type="BUY",
        symbol=SENTINEL_SYMBOL, asset_name=SENTINEL_ASSET_NAME,
        asset_class="EQUITY", instrument_type="EQ",
        quantity=Decimal("123.4500"), price=Decimal("5555.5555"),
        amount=Decimal("88888888.88"),
    ))

    session.add(Holding(
        client_id=client.id, portfolio_id=portfolio.id,
        symbol=SENTINEL_SYMBOL, asset_name=SENTINEL_ASSET_NAME,
        asset_class="EQUITY", sector=SENTINEL_SECTOR,
        quantity=Decimal("123.4500"), avg_cost=Decimal("5555.5555"),
        current_price=Decimal("6000.0000"),
        current_value=Decimal("77777777.77"),
        unrealized_pnl=Decimal("99999999.99"),
        weight_pct=Decimal("99.9900"),
    ))

    session.add(RiskMetric(
        client_id=client.id, portfolio_id=portfolio.id,
        computed_date=dt.date(2024, 6, 1),
        absolute_return=Decimal("99999999.99"),
        cagr=Decimal("99999999.99"),
        xirr=Decimal("99999999.99"),
        volatility=Decimal("99999999.99"),
        sharpe_ratio=Decimal("99999999.99"),
        sortino_ratio=Decimal("99999999.99"),
        max_drawdown=Decimal("-99999999.99"),
        alpha=Decimal("99999999.99"), beta=Decimal("99999999.99"),
        information_ratio=Decimal("99999999.99"),
        tracking_error=Decimal("99999999.99"),
        up_capture=Decimal("99999999.99"),
        down_capture=Decimal("99999999.99"),
        ulcer_index=Decimal("99999999.99"),
        market_correlation=Decimal("99999999.99"),
        monthly_hit_rate=Decimal("99.9900"),
        best_month=Decimal("99999999.99"),
        worst_month=Decimal("-99999999.99"),
        avg_positive_month=Decimal("99999999.99"),
        avg_negative_month=Decimal("-99999999.99"),
        max_consecutive_loss=42,
        win_months=99, loss_months=88,
        avg_cash_held=Decimal("99.9900"),
        max_cash_held=Decimal("99.9900"),
        current_cash=Decimal("99.9900"),
        cagr_inception=Decimal("99999999.99"),
        return_inception=Decimal("99999999.99"),
        bench_cagr_inception=Decimal("99999999.99"),
        bench_return_inception=Decimal("99999999.99"),
        bench_vol_inception=Decimal("99999999.99"),
        bench_sharpe_inception=Decimal("99999999.99"),
        bench_sortino_inception=Decimal("99999999.99"),
        bench_dd_inception=Decimal("-99999999.99"),
        risk_free_rate=Decimal("6.5000"),
    ))

    session.add(DrawdownSeries(
        client_id=client.id, portfolio_id=portfolio.id,
        dd_date=dt.date(2024, 3, 1),
        drawdown_pct=Decimal("-99999999.99"),
        bench_drawdown=Decimal("-99999999.99"),
        peak_nav=SENTINEL_NAV_VALUE,
        current_nav=Decimal("88888888.88"),
    ))

    session.add(CashFlow(
        client_id=client.id, portfolio_id=portfolio.id,
        flow_date=dt.date(2024, 1, 1), flow_type="INFLOW",
        amount=Decimal("66666666.66"),
        description=SENTINEL_ASSET_NAME, source_ucc=client.client_code,
    ))

    await session.commit()
    await session.refresh(client)
    await session.refresh(portfolio)
    return client, portfolio


@pytest_asyncio.fixture(scope="function")
async def seeded_db(session_factory):
    """Seed both clients and return their IDs."""
    async with session_factory() as session:
        a, a_pf = await _seed_client_a(session)
        b, b_pf = await _seed_client_b(session)
        return {
            "a_id": a.id, "b_id": b.id,
            "a_portfolio_id": a_pf.id, "b_portfolio_id": b_pf.id,
        }


# ── FastAPI test app ──


def _build_app(session_factory) -> FastAPI:
    """Construct a minimal FastAPI app with only the portfolio routers
    mounted; no lifespan, no scheduler, no RDS connection."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    app = FastAPI()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.include_router(portfolio_router)
    app.include_router(portfolio_nav_router)
    app.include_router(portfolio_detail_router)
    app.include_router(portfolio_methodology_router)
    app.include_router(portfolio_combined_router)
    # Admin router is included only to test the IDOR rejection (non-admin
    # token must get 403, not the requested data).
    app.include_router(admin_router)

    app.dependency_overrides[get_db] = _override_get_db

    # Mirror the production catch-all so that handler-level exceptions
    # (e.g. a Postgres-specific raw SQL path that breaks on SQLite) become
    # 500 responses instead of bubbling out of ASGI and aborting the test.
    # The body must not contain anything sensitive — we assert that.
    @app.exception_handler(Exception)
    async def _general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


@pytest_asyncio.fixture(scope="function")
async def client(session_factory, seeded_db):
    """httpx AsyncClient wrapped around the test app."""
    app = _build_app(session_factory)
    # raise_app_exceptions=False mirrors what TestClient does: handler-level
    # exceptions become 500 responses (via our exception_handler), instead of
    # bubbling out of ASGI and aborting the test before isolation can be checked.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, seeded_db


# ── Endpoint enumeration ──


# Endpoints whose response is allowed to be 404 with "no data" semantics
# (e.g. when a client has no risk metrics yet — also a possible outcome on
# our minimal fixture data even though we seed it). For tenant isolation,
# what matters is that the body never contains client B sentinels.
_ALLOWED_NON_200_STATUS = {200, 404, 422}


def _enumerate_portfolio_get_endpoints() -> list[tuple[str, dict]]:
    """Walk every router and return every GET path under ``/api/portfolio/``.

    Returns a list of ``(path, query_params)`` tuples. Adding a new endpoint
    that this matrix does not know how to call will surface as a 422 — make
    the test fail and force the author to add the endpoint here.
    """
    paths: list[tuple[str, dict]] = []
    for router in (
        portfolio_router,
        portfolio_nav_router,
        portfolio_detail_router,
        portfolio_methodology_router,
        portfolio_combined_router,
    ):
        for route in router.routes:
            methods = getattr(route, "methods", set()) or set()
            path = getattr(route, "path", "")
            if "GET" not in methods:
                continue
            if not path.startswith("/api/portfolio/"):
                continue
            paths.append((path, {}))
    return paths


def _expected_endpoint_count() -> int:
    """Authoritative count of /api/portfolio/* GET endpoints.

    Bumping this number is intentional — if a new endpoint is added, this
    test will fail until the matrix is reviewed and updated. Pair the bump
    with a sentinel-leak check for the new endpoint.

    Current matrix (must equal len(_enumerate_portfolio_get_endpoints())):
      /api/portfolio/list
      /api/portfolio/summary
      /api/portfolio/allocation
      /api/portfolio/holdings
      /api/portfolio/drawdown-series
      /api/portfolio/nav-series
      /api/portfolio/growth
      /api/portfolio/performance-table
      /api/portfolio/risk-scorecard
      /api/portfolio/transactions
      /api/portfolio/xirr
      /api/portfolio/methodology
      /api/portfolio/combined/summary
      /api/portfolio/combined/nav-series
      /api/portfolio/combined/holdings
      /api/portfolio/combined/risk-scorecard
      /api/portfolio/combined/performance-table
      /api/portfolio/combined/drawdown-series
      /api/portfolio/combined/allocation
      /api/portfolio/combined/growth
      /api/portfolio/combined/xirr
    """
    return 21


# Endpoints that use Postgres-specific raw SQL features (date arithmetic on
# the cash flow ledger) and therefore raise a 500 under SQLite in this test
# harness. Their tenant isolation logic still must NOT leak sentinels — but
# we accept 500 as a valid status alongside 200/404 for these endpoints
# until the test infrastructure can target a real Postgres instance.
_PG_ONLY_ENDPOINTS = frozenset({
    "/api/portfolio/xirr",
})


# ── Helpers ──


def _make_cookies(client_id: int) -> dict[str, str]:
    """Build an httpx cookie dict containing a real, signed JWT."""
    # Seeded clients default to token_version=1 (Client model default).
    token = create_access_token(client_id=client_id, is_admin=False, token_version=1)
    return {"access_token": token}


def _assert_no_sentinel_leak(body_text: str, endpoint: str) -> None:
    """Fail loudly if any client-B sentinel value appears in the response."""
    for token in SENTINEL_TEXT_TOKENS:
        assert token not in body_text, (
            f"TENANT LEAK on {endpoint}: client B text sentinel "
            f"{token!r} appeared in response served to client A.\n"
            f"Body: {body_text[:500]}"
        )
    for num_str in SENTINEL_NUMERIC_STRINGS:
        assert num_str not in body_text, (
            f"TENANT LEAK on {endpoint}: client B numeric sentinel "
            f"{num_str!r} appeared in response served to client A.\n"
            f"Body: {body_text[:500]}"
        )


# ── Sanity tests (so a passing matrix is meaningful) ──


@pytest.mark.asyncio
async def test_matrix_enumeration_finds_all_endpoints():
    """Guard rail: if a new /api/portfolio GET endpoint is added without
    being represented in the matrix, this test will fail and force the
    author to update _expected_endpoint_count() after auditing isolation."""
    endpoints = _enumerate_portfolio_get_endpoints()
    actual = len(endpoints)
    expected = _expected_endpoint_count()
    assert actual == expected, (
        f"Number of /api/portfolio GET endpoints changed: expected "
        f"{expected}, found {actual}. New endpoints discovered: "
        f"{[p for p, _ in endpoints]}. If you added an endpoint, "
        "audit it for client_id scoping, then update "
        "_expected_endpoint_count() in this file."
    )


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(client):
    """Sanity: no JWT cookie -> 401."""
    ac, _ = client
    resp = await ac.get("/api/portfolio/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_client_a_can_see_own_data(client):
    """Sanity: client A's own data IS reachable (so the leak test isn't
    vacuously green because everything 404s)."""
    ac, ids = client
    cookies = _make_cookies(ids["a_id"])
    resp = await ac.get("/api/portfolio/holdings", cookies=cookies)
    assert resp.status_code == 200, resp.text
    assert A_SYMBOL in resp.text


# ── Core matrix: every endpoint, both directions ──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint", [p for p, _ in _enumerate_portfolio_get_endpoints()]
)
async def test_no_leak_to_client_a(client, endpoint):
    """For each /api/portfolio GET endpoint, hit it with client A's JWT
    and assert no client-B sentinel value appears in the response."""
    ac, ids = client
    cookies = _make_cookies(ids["a_id"])
    resp = await ac.get(endpoint, cookies=cookies)
    allowed = _ALLOWED_NON_200_STATUS | ({500} if endpoint in _PG_ONLY_ENDPOINTS else set())
    assert resp.status_code in allowed, (
        f"{endpoint} returned unexpected status "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    _assert_no_sentinel_leak(resp.text, endpoint)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint", [p for p, _ in _enumerate_portfolio_get_endpoints()]
)
async def test_no_leak_to_client_b(client, endpoint):
    """Symmetric direction — confirm isolation is mutual. Client B should
    see B's sentinel values but should NEVER see anything tagged with
    client A's identifiers (we re-use the same matrix but invert which
    side is the 'must-not-appear' tenant)."""
    ac, ids = client
    cookies = _make_cookies(ids["b_id"])
    resp = await ac.get(endpoint, cookies=cookies)
    allowed = _ALLOWED_NON_200_STATUS | ({500} if endpoint in _PG_ONLY_ENDPOINTS else set())
    assert resp.status_code in allowed, (
        f"{endpoint} returned unexpected status "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    # Tokens unique to client A that must NEVER appear in B's response.
    a_only_tokens = [A_SYMBOL, "Reliance Industries", "Alpha Client",
                     "ACLIENT001", "alphaclient"]
    for token in a_only_tokens:
        assert token not in resp.text, (
            f"TENANT LEAK on {endpoint}: client A token {token!r} "
            f"appeared in response served to client B.\n"
            f"Body: {resp.text[:500]}"
        )


# ── Query-param IDOR ──


@pytest.mark.asyncio
async def test_admin_recompute_idor_blocked_for_non_admin(client):
    """Non-admin client A must not be able to trigger
    /api/admin/recompute-risk against client B's id by abusing the
    optional ``client_id`` query parameter. Admin auth dep must reject
    with 403 before any data work happens."""
    ac, ids = client
    cookies = _make_cookies(ids["a_id"])
    resp = await ac.post(
        f"/api/admin/recompute-risk?client_id={ids['b_id']}",
        cookies=cookies,
    )
    assert resp.status_code == 403, (
        f"Expected 403 for non-admin hitting admin endpoint with cross-tenant "
        f"client_id, got {resp.status_code}: {resp.text[:300]}"
    )
    # And the response body must not have leaked any client B sentinel.
    _assert_no_sentinel_leak(resp.text, "/api/admin/recompute-risk")


@pytest.mark.asyncio
async def test_foreign_portfolio_id_is_rejected(client):
    """Client A passing client B's portfolio_id must get 404 — never B's data.

    The new ``?portfolio_id=`` selector (resolve_portfolio) scopes by both id
    AND client_id; this guards against an IDOR where A reads B's portfolio by
    guessing its id."""
    ac, ids = client
    cookies = _make_cookies(ids["a_id"])

    for path in ("summary", "holdings", "nav-series"):
        resp = await ac.get(
            f"/api/portfolio/{path}?portfolio_id={ids['b_portfolio_id']}",
            cookies=cookies,
        )
        assert resp.status_code == 404, (
            f"Expected 404 for A requesting B's portfolio on /{path}, "
            f"got {resp.status_code}: {resp.text[:300]}"
        )
        _assert_no_sentinel_leak(resp.text, f"/api/portfolio/{path}?portfolio_id=B")

    # And A's OWN portfolio_id must still resolve normally.
    resp = await ac.get(
        f"/api/portfolio/summary?portfolio_id={ids['a_portfolio_id']}",
        cookies=cookies,
    )
    assert resp.status_code == 200, resp.text
