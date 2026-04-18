"""Audit service — log all data access and modifications for SEBI compliance."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def log_audit(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    target_client_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Insert an audit log entry. Fire-and-forget — never blocks the request."""
    try:
        await db.execute(
            insert(AuditLog).values(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                target_client_id=target_client_id,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                details=details,
            )
        )
    except Exception:
        logger.exception("Failed to write audit log entry")


def get_client_ip(request) -> str:
    """Extract real client IP considering proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


def get_request_id(request) -> str | None:
    """Extract request ID set by RequestIdMiddleware."""
    return getattr(request.state, "request_id", None)
