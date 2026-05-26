"""Data-rights endpoints for the authenticated client (DPDP Act 2023).

Implements three of the data principal's rights under India's Digital
Personal Data Protection Act, 2023:

  * §11 — right of access            → GET  /api/me/export
  * §12 — right to erasure           → POST /api/me/erasure-request
  * §7  — right to withdraw consent  → POST /api/me/consent/withdraw

§13 (grievance redressal) and DPO contact details are NOT covered here —
those require operator-supplied contact info and a separate workflow.

All three endpoints derive ``client_id`` strictly from the authenticated
JWT (``get_current_user`` dependency). No client_id is ever accepted from
the URL or request body. Every operation writes an immutable audit row.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import get_current_user
from backend.models.audit_log import AuditLog
from backend.models.client import Client
from backend.models.consent import ClientConsent
from backend.models.drawdown import DrawdownSeries
from backend.models.holding import Holding
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from backend.models.risk_metric import RiskMetric
from backend.models.transaction import Transaction
from backend.schemas.me import (
    ConsentWithdrawBody,
    ConsentWithdrawResponse,
    ErasureRequestBody,
    ErasureRequestResponse,
)
from backend.services.audit_service import get_client_ip, get_request_id, log_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["me", "dpdp"])


# ── Helpers ───────────────────────────────────────────────────────────


def _row_to_dict(obj: Any) -> dict[str, Any]:
    """Serialize a SQLAlchemy ORM row into a JSON-safe dict.

    Handles ``Decimal``, ``date``, ``datetime`` — the three non-JSON-native
    types that appear in our models. Other column types map directly.
    """
    if obj is None:
        return {}
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name, None)
        if isinstance(val, Decimal):
            out[col.name] = str(val)
        elif isinstance(val, (dt.datetime, dt.date)):
            out[col.name] = val.isoformat()
        else:
            out[col.name] = val
    return out


async def _fetch_all_as_dicts(
    db: AsyncSession, model: Any, client_id: int
) -> list[dict[str, Any]]:
    """Fetch every row for ``model`` scoped to ``client_id`` and serialize it."""
    stmt = select(model).where(model.client_id == client_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_row_to_dict(r) for r in rows]


# ── §11: Right of access ──────────────────────────────────────────────


@router.get("/export")
async def export_my_data(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return ALL personal data held about the authenticated client.

    Served as a downloadable JSON attachment so it lands as a file in the
    client's browser. Every table containing client-scoped rows is dumped;
    the audit log is filtered to entries where the client was either the
    actor (``user_id``) or the subject (``target_client_id``).
    """
    client_id: int = user["client_id"]

    # Profile — read directly so EncryptedString columns are decrypted by SA.
    client_obj = (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client_obj is None:
        raise HTTPException(status_code=404, detail="Client not found")

    profile = {
        "id": client_obj.id,
        "client_code": client_obj.client_code,
        "name": client_obj.name,
        "email": client_obj.email,
        "phone": client_obj.phone,
        "username": client_obj.username,
        "role": client_obj.role,
        "is_active": client_obj.is_active,
        "is_admin": client_obj.is_admin,
        "is_deleted": client_obj.is_deleted,
        "created_at": client_obj.created_at.isoformat() if client_obj.created_at else None,
        "last_login": client_obj.last_login.isoformat() if client_obj.last_login else None,
    }

    portfolios = await _fetch_all_as_dicts(db, Portfolio, client_id)
    nav_series = await _fetch_all_as_dicts(db, NavSeries, client_id)
    transactions = await _fetch_all_as_dicts(db, Transaction, client_id)
    holdings = await _fetch_all_as_dicts(db, Holding, client_id)
    risk_metrics = await _fetch_all_as_dicts(db, RiskMetric, client_id)
    drawdown_series = await _fetch_all_as_dicts(db, DrawdownSeries, client_id)
    consents = await _fetch_all_as_dicts(db, ClientConsent, client_id)

    # Audit log: any row where this client was the actor or the subject.
    audit_stmt = select(AuditLog).where(
        or_(AuditLog.user_id == client_id, AuditLog.target_client_id == client_id)
    )
    audit_rows = (await db.execute(audit_stmt)).scalars().all()
    audit_log = [_row_to_dict(r) for r in audit_rows]

    now = dt.datetime.now(dt.timezone.utc)
    payload: dict[str, Any] = {
        "as_of": now.isoformat(),
        "client_id": client_id,
        "dpdp_section": "§11 right of access",
        "profile": profile,
        "portfolios": portfolios,
        "nav_series": nav_series,
        "transactions": transactions,
        "holdings": holdings,
        "risk_metrics": risk_metrics,
        "drawdown_series": drawdown_series,
        "consents": consents,
        "audit_log": audit_log,
    }

    await log_audit(
        db,
        user_id=client_id,
        action="EXPORT",
        resource_type="CLIENT",
        resource_id=client_id,
        target_client_id=client_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=get_request_id(request),
        details={
            "rows": {
                "portfolios": len(portfolios),
                "nav_series": len(nav_series),
                "transactions": len(transactions),
                "holdings": len(holdings),
                "risk_metrics": len(risk_metrics),
                "drawdown_series": len(drawdown_series),
                "consents": len(consents),
                "audit_log": len(audit_log),
            }
        },
    )

    filename = f"my-data-{client_obj.client_code}-{now.date().isoformat()}.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── §12: Right to erasure ─────────────────────────────────────────────


@router.post(
    "/erasure-request",
    response_model=ErasureRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_erasure(
    request: Request,
    body: ErasureRequestBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ErasureRequestResponse:
    """Log an erasure request and freeze the account.

    This does NOT delete any rows — SEBI mandates 7-year retention of
    transaction/NAV data which overrides the DPDP default. We instead:
      1. Mark the client soft-deleted (``is_deleted = TRUE``, ``deleted_at = NOW``).
      2. Bump ``token_version`` so all live JWTs are invalidated (C5).
      3. Audit-log the request with the optional reason.

    A human operator must then complete the legally-reviewed deletion
    workflow within the 30-day DPDP response window.
    """
    client_id: int = user["client_id"]

    await db.execute(
        update(Client)
        .where(Client.id == client_id)
        .values(
            is_deleted=True,
            deleted_at=dt.datetime.utcnow(),
            token_version=Client.token_version + 1,
        )
    )
    await db.flush()

    await log_audit(
        db,
        user_id=client_id,
        action="ERASURE_REQUEST",
        resource_type="CLIENT",
        resource_id=client_id,
        target_client_id=client_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=get_request_id(request),
        details={"reason": body.reason} if body.reason else None,
    )

    return ErasureRequestResponse(
        status="received",
        message=(
            "Your erasure request has been logged. We will contact you "
            "within 30 days as required by the DPDP Act 2023."
        ),
    )


# ── §7: Right to withdraw consent ─────────────────────────────────────


@router.post("/consent/withdraw", response_model=ConsentWithdrawResponse)
async def withdraw_consent(
    request: Request,
    body: ConsentWithdrawBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsentWithdrawResponse:
    """Revoke a previously-granted consent.

    Finds the most recent active (``revoked_at IS NULL``) consent row for
    this client of the given ``consent_type`` and stamps ``revoked_at``
    with the current timestamp. Returns 404 if no matching active consent
    exists — withdrawing a consent that was never granted is a no-op.
    """
    client_id: int = user["client_id"]
    consent_type = body.consent_type.strip()

    stmt = (
        select(ClientConsent)
        .where(ClientConsent.client_id == client_id)
        .where(ClientConsent.consent_type == consent_type)
        .where(ClientConsent.revoked_at.is_(None))
        .order_by(ClientConsent.id.desc())
        .limit(1)
    )
    consent_row = (await db.execute(stmt)).scalar_one_or_none()
    if consent_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active consent of type '{consent_type}' found for this client",
        )

    withdrawn_at = dt.datetime.utcnow()
    consent_row.revoked_at = withdrawn_at
    await db.flush()

    await log_audit(
        db,
        user_id=client_id,
        action="CONSENT_WITHDRAWN",
        resource_type="CLIENT",
        resource_id=consent_row.id,
        target_client_id=client_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=get_request_id(request),
        details={"consent_type": consent_type, "document_version": consent_row.document_version},
    )

    return ConsentWithdrawResponse(
        status="withdrawn",
        consent_type=consent_type,
        withdrawn_at=withdrawn_at,
    )
