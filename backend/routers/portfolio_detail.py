"""Portfolio router part 2 — performance table, risk, transactions, XIRR, methodology."""

import datetime as dt
import logging
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func as sqlfunc, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import get_current_user
from backend.models.nav_series import NavSeries
from backend.models.transaction import Transaction
from backend.routers.helpers import dec2, dec4, get_default_portfolio, get_latest_risk, opt2
from backend.schemas.portfolio import (
    PaginatedTransactions,
    PerformanceRow,
    RiskScorecardResponse,
    TransactionItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

PERIODS = [
    ("1 Month", "1m", 30), ("3 Months", "3m", 91), ("6 Months", "6m", 182),
    ("1 Year", "1y", 365), ("2 Years", "2y", 730), ("3 Years", "3y", 1095),
    ("4 Years", "4y", 1461), ("5 Years", "5y", 1826), ("Since Inception", "inception", None),
]


@router.get("/performance-table", response_model=list[PerformanceRow])
async def get_performance_table(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PerformanceRow]:
    """Multi-period returns table with all metrics."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)
    risk = await get_latest_risk(db, client_id, portfolio.id)
    if risk is None:
        return []

    # Determine data range to skip periods beyond available data
    from sqlalchemy import func as sqlfunc
    date_range = await db.execute(
        select(sqlfunc.min(NavSeries.nav_date), sqlfunc.max(NavSeries.nav_date))
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
    )
    min_date, max_date = date_range.one()
    data_days = (max_date - min_date).days if min_date and max_date else 0

    rows: list[PerformanceRow] = []
    for label, suffix, period_days in PERIODS:
        # Skip periods that exceed client's data range (except inception)
        if period_days is not None and period_days > data_days + 15:
            continue
        row = PerformanceRow(
            period=label,
            port_abs_return=opt2(getattr(risk, f"return_{suffix}", None)),
            bench_abs_return=opt2(getattr(risk, f"bench_return_{suffix}", None)),
            port_cagr=opt2(getattr(risk, f"cagr_{suffix}", None)),
            bench_cagr=opt2(getattr(risk, f"bench_cagr_{suffix}", None)),
            port_volatility=opt2(getattr(risk, f"vol_{suffix}", None)),
            bench_volatility=opt2(getattr(risk, f"bench_vol_{suffix}", None)),
            port_max_dd=opt2(getattr(risk, f"dd_{suffix}", None)),
            bench_max_dd=opt2(getattr(risk, f"bench_dd_{suffix}", None)),
            port_sharpe=opt2(getattr(risk, f"sharpe_{suffix}", None)),
            bench_sharpe=opt2(getattr(risk, f"bench_sharpe_{suffix}", None)),
            port_sortino=opt2(getattr(risk, f"sortino_{suffix}", None)),
            bench_sortino=opt2(getattr(risk, f"bench_sortino_{suffix}", None)),
        )
        rows.append(row)
    return rows


@router.get("/risk-scorecard", response_model=RiskScorecardResponse)
async def get_risk_scorecard(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiskScorecardResponse:
    """Risk scorecard with capture ratios, beta, alpha, monthly profile."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)
    risk = await get_latest_risk(db, client_id, portfolio.id)
    if risk is None:
        raise HTTPException(status_code=404, detail="No risk metrics computed yet")

    # Compute monthly returns from NAV series for heatmap
    monthly_returns = await _compute_monthly_returns(db, client_id, portfolio.id)

    return RiskScorecardResponse(
        alpha=opt2(risk.alpha), beta=opt2(risk.beta),
        information_ratio=opt2(risk.information_ratio),
        tracking_error=opt2(risk.tracking_error),
        up_capture=opt2(risk.up_capture), down_capture=opt2(risk.down_capture),
        ulcer_index=opt2(risk.ulcer_index),
        market_correlation=opt2(risk.market_correlation),
        max_drawdown=opt2(risk.max_drawdown),
        max_dd_start=risk.max_dd_start, max_dd_end=risk.max_dd_end,
        max_dd_recovery=risk.max_dd_recovery,
        monthly_hit_rate=opt2(risk.monthly_hit_rate),
        best_month=opt2(risk.best_month), worst_month=opt2(risk.worst_month),
        avg_positive_month=opt2(risk.avg_positive_month),
        avg_negative_month=opt2(risk.avg_negative_month),
        max_consecutive_loss=risk.max_consecutive_loss,
        win_months=risk.win_months, loss_months=risk.loss_months,
        monthly_returns=monthly_returns,
        avg_cash_held=opt2(risk.avg_cash_held),
        max_cash_held=opt2(risk.max_cash_held),
        current_cash=opt2(risk.current_cash),
        volatility=opt2(risk.volatility),
        sharpe_ratio=opt2(risk.sharpe_ratio),
        sortino_ratio=opt2(risk.sortino_ratio),
        bench_volatility=opt2(risk.bench_vol_inception),
        bench_sharpe=opt2(risk.bench_sharpe_inception),
        bench_sortino=opt2(risk.bench_sortino_inception),
        bench_max_dd=opt2(risk.bench_dd_inception),
    )


async def _compute_monthly_returns(
    db: AsyncSession, client_id: int, portfolio_id: int
) -> list[dict]:
    """Compute month-over-month returns from TWR-adjusted NAV for heatmap grid.

    Uses TWR (Time-Weighted Return) values so that cash inflows/outflows
    are NOT counted as investment returns.
    """
    import numpy as np
    import pandas as pd
    from backend.services.risk_metrics import compute_twr_series

    stmt = (
        select(NavSeries.nav_date, NavSeries.nav_value, NavSeries.invested_amount)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio_id)
        .order_by(NavSeries.nav_date)
    )
    rows = (await db.execute(stmt)).all()
    if len(rows) < 2:
        return []

    # Build DataFrame and compute TWR series (adjusts for corpus changes)
    nav_df = pd.DataFrame(
        [(r[0], float(r[1]), float(r[2])) for r in rows],
        columns=["nav_date", "nav_value", "invested_amount"],
    )
    nav_df["twr_value"] = compute_twr_series(nav_df)

    # Group by (year, month) → take last TWR value of each month
    monthly_last: dict[tuple[int, int], float] = {}
    for _, row in nav_df.iterrows():
        key = (row["nav_date"].year, row["nav_date"].month)
        monthly_last[key] = row["twr_value"]

    sorted_keys = sorted(monthly_last.keys())
    results: list[dict] = []
    for i in range(1, len(sorted_keys)):
        prev_key = sorted_keys[i - 1]
        curr_key = sorted_keys[i]
        prev_val = monthly_last[prev_key]
        curr_val = monthly_last[curr_key]
        if prev_val and prev_val > 0:
            ret = ((curr_val - prev_val) / prev_val) * 100
            year, month = curr_key
            results.append({
                "year": year,
                "month": month - 1,  # 0-indexed for frontend (Jan=0)
                "return_pct": round(ret, 2),
                "label": f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][month-1]} {year}",
            })

    return results


