"""Portfolio router part 2 — performance table, risk, transactions, XIRR, methodology."""

import datetime as dt
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
    MethodologyMetric,
    MethodologyResponse,
    PaginatedTransactions,
    PerformanceRow,
    RiskScorecardResponse,
    TransactionItem,
    XIRRResponse,
)

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
        avg_cash_held=opt2(risk.avg_cash_held),
        max_cash_held=opt2(risk.max_cash_held),
        current_cash=opt2(risk.current_cash),
        volatility=opt2(risk.volatility),
        sharpe_ratio=opt2(risk.sharpe_ratio),
        sortino_ratio=opt2(risk.sortino_ratio),
    )


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


@router.get("/xirr", response_model=XIRRResponse)
async def get_xirr(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> XIRRResponse:
    """XIRR based on corpus changes detected in NAV series."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(NavSeries.nav_date)
    )
    navs = list((await db.execute(stmt)).scalars().all())
    if len(navs) < 2:
        raise HTTPException(status_code=404, detail="Insufficient NAV data for XIRR")

    cash_flows: list[tuple[dt.date, Decimal]] = []
    prev_corpus = navs[0].invested_amount
    cash_flows.append((navs[0].nav_date, -prev_corpus))

    for nav_row in navs[1:]:
        if nav_row.invested_amount != prev_corpus:
            change = nav_row.invested_amount - prev_corpus
            cash_flows.append((nav_row.nav_date, -change))
            prev_corpus = nav_row.invested_amount

    cash_flows.append((navs[-1].nav_date, navs[-1].current_value))
    xirr_val = _compute_xirr(cash_flows) if len(cash_flows) >= 2 else Decimal("0")

    return XIRRResponse(
        xirr=dec2(xirr_val), cash_flows_count=len(cash_flows),
        first_investment_date=navs[0].nav_date,
        total_invested=dec2(navs[-1].invested_amount),
    )


def _compute_xirr(cash_flows: list[tuple[dt.date, Decimal]]) -> Decimal:
    """Compute XIRR using scipy brentq. Returns percentage."""
    from scipy.optimize import brentq

    dates = [cf[0] for cf in cash_flows]
    amounts = [float(cf[1]) for cf in cash_flows]
    d0 = dates[0]
    day_offsets = [(d - d0).days / 365.0 for d in dates]

    def npv(rate: float) -> float:
        return sum(amt / (1 + rate) ** t for amt, t in zip(amounts, day_offsets))

    try:
        rate = brentq(npv, -0.99, 10.0)
        return Decimal(str(rate * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (ValueError, RuntimeError):
        return Decimal("0")


@router.get("/methodology", response_model=MethodologyResponse)
async def get_methodology(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MethodologyResponse:
    """All metrics with values, formulae inputs for worked examples."""
    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)
    risk = await get_latest_risk(db, client_id, portfolio.id)
    if risk is None:
        raise HTTPException(status_code=404, detail="No risk metrics computed yet")

    rf = risk.risk_free_rate
    metrics = _build_methodology_metrics(risk, rf)

    return MethodologyResponse(
        as_of_date=risk.computed_date, risk_free_rate=dec2(rf),
        trading_days_per_year=252, benchmark_name="NIFTY 50", metrics=metrics,
    )


def _build_methodology_metrics(risk, rf: Decimal) -> dict[str, MethodologyMetric]:  # noqa: ANN001
    """Assemble methodology metrics dict from a RiskMetric row."""
    return {
        "absolute_return": MethodologyMetric(
            value=opt2(risk.absolute_return), benchmark_value=opt2(risk.bench_return_inception),
            inputs={"start_nav": "First NAV value", "end_nav": "Latest NAV value"},
        ),
        "cagr": MethodologyMetric(
            value=opt2(risk.cagr), benchmark_value=opt2(risk.bench_cagr_inception),
            inputs={"start_value": "First NAV", "end_value": "Latest NAV", "days": "Days since inception"},
        ),
        "xirr": MethodologyMetric(
            value=opt2(risk.xirr),
            inputs={"method": "scipy.optimize.brentq", "cash_flow_source": "Corpus changes in NAV file"},
        ),
        "volatility": MethodologyMetric(
            value=opt2(risk.volatility), benchmark_value=opt2(risk.bench_vol_inception),
            inputs={"trading_days": "252", "formula": "std(daily_returns) * sqrt(252) * 100"},
        ),
        "sharpe_ratio": MethodologyMetric(
            value=opt2(risk.sharpe_ratio), benchmark_value=opt2(risk.bench_sharpe_inception),
            inputs={"portfolio_cagr": opt2(risk.cagr), "risk_free_rate": dec2(rf),
                    "portfolio_volatility": opt2(risk.volatility)},
        ),
        "sortino_ratio": MethodologyMetric(
            value=opt2(risk.sortino_ratio), benchmark_value=opt2(risk.bench_sortino_inception),
            inputs={"portfolio_cagr": opt2(risk.cagr), "risk_free_rate": dec2(rf),
                    "downside_deviation": "Computed from negative daily returns"},
        ),
        "max_drawdown": MethodologyMetric(
            value=opt2(risk.max_drawdown),
            inputs={"dd_start": str(risk.max_dd_start) if risk.max_dd_start else None,
                    "dd_end": str(risk.max_dd_end) if risk.max_dd_end else None,
                    "dd_recovery": str(risk.max_dd_recovery) if risk.max_dd_recovery else None},
        ),
        "alpha": MethodologyMetric(
            value=opt2(risk.alpha),
            inputs={"portfolio_cagr": opt2(risk.cagr), "benchmark_cagr": opt2(risk.bench_cagr_inception),
                    "beta": opt2(risk.beta), "risk_free_rate": dec2(rf)},
        ),
        "beta": MethodologyMetric(
            value=opt2(risk.beta), inputs={"formula": "Cov(R_p, R_b) / Var(R_b)"},
        ),
        "information_ratio": MethodologyMetric(
            value=opt2(risk.information_ratio),
            inputs={"portfolio_cagr": opt2(risk.cagr), "benchmark_cagr": opt2(risk.bench_cagr_inception),
                    "tracking_error": opt2(risk.tracking_error)},
        ),
        "tracking_error": MethodologyMetric(
            value=opt2(risk.tracking_error),
            inputs={"formula": "std(R_p - R_b) * sqrt(252) * 100"},
        ),
        "up_capture": MethodologyMetric(
            value=opt2(risk.up_capture),
            inputs={"formula": "mean(port on up days) / mean(bench on up days) * 100"},
        ),
        "down_capture": MethodologyMetric(
            value=opt2(risk.down_capture),
            inputs={"formula": "mean(port on down days) / mean(bench on down days) * 100"},
        ),
        "ulcer_index": MethodologyMetric(
            value=opt2(risk.ulcer_index), inputs={"formula": "sqrt(mean(DD_i^2))"},
        ),
        "monthly_hit_rate": MethodologyMetric(
            value=opt2(risk.monthly_hit_rate),
            inputs={"win_months": str(risk.win_months) if risk.win_months else None,
                    "loss_months": str(risk.loss_months) if risk.loss_months else None},
        ),
        "market_correlation": MethodologyMetric(
            value=opt2(risk.market_correlation),
            inputs={"formula": "Pearson correlation of daily returns"},
        ),
        "avg_cash_held": MethodologyMetric(
            value=opt2(risk.avg_cash_held),
            inputs={"current_cash": opt2(risk.current_cash), "max_cash_held": opt2(risk.max_cash_held)},
        ),
    }
