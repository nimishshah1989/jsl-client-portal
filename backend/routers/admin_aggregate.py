"""Admin aggregate portfolio router — firm-wide analytics endpoints.

All endpoints require admin JWT authentication. Returns aggregate metrics
across all active, non-admin client portfolios.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import (
    ROLE_ADMIN_DATA_ENTRY,
    ROLE_ADMIN_READONLY,
    require_role,
)
from backend.services.aggregate_holdings import (
    get_aggregate_allocation,
    get_aggregate_monthly_returns,
)
from backend.services.aggregate_service import (
    get_aggregate_nav_series,
    get_aggregate_performance_table,
    get_aggregate_risk_metrics,
)
from backend.services.benchmark_sweep import (
    DEFAULT_SWEEP_DAYS,
    sweep_benchmark_holes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/aggregate", tags=["admin-aggregate"])

# Separate router so the URL is /api/admin/benchmark/sync — flat under
# /api/admin rather than nested under /api/admin/aggregate.
benchmark_router = APIRouter(prefix="/api/admin/benchmark", tags=["admin-benchmark"])


@benchmark_router.post("/sync")
async def benchmark_sync(
    days: int = Query(
        DEFAULT_SWEEP_DAYS,
        ge=1,
        le=365,
        description="Look-back window (days). Finds any nav_date in this "
        "window with a NULL or 0 benchmark_value and back-fills it from "
        "fie_v3.index_prices (primary) / yfinance (fallback, with write-back "
        "to fie_v3).",
    ),
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Operator-triggered benchmark hole sweep.

    Idempotent — re-running over the same window is a no-op once the holes
    are closed. The same sweep runs automatically every night at 19:30 IST;
    use this endpoint when you want immediate healing (e.g. right after an
    out-of-band NAV upload).
    """
    try:
        result = await sweep_benchmark_holes(db, days=days)
        return result.as_dict()
    except Exception as exc:
        logger.exception("Benchmark sweep failed")
        raise HTTPException(
            status_code=500, detail=f"Benchmark sweep failed: {exc}"
        ) from exc


@router.get("/nav-series")
async def aggregate_nav_series(
    time_range: str = Query("ALL", alias="range"),
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Aggregate NAV series (base 100) across all active clients."""
    try:
        return await get_aggregate_nav_series(db, range_filter=time_range)
    except Exception as exc:
        logger.exception("Failed to compute aggregate NAV series")
        raise HTTPException(status_code=500, detail="Failed to compute aggregate NAV series") from exc


@router.get("/performance-table")
async def aggregate_performance_table(
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Multi-period performance table for the aggregate portfolio."""
    try:
        return await get_aggregate_performance_table(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate performance table")
        raise HTTPException(status_code=500, detail="Failed to compute aggregate performance table") from exc


@router.get("/risk-scorecard")
async def aggregate_risk_scorecard(
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Risk metrics computed on the aggregate (firm-wide) NAV series."""
    try:
        return await get_aggregate_risk_metrics(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate risk metrics")
        raise HTTPException(status_code=500, detail="Failed to compute aggregate risk metrics") from exc


@router.get("/allocation")
async def aggregate_allocation(
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sector allocation across all active client holdings."""
    try:
        return await get_aggregate_allocation(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate allocation")
        raise HTTPException(status_code=500, detail="Failed to compute aggregate allocation") from exc


@router.get("/monthly-returns")
async def aggregate_monthly_returns(
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Monthly return heatmap and stats for the aggregate portfolio."""
    try:
        return await get_aggregate_monthly_returns(db)
    except Exception as exc:
        logger.exception("Failed to compute aggregate monthly returns")
        raise HTTPException(status_code=500, detail="Failed to compute aggregate monthly returns") from exc
