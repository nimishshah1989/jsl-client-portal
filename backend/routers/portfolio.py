"""Portfolio router — summary, NAV series, growth, allocation, holdings, drawdown."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

import numpy as np

from backend.database import get_db
from backend.middleware.auth_middleware import get_current_user
from backend.models.drawdown import DrawdownSeries
from backend.models.holding import Holding
from backend.models.nav_series import NavSeries
from backend.models.risk_metric import RiskMetric
from backend.routers.helpers import (
    FD_RATE,
    date_cutoff,
    dec2,
    dec4,
    get_default_portfolio,
)
from backend.schemas.portfolio import (
    AllocationItem,
    AllocationResponse,
    DrawdownPoint,
    GrowthResponse,
    HoldingResponse,
    NavSeriesPoint,
    SummaryResponse,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SummaryResponse:
    """Summary cards: invested, current, profit, CAGR, YTD, max DD."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    nav_stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(desc(NavSeries.nav_date))
        .limit(1)
    )
    latest_nav = (await db.execute(nav_stmt)).scalar_one_or_none()
    if latest_nav is None:
        raise HTTPException(status_code=404, detail="No NAV data available")

    risk_stmt = (
        select(RiskMetric)
        .where(RiskMetric.client_id == client_id)
        .where(RiskMetric.portfolio_id == portfolio.id)
        .order_by(desc(RiskMetric.computed_date))
        .limit(1)
    )
    risk = (await db.execute(risk_stmt)).scalar_one_or_none()

    invested = latest_nav.invested_amount
    current = latest_nav.current_value
    profit_amount = current - invested
    profit_pct = (
        ((current - invested) / invested * Decimal("100"))
        if invested and invested != Decimal("0")
        else Decimal("0")
    )

    # Compute TWR-adjusted YTD return. Raw nav_value includes corpus infusions
    # as value increases, which would be incorrectly counted as returns.
    # Fetch all NAV rows from Jan 1 to compute chain-linked TWR.
    jan1 = dt.date(latest_nav.nav_date.year, 1, 1)
    ytd_stmt = (
        select(NavSeries.nav_value, NavSeries.invested_amount)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .where(NavSeries.nav_date >= jan1)
        .order_by(NavSeries.nav_date)
    )
    ytd_rows = (await db.execute(ytd_stmt)).all()
    ytd_return = Decimal("0")
    if len(ytd_rows) >= 2:
        nav_vals = np.array([float(r[0]) for r in ytd_rows])
        corpus_vals = np.array([float(r[1]) for r in ytd_rows])
        # Chain-link TWR from Jan 1: on corpus-change days, adjust
        # the previous NAV to remove the infusion effect.
        twr = 1.0
        for i in range(1, len(nav_vals)):
            prev = nav_vals[i - 1]
            if prev == 0:
                continue
            corpus_chg = corpus_vals[i] - corpus_vals[i - 1]
            if corpus_chg != 0:
                adj_prev = prev + corpus_chg
                if adj_prev <= 0:
                    continue
                twr *= nav_vals[i] / adj_prev
            else:
                twr *= nav_vals[i] / prev
        ytd_return = Decimal(str(round((twr - 1) * 100, 6)))

    return SummaryResponse(
        invested=dec2(invested),
        current_value=dec2(current),
        profit_amount=dec2(profit_amount),
        profit_pct=dec2(profit_pct),
        cagr=dec2(risk.cagr) if risk else "0.00",
        ytd_return=dec2(ytd_return),
        max_drawdown=dec2(risk.max_drawdown) if risk else "0.00",
        as_of_date=latest_nav.nav_date,
    )


