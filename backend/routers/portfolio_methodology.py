"""Portfolio router — XIRR and calculation methodology endpoints."""

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import get_current_user
from backend.models.nav_series import NavSeries
from backend.routers.helpers import dec2, get_default_portfolio, get_latest_risk, opt2
from backend.schemas.portfolio import (
    MethodologyMetric,
    MethodologyResponse,
    XIRRResponse,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/xirr", response_model=XIRRResponse)
async def get_xirr(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> XIRRResponse:
    """XIRR based on actual cash flows (preferred) or corpus changes (fallback)."""
    from sqlalchemy import text as sa_text

    client_id: int = user["client_id"]
    portfolio = await get_default_portfolio(db, client_id)

    # Fetch NAV data for terminal value and fallback
    stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(NavSeries.nav_date)
    )
    navs = list((await db.execute(stmt)).scalars().all())
    if len(navs) < 2:
        raise HTTPException(status_code=404, detail="Insufficient NAV data for XIRR")

    # Try real cash flows from cpp_cash_flows first
    cf_result = await db.execute(
        sa_text("""
            SELECT flow_date, flow_type, amount
            FROM cpp_cash_flows
            WHERE client_id = :cid AND portfolio_id = :pid
            ORDER BY flow_date ASC
        """),
        {"cid": client_id, "pid": portfolio.id},
    )
    cf_rows = cf_result.fetchall()

    cash_flow_source: str
    if cf_rows:
        # Use actual cash flow records
        cash_flow_source = "actual"
        terminal_date = navs[-1].nav_date
        terminal_value = float(navs[-1].current_value)
        cash_flows: list[tuple[dt.date, Decimal]] = []
        for flow_date, flow_type, amount in cf_rows:
            amt = Decimal(str(amount))
            if flow_type == "INFLOW":
                cash_flows.append((flow_date, -amt))  # money in = negative for XIRR
            elif flow_type == "OUTFLOW":
                cash_flows.append((flow_date, amt))  # money out = positive for XIRR
        cash_flows.append((terminal_date, Decimal(str(terminal_value))))
    else:
        # Fallback: infer from corpus changes
        cash_flow_source = "inferred"
        cash_flows = []
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
        cash_flow_source=cash_flow_source,
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

    # Fetch first and last NAV rows for methodology worked examples
    first_nav_stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(NavSeries.nav_date)
        .limit(1)
    )
    last_nav_stmt = (
        select(NavSeries)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .order_by(desc(NavSeries.nav_date))
        .limit(1)
    )
    first_nav = (await db.execute(first_nav_stmt)).scalar_one_or_none()
    last_nav = (await db.execute(last_nav_stmt)).scalar_one_or_none()

    rf = risk.risk_free_rate
    metrics = _build_methodology_metrics(risk, rf, first_nav, last_nav)

    return MethodologyResponse(
        as_of_date=risk.computed_date, risk_free_rate=dec2(rf),
        trading_days_per_year=252, benchmark_name="NIFTY 50", metrics=metrics,
    )


