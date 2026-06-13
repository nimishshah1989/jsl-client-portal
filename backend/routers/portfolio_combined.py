"""Combined portfolio view — aggregates the logged-in client's LIVE portfolios.

All endpoints are scoped to the caller's own client_id (from the JWT); closed
portfolios are excluded. These power the dashboard's "Combined" selection.
"""

import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import get_current_user
from backend.services.audit_service import get_client_ip, get_request_id, log_audit
from backend.services.combined_analytics import (
    get_combined_allocation,
    get_combined_drawdown_series,
    get_combined_growth,
    get_combined_performance_table,
    get_combined_risk_metrics,
    get_combined_xirr,
)
from backend.services.combined_service import (
    get_combined_holdings,
    get_combined_nav_series,
    get_combined_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio/combined", tags=["portfolio-combined"])


async def _audit(db: AsyncSession, request: Request, client_id: int, resource: str) -> None:
    await log_audit(
        db, user_id=client_id, action="VIEW", resource_type=resource,
        ip_address=get_client_ip(request), request_id=get_request_id(request),
        target_client_id=client_id,
    )


@router.get("/summary")
async def combined_summary(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Combined summary cards across the client's live portfolios."""
    client_id: int = user["client_id"]
    data = await get_combined_summary(db, client_id)
    await _audit(db, request, client_id, "PORTFOLIO")
    return data


@router.get("/nav-series")
async def combined_nav_series(
    request: Request,
    time_range: str = Query("ALL", alias="range"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Combined portfolio value vs Nifty equivalent + cash %."""
    client_id: int = user["client_id"]
    data = await get_combined_nav_series(db, client_id, time_range)
    await _audit(db, request, client_id, "NAV")
    return data


@router.get("/holdings")
async def combined_holdings(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Holdings merged by symbol across the client's live portfolios."""
    client_id: int = user["client_id"]
    data = await get_combined_holdings(db, client_id)
    await _audit(db, request, client_id, "HOLDINGS")
    return data


@router.get("/risk-scorecard")
async def combined_risk_scorecard(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Risk metrics on the combined TWR series across live portfolios."""
    client_id: int = user["client_id"]
    data = await get_combined_risk_metrics(db, client_id)
    await _audit(db, request, client_id, "PORTFOLIO")
    return data


@router.get("/performance-table")
async def combined_performance_table(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Multi-period performance on the combined composite index."""
    client_id: int = user["client_id"]
    data = await get_combined_performance_table(db, client_id)
    await _audit(db, request, client_id, "PORTFOLIO")
    return data


@router.get("/drawdown-series")
async def combined_drawdown_series(
    request: Request,
    time_range: str = Query("ALL", alias="range"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Underwater (drawdown) series for the combined portfolio + benchmark."""
    client_id: int = user["client_id"]
    data = await get_combined_drawdown_series(db, client_id, time_range)
    await _audit(db, request, client_id, "PORTFOLIO")
    return data


@router.get("/allocation")
async def combined_allocation(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sector allocation across the client's live portfolios."""
    client_id: int = user["client_id"]
    data = await get_combined_allocation(db, client_id)
    await _audit(db, request, client_id, "HOLDINGS")
    return data


@router.get("/growth")
async def combined_growth(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Combined 'what your money became': portfolio vs Nifty vs FD."""
    client_id: int = user["client_id"]
    data = await get_combined_growth(db, client_id)
    await _audit(db, request, client_id, "PORTFOLIO")
    return data


@router.get("/xirr")
async def combined_xirr(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Combined XIRR from corpus changes across live portfolios."""
    client_id: int = user["client_id"]
    data = await get_combined_xirr(db, client_id)
    await _audit(db, request, client_id, "PORTFOLIO")
    return data