@router.get("/nav-series", response_model=list[NavSeriesPoint])
async def get_nav_series(
    time_range: str = Query("ALL", alias="range"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NavSeriesPoint]:
    """NAV time series with actual ₹ portfolio value and Nifty equivalent.

    Left-axis values are in absolute rupees so the client sees real portfolio
    growth rather than a normalised index.

    - nav:           actual current_value from the NAV row (₹)
    - benchmark:     invested_amount × (benchmark_today / benchmark_first) —
                     what the same corpus would be worth had it been in Nifty
    - invested:      corpus (invested_amount) at each date — step-line overlay
    - benchmark_raw: base-100 Nifty index (kept for reference)
    - cash_pct:      liquidity % clamped to [0, 100]
    """
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(NavSeries.nav_date)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return []

    cutoff = date_cutoff(time_range, rows[-1].nav_date)
    if cutoff is not None:
        rows = [r for r in rows if r.nav_date >= cutoff]
    if not rows:
        return []

    # Benchmark base: use the first row's benchmark value that is non-zero.
    # invested_amount at the first row is the reference corpus for Nifty scaling.
    first_bench = rows[0].benchmark_value
    first_invested = rows[0].invested_amount or Decimal("0")

    points: list[NavSeriesPoint] = []
    for row in rows:
        # Nifty equivalent: what first_invested corpus would be worth today in Nifty
        bench_equiv: str | None = None
        bench_raw: str | None = None
        if (
            row.benchmark_value
            and first_bench
            and first_bench != Decimal("0")
            and first_invested != Decimal("0")
        ):
            bench_equiv = dec2(
                first_invested * row.benchmark_value / first_bench
            )
            bench_raw = dec2(row.benchmark_value / first_bench * Decimal("100"))

        # Clamp cash_pct to [0, 100]
        cash: str | None = None
        if row.cash_pct is not None:
            clamped = max(Decimal("0"), min(Decimal("100"), row.cash_pct))
            cash = dec2(clamped)

        points.append(NavSeriesPoint(
            date=row.nav_date,
            nav=dec2(row.current_value),
            benchmark=bench_equiv,
            invested=dec2(row.invested_amount) if row.invested_amount is not None else None,
            benchmark_raw=bench_raw,
            cash_pct=cash,
        ))
    return points


@router.get("/growth", response_model=GrowthResponse)
async def get_growth(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GrowthResponse:
    """Growth comparison: portfolio vs Nifty vs FD."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    first_stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(NavSeries.nav_date).limit(1)
    )
    last_stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(desc(NavSeries.nav_date)).limit(1)
    )
    first_nav = (await db.execute(first_stmt)).scalar_one_or_none()
    last_nav = (await db.execute(last_stmt)).scalar_one_or_none()
    if first_nav is None or last_nav is None:
        raise HTTPException(status_code=404, detail="No NAV data available")

    invested = last_nav.invested_amount
    current = last_nav.current_value
    days = (last_nav.nav_date - first_nav.nav_date).days
    years = Decimal(str(days)) / Decimal("365.25") if days > 0 else Decimal("1")

    nifty_value = invested
    if (first_nav.benchmark_value and last_nav.benchmark_value
            and first_nav.benchmark_value != Decimal("0")):
        nifty_value = invested * last_nav.benchmark_value / first_nav.benchmark_value

    fd_value = invested * ((Decimal("1") + FD_RATE / Decimal("100")) ** years)

    return GrowthResponse(
        invested=dec2(invested), portfolio=dec2(current),
        nifty=dec2(nifty_value), fd=dec2(fd_value),
        inception_date=first_nav.nav_date, latest_date=last_nav.nav_date,
        years=dec2(years),
    )


@router.get("/allocation", response_model=AllocationResponse)
async def get_allocation(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AllocationResponse:
    """Holdings grouped by asset class and sector."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    stmt = (
        select(Holding)
        .where(Holding.client_id == client_id)
        .where(Holding.portfolio_id == portfolio.id)
        .where(Holding.quantity > 0)
    )
    holdings = list((await db.execute(stmt)).scalars().all())

    class_map: dict[str, Decimal] = {}
    sector_map: dict[str, Decimal] = {}
    total_value = Decimal("0")

    for h in holdings:
        val = h.current_value or Decimal("0")
        total_value += val
        class_map[h.asset_class or "OTHER"] = class_map.get(h.asset_class or "OTHER", Decimal("0")) + val
        # Exclude CASH holdings from sector breakdown (they have no sector)
        if (h.asset_class or "").upper() != "CASH":
            sector_map[h.sector or "Unknown"] = sector_map.get(h.sector or "Unknown", Decimal("0")) + val

    def _to_items(mapping: dict[str, Decimal]) -> list[AllocationItem]:
        return [
            AllocationItem(
                name=name, value=dec2(value),
                weight_pct=dec2(value / total_value * Decimal("100")
                                if total_value != Decimal("0") else Decimal("0")),
            )
            for name, value in sorted(mapping.items(), key=lambda x: x[1], reverse=True)
        ]

    # Omit sector breakdown when all holdings lack sector data
    sector_items = _to_items(sector_map)
    if len(sector_items) == 1 and sector_items[0].name == "Unknown":
        sector_items = []

    return AllocationResponse(by_class=_to_items(class_map), by_sector=sector_items)


@router.get("/holdings", response_model=list[HoldingResponse])
async def get_holdings(
    sort: str = Query("weight", regex="^(weight|pnl|value|name)$"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    asset_class: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[HoldingResponse]:
    """Current holdings with P&L, sortable and filterable."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    stmt = (
        select(Holding)
        .where(Holding.client_id == client_id)
        .where(Holding.portfolio_id == portfolio.id)
        .where(Holding.quantity > 0)
    )
    if asset_class:
        stmt = stmt.where(Holding.asset_class == asset_class.upper())

    sort_col = {"weight": Holding.weight_pct, "pnl": Holding.unrealized_pnl,
                "value": Holding.current_value, "name": Holding.symbol}.get(sort, Holding.weight_pct)
    stmt = stmt.order_by(desc(sort_col) if order == "desc" else sort_col)
    holdings = list((await db.execute(stmt)).scalars().all())

    responses: list[HoldingResponse] = []
    for h in holdings:
        pnl_pct: str | None = None
        if h.avg_cost and h.current_price and h.avg_cost != Decimal("0"):
            pnl_pct = dec2((h.current_price - h.avg_cost) / h.avg_cost * Decimal("100"))
        responses.append(HoldingResponse(
            symbol=h.symbol, asset_name=h.asset_name, asset_class=h.asset_class,
            sector=h.sector, quantity=dec4(h.quantity), avg_cost=dec2(h.avg_cost),
            current_price=dec2(h.current_price) if h.current_price else None,
            current_value=dec2(h.current_value) if h.current_value else None,
            unrealized_pnl=dec2(h.unrealized_pnl) if h.unrealized_pnl else None,
            pnl_pct=pnl_pct,
            weight_pct=dec2(h.weight_pct) if h.weight_pct else None,
        ))
    return responses


@router.get("/drawdown-series", response_model=list[DrawdownPoint])
async def get_drawdown_series(
    time_range: str = Query("ALL", alias="range"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DrawdownPoint]:
    """Drawdown underwater chart data."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    stmt = (
        select(DrawdownSeries)
        .where(DrawdownSeries.client_id == client_id)
        .where(DrawdownSeries.portfolio_id == portfolio.id)
        .order_by(DrawdownSeries.dd_date)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return []

    cutoff = date_cutoff(time_range, rows[-1].dd_date)
    if cutoff is not None:
        rows = [r for r in rows if r.dd_date >= cutoff]

    return [
        DrawdownPoint(
            date=r.dd_date, drawdown_pct=dec2(r.drawdown_pct),
            bench_drawdown=dec2(r.bench_drawdown) if r.bench_drawdown else None,
        )
        for r in rows
    ]
