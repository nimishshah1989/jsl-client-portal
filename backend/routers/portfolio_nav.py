"""Portfolio NAV series and growth comparison endpoints.

Split from portfolio.py — these are the cash-flow-adjusted endpoints
that compute benchmark-equivalent values using the virtual units method.
"""

import datetime as dt
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import get_current_user
from backend.models.nav_series import NavSeries
from backend.routers.helpers import (
    FD_RATE,
    date_cutoff,
    dec2,
    get_default_portfolio,
)
from backend.schemas.portfolio import (
    GrowthResponse,
    NavSeriesPoint,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


async def _build_flow_map(
    db: AsyncSession, client_id: int, portfolio_id: int,
) -> dict[dt.date, float]:
    """Build cash flow map from corpus changes in cpp_nav_series.

    Always derived from the NAV series — the authoritative source for invested
    capital, and always current after a NAV upload.  The separate cashflow
    ledger files (cpp_cash_flows) require their own upload step and can be
    stale; using them as primary caused the Nifty benchmark line to stop
    adjusting whenever a new NAV file was uploaded without a matching cashflow
    file.  Corpus changes = actual client invested-capital movements, which is
    exactly the right basis for the virtual-units Nifty comparison.
    """
    all_nav_stmt = (
        select(NavSeries.nav_date, NavSeries.invested_amount)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio_id)
        .order_by(NavSeries.nav_date)
    )
    all_navs = (await db.execute(all_nav_stmt)).all()
    flow_map: dict[dt.date, float] = {}
    prev_corpus = Decimal("0")
    for nav_date, invested in all_navs:
        if invested is not None and invested != prev_corpus:
            delta = float(invested - prev_corpus)
            flow_map[nav_date] = flow_map.get(nav_date, 0.0) + delta
            prev_corpus = invested
    return flow_map


