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
