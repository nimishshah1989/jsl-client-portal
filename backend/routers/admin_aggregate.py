"""Admin aggregate portfolio router — firm-wide analytics endpoints.

All endpoints require admin JWT authentication. Returns aggregate metrics
across all active, non-admin client portfolios.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import get_admin_user
from backend.services.aggregate_service import (
    get_aggregate_allocation,
    get_aggregate_monthly_returns,
    get_aggregate_nav_series,
    get_aggregate_performance_table,
    get_aggregate_risk_metrics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/aggregate", tags=["admin-aggregate"])


@router.get("/nav-series")
async def aggregate_nav_series(
    time_range: str = Query("ALL", alias="range"),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Aggregate NAV series (base 100) across all active clients."""
    try:
        return await get_aggregate_nav_series(db, range_filter=time_range)
    except Exception as exc:
        logger.exception("Failed to compute aggregate NAV series")
        raise HTTPException(status_code=500, detail=f"Computation error: {exc}") from exc


@router.get("/performance-table")
async def aggregate_performance_table(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Multi-period performance table for the aggregate portfolio."""
    try:
        return await get_aggregate_performance_table(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate performance table")
        raise HTTPException(status_code=500, detail=f"Computation error: {exc}") from exc


@router.get("/risk-scorecard")
async def aggregate_risk_scorecard(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Risk metrics computed on the aggregate (firm-wide) NAV series."""
    try:
        return await get_aggregate_risk_metrics(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate risk metrics")
        raise HTTPException(status_code=500, detail=f"Computation error: {exc}") from exc


@router.get("/allocation")
async def aggregate_allocation(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sector allocation across all active client holdings."""
    try:
        return await get_aggregate_allocation(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate allocation")
        raise HTTPException(status_code=500, detail=f"Computation error: {exc}") from exc


@router.get("/monthly-returns")
async def aggregate_monthly_returns(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Monthly return heatmap and stats for the aggregate portfolio."""
    try:
        return await get_aggregate_monthly_returns(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate monthly returns")
        raise HTTPException(status_code=500, detail=f"Computation error: {exc}") from exc