@router.get("/transactions", response_model=PaginatedTransactions)
async def get_transactions(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    type: str | None = Query(None, alias="type"),
    asset_class: str | None = Query(None),
    start_date: dt.date | None = Query(None),
    end_date: dt.date | None = Query(None),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedTransactions:
    """Paginated, filterable transaction history."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    base = (
        select(Transaction)
        .where(Transaction.client_id == client_id)
        .where(Transaction.portfolio_id == portfolio.id)
    )
    if type:
        base = base.where(Transaction.txn_type == type.upper())
    if asset_class:
        base = base.where(Transaction.asset_class == asset_class.upper())
    if start_date:
        base = base.where(Transaction.txn_date >= start_date)
    if end_date:
        base = base.where(Transaction.txn_date <= end_date)

    total = (await db.execute(
        select(sqlfunc.count()).select_from(base.subquery())
    )).scalar() or 0

    offset = (page - 1) * per_page
    data_stmt = base.order_by(desc(Transaction.txn_date), desc(Transaction.id)).offset(offset).limit(per_page)
    txns = list((await db.execute(data_stmt)).scalars().all())
    total_pages = max(1, (total + per_page - 1) // per_page)

    items = [
        TransactionItem(
            id=t.id, txn_date=t.txn_date, txn_type=t.txn_type, symbol=t.symbol,
            asset_name=t.asset_name, asset_class=t.asset_class,
            quantity=dec4(t.quantity) if t.quantity else None,
            price=dec2(t.price) if t.price else None, amount=dec2(t.amount),
        )
        for t in txns
    ]
    return PaginatedTransactions(
        items=items, total=total, page=page, per_page=per_page, total_pages=total_pages,
    )


