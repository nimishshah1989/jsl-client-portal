"""Shared helpers for portfolio routers — formatting, common queries."""

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.portfolio import Portfolio
from backend.models.risk_metric import RiskMetric

RANGE_DAYS: dict[str, int | None] = {
    "1M": 30, "3M": 91, "6M": 182, "1Y": 365,
    "2Y": 730, "3Y": 1095, "5Y": 1826, "ALL": None,
}

FD_RATE = Decimal("7.00")


def dec2(val: Decimal | None) -> str:
    """Format Decimal to string with 2 decimal places, or '0.00'."""
    if val is None:
        return "0.00"
    return str(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dec4(val: Decimal | None) -> str:
    """Format Decimal to string with 4 decimal places."""
    if val is None:
        return "0.0000"
    return str(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def opt2(val: Decimal | None) -> str | None:
    """Format Decimal to 2dp string, or None if input is None."""
    if val is None:
        return None
    return dec2(val)


def date_cutoff(range_key: str, latest_date: dt.date) -> dt.date | None:
    """Return the start date for a given range, or None for ALL."""
    days = RANGE_DAYS.get(range_key.upper())
    if days is None:
        return None
    return latest_date - dt.timedelta(days=days)


async def get_default_portfolio(db: AsyncSession, client_id: int) -> Portfolio:
    """Fetch the first active portfolio for a client, or 404."""
    stmt = (
        select(Portfolio)
        .where(Portfolio.client_id == client_id)
        .where(Portfolio.status == "active")
        .limit(1)
    )
    result = await db.execute(stmt)
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active portfolio found for this client",
        )
    return portfolio


async def get_latest_risk(
    db: AsyncSession, client_id: int, portfolio_id: int
) -> RiskMetric | None:
    """Fetch the most recent risk metrics row for a client portfolio."""
    stmt = (
        select(RiskMetric)
        .where(RiskMetric.client_id == client_id)
        .where(RiskMetric.portfolio_id == portfolio_id)
        .order_by(desc(RiskMetric.computed_date))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
