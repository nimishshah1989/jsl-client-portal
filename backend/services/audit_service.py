"""Audit service — log all data access and modifications for SEBI compliance.

M7 — Audit-log integrity hardening:

Audit rows MUST survive a rolled-back business transaction. SEBI compliance
requires that an attempted (but failed) mutation still leaves a trace. To
guarantee this, ``log_audit`` does NOT use the caller's ``AsyncSession`` for
the write — instead it opens a fresh short-lived connection from the engine
and commits in its own transaction (via ``engine.begin()``).

The ``db`` parameter is retained for backwards compatibility with existing
call sites but is intentionally unused for the insert. Future call sites
should pass ``db=None``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_engine
from backend.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def log_audit(
    db: AsyncSession | None,
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
    """Insert an audit log entry on an independent transaction.

    The write is performed on a freshly checked-out connection from the
    shared ``async_engine`` pool and is committed inside its own
    ``engine.begin()`` block. This means the row is durable even if the
    caller's business transaction (which uses a separate ``AsyncSession``)
    rolls back afterward.

    Fire-and-forget: any exception from the audit write is logged and
    swallowed so that audit failures never break the request path.

    NOTE: ``db`` is accepted for backwards compatibility with existing call
    sites but is deliberately NOT used to perform the insert. SEBI integrity
    requires the audit row to outlive a rolled-back business txn.

    Performance note: a fresh connection checkout + commit is slower than
    piggy-backing on the request session, but SEBI compliance outranks the
    extra few milliseconds on hot paths.
    """
    stmt = insert(AuditLog).values(
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
    try:
        async with async_engine.begin() as conn:
            await conn.execute(stmt)
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