def _build_methodology_metrics(  # noqa: ANN001
    risk, rf: Decimal, first_nav=None, last_nav=None,
) -> dict[str, MethodologyMetric]:
    """Assemble methodology metrics dict from a RiskMetric row and NAV bookends."""
    # Compute actual input values from NAV data
    nav_start = dec2(first_nav.nav_value) if first_nav and first_nav.nav_value else None
    nav_end = dec2(last_nav.nav_value) if last_nav and last_nav.nav_value else None
    inception_days: str | None = None
    if first_nav and last_nav and first_nav.nav_date and last_nav.nav_date:
        inception_days = str((last_nav.nav_date - first_nav.nav_date).days)

    # Derive downside deviation from sortino ratio: dd = (cagr - rf) / sortino
    downside_dev: str | None = None
    if risk.sortino_ratio and risk.cagr and risk.sortino_ratio != Decimal("0"):
        dd_val = (risk.cagr - rf) / risk.sortino_ratio
        downside_dev = dec2(dd_val)

    # Derive daily std from volatility: daily_std = vol / sqrt(252)
    daily_std: str | None = None
    if risk.volatility and risk.volatility != Decimal("0"):
        import math
        ds_val = float(risk.volatility) / math.sqrt(252)
        daily_std = str(Decimal(str(ds_val)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    return {
        "absolute_return": MethodologyMetric(
            value=opt2(risk.absolute_return), benchmark_value=opt2(risk.bench_return_inception),
            inputs={"start_nav": nav_start, "end_nav": nav_end},
        ),
        "cagr": MethodologyMetric(
            value=opt2(risk.cagr), benchmark_value=opt2(risk.bench_cagr_inception),
            inputs={"start_value": nav_start, "end_value": nav_end, "days": inception_days},
        ),
        "xirr": MethodologyMetric(
            value=opt2(risk.xirr),
            inputs={
                "method": "scipy.optimize.brentq",
                "cash_flow_source": "Actual PMS cash flow records (inflows/outflows with exact dates and amounts). Falls back to corpus-change detection from NAV data if cash flow files are not uploaded.",
                "first_date": str(first_nav.nav_date) if first_nav else None,
                "latest_date": str(last_nav.nav_date) if last_nav else None,
                "num_cash_flows": inception_days,
                "total_invested": dec2(last_nav.invested_amount) if last_nav and last_nav.invested_amount else None,
            },
        ),
        "volatility": MethodologyMetric(
            value=opt2(risk.volatility), benchmark_value=opt2(risk.bench_vol_inception),
            inputs={"daily_std": daily_std, "trading_days": "252"},
        ),
        "sharpe_ratio": MethodologyMetric(
            value=opt2(risk.sharpe_ratio), benchmark_value=opt2(risk.bench_sharpe_inception),
            inputs={"portfolio_cagr": opt2(risk.cagr), "risk_free_rate": dec2(rf),
                    "portfolio_volatility": opt2(risk.volatility)},
        ),
        "sortino_ratio": MethodologyMetric(
            value=opt2(risk.sortino_ratio), benchmark_value=opt2(risk.bench_sortino_inception),
            inputs={"portfolio_cagr": opt2(risk.cagr), "risk_free_rate": dec2(rf),
                    "downside_dev": downside_dev},
        ),
        "max_drawdown": MethodologyMetric(
            value=opt2(risk.max_drawdown),
            inputs={"dd_start": str(risk.max_dd_start) if risk.max_dd_start else None,
                    "dd_end": str(risk.max_dd_end) if risk.max_dd_end else None,
                    "dd_recovery": str(risk.max_dd_recovery) if risk.max_dd_recovery else None},
        ),
        "alpha": MethodologyMetric(
            value=opt2(risk.alpha),
            inputs={"port_cagr": opt2(risk.cagr), "bench_cagr": opt2(risk.bench_cagr_inception),
                    "beta": opt2(risk.beta), "risk_free_rate": dec2(rf)},
        ),
        "beta": MethodologyMetric(
            value=opt2(risk.beta), inputs={"formula": "Cov(R_p, R_b) / Var(R_b)"},
        ),
        "information_ratio": MethodologyMetric(
            value=opt2(risk.information_ratio),
            inputs={"port_cagr": opt2(risk.cagr), "bench_cagr": opt2(risk.bench_cagr_inception),
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
        "max_consecutive_loss": MethodologyMetric(
            value=str(risk.max_consecutive_loss) if risk.max_consecutive_loss is not None else None,
            inputs={"win_months": str(risk.win_months) if risk.win_months else None,
                    "loss_months": str(risk.loss_months) if risk.loss_months else None},
        ),
        "avg_cash_held": MethodologyMetric(
            value=opt2(risk.avg_cash_held),
            inputs={"current_cash": opt2(risk.current_cash), "max_cash_held": opt2(risk.max_cash_held)},
        ),
        "max_cash_held": MethodologyMetric(
            value=opt2(risk.max_cash_held),
            inputs={"current_cash": opt2(risk.current_cash), "avg_cash_held": opt2(risk.avg_cash_held)},
        ),
    }
