"""Portfolio router — summary, allocation, holdings, drawdown.

NAV series and growth endpoints are in portfolio_nav.py.
"""

import datetime as dt
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

import numpy as np

from backend.database import get_db
from backend.middleware.auth_middleware import get_current_user
from backend.models.drawdown import DrawdownSeries
from backend.models.holding import Holding
from backend.models.nav_series import NavSeries
from backend.models.risk_metric import RiskMetric
from backend.routers.helpers import (
    date_cutoff,
    dec2,
    dec4,
    get_default_portfolio,
    opt2,
)
from backend.schemas.portfolio import (
    AllocationItem,
    AllocationResponse,
    DrawdownPoint,
    HoldingResponse,
    SummaryResponse,
)

logger = logging.getLogger(__name__)

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

    invested = latest_nav.invested_amount or Decimal("0")
    current = latest_nav.current_value or latest_nav.nav_value or Decimal("0")
    profit_amount = current - invested if invested else Decimal("0")
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

    # True cash = Cash + ETF (LIQUIDBEES) + Bank Balance
    # The PMS file's Liquidity% excludes ETF, so we compute from components.
    # Fallback to Liquidity% if breakdown columns are not yet populated (pre-re-upload).
    etf = latest_nav.etf_value if latest_nav.etf_value is not None else Decimal("0")
    cash_val = latest_nav.cash_value if latest_nav.cash_value is not None else Decimal("0")
    bank = latest_nav.bank_balance if latest_nav.bank_balance is not None else Decimal("0")
    ledger_cash = cash_val + bank  # Cash on books (no ETF)
    cash_amount = etf + ledger_cash  # Total cash position
    nav_val = latest_nav.nav_value if latest_nav.nav_value and latest_nav.nav_value != Decimal("0") else Decimal("1")

    if cash_amount > 0:
        cash_pct_clamped = max(Decimal("0"), cash_amount / nav_val * Decimal("100"))
    else:
        # Fallback: use Liquidity% and derive cash_amount from it
        fallback_pct = latest_nav.cash_pct if latest_nav.cash_pct is not None else Decimal("0")
        cash_pct_clamped = max(Decimal("0"), fallback_pct)
        cash_amount = current * cash_pct_clamped / Decimal("100") if current else Decimal("0")
        ledger_cash = cash_amount  # Best approximation before re-upload

    return SummaryResponse(
        invested=dec2(invested),
        current_value=dec2(current),
        profit_amount=dec2(profit_amount),
        profit_pct=dec2(profit_pct),
        cagr=dec2(risk.cagr) if risk else "0.00",
        ytd_return=dec2(ytd_return),
        max_drawdown=dec2(risk.max_drawdown) if risk else "0.00",
        as_of_date=latest_nav.nav_date,
        cash_amount=dec2(cash_amount),
        cash_pct=dec2(cash_pct_clamped),
        ledger_cash=dec2(ledger_cash),
        bench_cagr=opt2(risk.bench_cagr_inception) if risk else None,
        bench_max_dd=opt2(risk.bench_dd_inception) if risk else None,
    )


@router.get("/allocation", response_model=AllocationResponse)
async def get_allocation(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AllocationResponse:
    """Holdings grouped by sector. Every holding maps to a sector.

    LIQUID* instruments -> 'Cash', GOLDBEES/SILVERBEES -> 'Metals', etc.
    """
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    stmt = (
        select(Holding)
        .where(Holding.client_id == client_id)
        .where(Holding.portfolio_id == portfolio.id)
        .where(Holding.quantity > 0)
    )
    holdings = list((await db.execute(stmt)).scalars().all())

    sector_map: dict[str, Decimal] = {}
    total_value = Decimal("0")

    for h in holdings:
        val = h.current_value or Decimal("0")
        total_value += val
        sector = h.sector or "Other"
        sector_map[sector] = sector_map.get(sector, Decimal("0")) + val

    by_sector = [
        AllocationItem(
            name=name, value=dec2(value),
            weight_pct=dec2(value / total_value * Decimal("100")
                            if total_value != Decimal("0") else Decimal("0")),
        )
        for name, value in sorted(sector_map.items(), key=lambda x: x[1], reverse=True)
    ]

    return AllocationResponse(by_sector=by_sector)


@router.get("/holdings", response_model=list[HoldingResponse])
async def get_holdings(
    sort: str = Query("weight", regex="^(weight|pnl|value|name|price|quantity|avg_cost|pnl_pct)$"),
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

    sort_col = {
        "weight": Holding.weight_pct, "pnl": Holding.unrealized_pnl,
        "value": Holding.current_value, "name": Holding.symbol,
        "price": Holding.current_price, "quantity": Holding.quantity,
        "avg_cost": Holding.avg_cost, "pnl_pct": Holding.unrealized_pnl,
    }.get(sort, Holding.weight_pct)
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