@router.get("/nav-series", response_model=list[NavSeriesPoint])
async def get_nav_series(
    time_range: str = Query("ALL", alias="range"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NavSeriesPoint]:
    """NAV time series with actual portfolio value and Nifty equivalent.

    Left-axis values are in absolute rupees so the client sees real portfolio
    growth rather than a normalised index.

    - nav:           actual current_value from the NAV row
    - benchmark:     invested_amount x (benchmark_today / benchmark_first) —
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
    all_rows = list((await db.execute(stmt)).scalars().all())
    if not all_rows:
        return []

    cutoff = date_cutoff(time_range, all_rows[-1].nav_date)
    flow_map = await _build_flow_map(db, client_id, portfolio.id)

    # ── Pre-seed nifty_units from historical flows before the filter window ──
    # Without this, a 1Y chart starts with nifty_units=0, ignoring all prior
    # inflows and making the benchmark line meaningless for filtered ranges.
    nifty_units = 0.0
    if cutoff is not None:
        for r in all_rows:
            if r.nav_date >= cutoff:
                break
            bench_p = (
                float(r.benchmark_value)
                if r.benchmark_value and r.benchmark_value != Decimal("0")
                else None
            )
            if bench_p and r.nav_date in flow_map:
                nifty_units += flow_map[r.nav_date] / bench_p

        # If no explicit flows found before cutoff, seed from the invested_amount
        # at the last pre-cutoff row (captures clients with a single corpus entry)
        if nifty_units == 0.0:
            for r in reversed(all_rows):
                if r.nav_date >= cutoff:
                    continue
                bench_p = (
                    float(r.benchmark_value)
                    if r.benchmark_value and r.benchmark_value != Decimal("0")
                    else None
                )
                if bench_p and r.invested_amount and float(r.invested_amount) > 0:
                    nifty_units = float(r.invested_amount) / bench_p
                    break

        rows = [r for r in all_rows if r.nav_date >= cutoff]
    else:
        rows = all_rows

    if not rows:
        return []

    first_bench = rows[0].benchmark_value

    # ── Build series points ───────────────────────────────────────────────────
    points: list[NavSeriesPoint] = []
    for idx, row in enumerate(rows):
        bench_price = (
            float(row.benchmark_value)
            if row.benchmark_value and row.benchmark_value != Decimal("0")
            else None
        )

        # Accumulate Nifty units on cash flow dates within the visible window
        if bench_price and row.nav_date in flow_map:
            flow_amt = flow_map[row.nav_date]
            nifty_units += flow_amt / bench_price

        # Safety: if nifty_units is still 0 at the first row (ALL range with no
        # flow data at all), seed from invested_amount so the line isn't flat
        if bench_price and nifty_units == 0.0 and idx == 0:
            initial = float(row.invested_amount) if row.invested_amount else 0.0
            if initial > 0 and row.nav_date not in flow_map:
                nifty_units = initial / bench_price

        # Compute benchmark equivalent value and base-100 index
        bench_equiv: str | None = None
        bench_raw: str | None = None
        if bench_price and first_bench and float(first_bench) != 0:
            if nifty_units > 0:
                bench_equiv = dec2(Decimal(str(nifty_units * bench_price)))
            bench_raw = dec2(row.benchmark_value / first_bench * Decimal("100"))

        # True cash % = (ETF + Cash + Bank) / NAV x 100
        cash: str | None = None
        etf_v = row.etf_value or Decimal("0")
        cash_v = row.cash_value or Decimal("0")
        bank_v = row.bank_balance or Decimal("0")
        total_cash = etf_v + cash_v + bank_v
        if total_cash > 0 and row.nav_value and row.nav_value != Decimal("0"):
            true_pct = total_cash / row.nav_value * Decimal("100")
            cash = dec2(max(Decimal("0"), min(Decimal("100"), true_pct)))
        elif row.cash_pct is not None:
            clamped = max(Decimal("0"), min(Decimal("100"), row.cash_pct))
            cash = dec2(clamped)

        # Include cash flow amount if this date has an inflow/outflow
        cf_str: str | None = None
        if row.nav_date in flow_map:
            cf_str = dec2(Decimal(str(flow_map[row.nav_date])))

        points.append(NavSeriesPoint(
            date=row.nav_date,
            nav=dec2(row.current_value),
            benchmark=bench_equiv,
            invested=dec2(row.invested_amount) if row.invested_amount is not None else None,
            benchmark_raw=bench_raw,
            cash_pct=cash,
            cash_flow=cf_str,
        ))
    return points


@router.get("/growth", response_model=GrowthResponse)
async def get_growth(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GrowthResponse:
    """Growth comparison: portfolio vs Nifty vs FD.

    Nifty and FD values are computed using cash-flow-adjusted logic:
    each inflow "buys" Nifty units / starts an FD at that date's price,
    each outflow "sells" units, so the comparison is fair when clients
    add or withdraw capital over time.
    """
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

    flow_map = await _build_flow_map(db, client_id, portfolio.id)

    # Fetch benchmark prices for Nifty unit calculation
    bench_stmt = (
        select(NavSeries.nav_date, NavSeries.benchmark_value)
        .where(NavSeries.client_id == client_id)
        .where(NavSeries.portfolio_id == portfolio.id)
        .where(NavSeries.benchmark_value.isnot(None))
        .order_by(NavSeries.nav_date)
    )
    bench_rows = (await db.execute(bench_stmt)).all()
    bench_by_date: dict[dt.date, float] = {
        r[0]: float(r[1]) for r in bench_rows if r[1] and r[1] != Decimal("0")
    }

    def _find_bench_price(target_date: dt.date) -> float | None:
        """Find benchmark price on or nearest before target_date."""
        if target_date in bench_by_date:
            return bench_by_date[target_date]
        prior = [d for d in bench_by_date if d <= target_date]
        if prior:
            return bench_by_date[max(prior)]
        return None

    latest_date = last_nav.nav_date
    latest_bench = _find_bench_price(latest_date)

    # Compute Nifty value using virtual units
    nifty_units = 0.0
    fd_value_total = Decimal("0")
    fd_rate_dec = FD_RATE / Decimal("100")

    if flow_map:
        for flow_date in sorted(flow_map.keys()):
            flow_amt = flow_map[flow_date]
            bench_price = _find_bench_price(flow_date)
            if bench_price and bench_price > 0:
                nifty_units += flow_amt / bench_price

            # FD: each inflow/outflow compounds from its date to latest
            flow_days = (latest_date - flow_date).days
            flow_years = Decimal(str(flow_days)) / Decimal("365.25") if flow_days > 0 else Decimal("0")

            # Warn if any single flow implies an unusually long compounding window —
            # this helps catch bad date rows in the NAV file (e.g. misparse → 1990s).
            if float(flow_years) > 20:
                logger.warning(
                    "Growth: client_id=%d flow_date=%s is %.1f years before latest (%s) — "
                    "verify this date is correct in the NAV file.",
                    client_id, flow_date, float(flow_years), latest_date,
                )

            fd_value_total += Decimal(str(flow_amt)) * (
                (Decimal("1") + fd_rate_dec) ** flow_years
            )

        nifty_value = Decimal(str(nifty_units * latest_bench)) if latest_bench and nifty_units > 0 else invested
    else:
        # No flow data at all — simple ratio fallback
        nifty_value = invested
        if (first_nav.benchmark_value and last_nav.benchmark_value
                and first_nav.benchmark_value != Decimal("0")):
            nifty_value = invested * last_nav.benchmark_value / first_nav.benchmark_value
        fd_value_total = invested * ((Decimal("1") + fd_rate_dec) ** years)

    return GrowthResponse(
        invested=dec2(invested), portfolio=dec2(current),
        nifty=dec2(nifty_value), fd=dec2(fd_value_total),
        inception_date=first_nav.nav_date, latest_date=last_nav.nav_date,
        years=dec2(years),
    )
