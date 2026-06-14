"""Admin router — risk recompute, price update, upload log, data status,
dashboard analytics, and client impersonation."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select, desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from backend.database import AsyncSessionLocal, get_db
from backend.middleware.auth_middleware import (
    ROLE_ADMIN_DATA_ENTRY,
    ROLE_ADMIN_READONLY,
    create_access_token,
    require_role,
)
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.upload_log import UploadLog
from backend.schemas.admin import UploadLogResponse
from backend.services.admin_analytics import compute_dashboard_analytics

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/recompute-risk")
async def recompute_risk(
    client_id: int | None = None,
    force: bool = False,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger risk recomputation for all or a specific client.

    Optimised: runs up to 5 clients in parallel, skips clients whose
    risk metrics are already current (unless force=True).
    """
    from backend.services.risk_engine import run_risk_engine, run_risk_engine_batch

    if client_id is not None:
        pid = (await db.execute(
            text("SELECT id FROM cpp_portfolios WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        )).scalar()
        if pid is None:
            raise HTTPException(status_code=404, detail=f"No portfolio found for client_id={client_id}")
        await run_risk_engine(client_id, pid, db, force=True)
        await db.commit()
        return {"message": f"Recomputed risk for client_id={client_id}"}

    # Fetch all active client+portfolio pairs
    result = await db.execute(text("""
        SELECT c.id, p.id, c.client_code
        FROM cpp_clients c
        JOIN cpp_portfolios p ON p.client_id = c.id
        WHERE c.is_active = true
        ORDER BY c.client_code
    """))
    pairs = [(r[0], r[1], r[2]) for r in result.fetchall()]

    if not pairs:
        return {"message": "No active clients found"}

    # Run batch with parallel processing (5 concurrent)
    batch_result = await run_risk_engine_batch(
        pairs, AsyncSessionLocal, concurrency=5, force=force,
    )

    return {
        "message": f"Risk recompute: {batch_result['success']} updated, {batch_result['skipped']} skipped (up-to-date), {batch_result['failed']} failed",
        "success": batch_result["success"],
        "skipped": batch_result["skipped"],
        "failed": batch_result["failed"],
        "errors": batch_result["errors"][:20],
    }


@router.post("/recompute-holdings")
async def recompute_holdings_all(
    client_id: int | None = None,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recompute holdings from transactions for all (or one) client.

    Needed after fixing same-day buy+sell ordering in the FIFO engine.
    Rebuilds cpp_holdings from cpp_transactions for every active client.
    """
    from backend.services.ingestion_helpers import recompute_holdings

    if client_id is not None:
        result = await db.execute(text("""
            SELECT c.id, p.id, c.client_code
            FROM cpp_clients c
            JOIN cpp_portfolios p ON p.client_id = c.id
            WHERE c.is_active = true AND c.id = :cid
            ORDER BY c.client_code
        """), {"cid": client_id})
    else:
        result = await db.execute(text("""
            SELECT c.id, p.id, c.client_code
            FROM cpp_clients c
            JOIN cpp_portfolios p ON p.client_id = c.id
            WHERE c.is_active = true
            ORDER BY c.client_code
        """))
    pairs = [(r[0], r[1], r[2]) for r in result.fetchall()]

    if not pairs:
        raise HTTPException(status_code=404, detail="No matching clients")

    success, failed, errors = 0, 0, []
    for cid, pid, code in pairs:
        try:
            count = await recompute_holdings(db, cid, pid)
            await db.commit()
            success += 1
            logger.info("Holdings recomputed: %s → %d positions", code, count)
        except Exception as exc:
            await db.rollback()
            failed += 1
            errors.append({"client": code, "error": str(exc)})
            logger.error("Holdings recompute failed for %s: %s", code, exc)

    return {
        "message": f"Holdings recomputed: {success} ok, {failed} failed",
        "success": success,
        "failed": failed,
        "errors": errors[:20],
    }


@router.post("/deduplicate-symbols")
async def deduplicate_symbols(
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove duplicate transactions caused by alias/canonical symbol pairs.

    The backoffice sometimes records the same trade with both the NSE ticker
    (e.g. ATHERENERG) and the full company name (ATHERENERGYLIMITED) on the
    same row.  Both get ingested, creating phantom double positions.

    This endpoint deletes the alias version of any transaction where an exact
    match (same client, portfolio, date, txn_type, quantity, price) already
    exists under the canonical symbol.  Then recomputes holdings for all
    affected clients.

    Alias → Canonical pairs are taken from the parser's _SYMBOL_OVERRIDES map.
    """
    from backend.services.txn_parser import _SYMBOL_OVERRIDES
    from backend.services.ingestion_helpers import recompute_holdings

    deleted_total = 0
    affected_clients: set[tuple[int, int]] = set()

    for alias, canonical in _SYMBOL_OVERRIDES.items():
        if alias == canonical:
            continue
        # Find alias transactions that have an exact canonical counterpart
        result = await db.execute(text("""
            SELECT a.id, a.client_id, a.portfolio_id
            FROM cpp_transactions a
            WHERE a.symbol = :alias
              AND EXISTS (
                SELECT 1 FROM cpp_transactions b
                WHERE b.client_id    = a.client_id
                  AND b.portfolio_id = a.portfolio_id
                  AND b.txn_date     = a.txn_date
                  AND b.txn_type     = a.txn_type
                  AND b.quantity     = a.quantity
                  AND b.price        = a.price
                  AND b.symbol       = :canonical
              )
        """), {"alias": alias, "canonical": canonical})
        rows = result.fetchall()
        if not rows:
            continue

        ids_to_delete = [r[0] for r in rows]
        for r in rows:
            affected_clients.add((r[1], r[2]))

        await db.execute(
            text("""
                UPDATE cpp_transactions
                SET is_deleted = true,
                    deleted_at = NOW(),
                    deleted_by = :admin_id
                WHERE id = ANY(:ids)
            """),
            {"ids": ids_to_delete, "admin_id": admin["client_id"]},
        )
        deleted_total += len(ids_to_delete)
        logger.info(
            "Soft-deleted %d duplicate '%s' transactions (canonical: %s)",
            len(ids_to_delete), alias, canonical,
        )

    await db.commit()

    # Recompute holdings for all affected clients
    pairs_result = await db.execute(text("""
        SELECT c.id, p.id, c.client_code
        FROM cpp_clients c
        JOIN cpp_portfolios p ON p.client_id = c.id
        WHERE c.is_active = true
        ORDER BY c.client_code
    """))
    all_pairs = {(r[0], r[1]): r[2] for r in pairs_result.fetchall()}

    recomputed, failed, errors = 0, 0, []
    for (cid, pid) in affected_clients:
        code = all_pairs.get((cid, pid), f"client_{cid}")
        try:
            await recompute_holdings(db, cid, pid)
            await db.commit()
            recomputed += 1
        except Exception as exc:
            await db.rollback()
            failed += 1
            errors.append({"client": code, "error": str(exc)})

    return {
        "message": (
            f"Deleted {deleted_total} duplicate alias transactions, "
            f"recomputed {recomputed} clients ({failed} failed)"
        ),
        "deleted_transactions": deleted_total,
        "clients_recomputed": recomputed,
        "clients_failed": failed,
        "errors": errors,
    }


@router.post("/update-prices")
async def update_prices(
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch live NSE prices and update all holdings."""
    from backend.services.live_prices import update_holdings_prices
    result = await update_holdings_prices(db)
    return result


@router.get("/upload-log", response_model=list[UploadLogResponse])
async def get_upload_log(
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> list[UploadLogResponse]:
    """List recent upload history."""
    stmt = select(UploadLog).order_by(desc(UploadLog.uploaded_at)).limit(100)
    logs = list((await db.execute(stmt)).scalars().all())
    return [
        UploadLogResponse(
            id=log.id, uploaded_by=log.uploaded_by, file_type=log.file_type,
            filename=log.filename, rows_processed=log.rows_processed,
            rows_failed=log.rows_failed, clients_affected=log.clients_affected,
            errors=log.errors if isinstance(log.errors, list) else [],
            uploaded_at=log.uploaded_at,
        )
        for log in logs
    ]


@router.get("/data-status")
async def data_status(
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return last upload timestamp and latest NAV date across all clients."""
    last_upload_stmt = (
        select(UploadLog.uploaded_at)
        .order_by(desc(UploadLog.uploaded_at))
        .limit(1)
    )
    last_upload = (await db.execute(last_upload_stmt)).scalar_one_or_none()

    last_nav_stmt = select(func.max(NavSeries.nav_date))
    last_nav_date = (await db.execute(last_nav_stmt)).scalar_one_or_none()

    return {
        "last_uploaded_at": last_upload.isoformat() if last_upload else None,
        "last_data_date": last_nav_date.isoformat() if last_nav_date else None,
    }


@router.get("/dashboard-analytics")
async def dashboard_analytics(
    strategy: str = Query("COMBINED"),
    include_inactive: bool = Query(False),
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate analytics for the admin dashboard, scoped to a strategy.

    Strategy is COMBINED / LEADERS / PASSIVE / IND11; closed accounts are always
    excluded. Aggregation is per-portfolio (not per-client), so a unified client's
    sleeves all count post-merge — see
    :func:`backend.services.admin_analytics.compute_dashboard_analytics`.
    """
    return await compute_dashboard_analytics(db, strategy, include_inactive)


@router.post("/impersonate/{client_id}")
async def impersonate_client(
    client_id: int,
    request: Request,
    response: Response,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issue a JWT for viewing a client's dashboard. Admin only. Audit-logged.

    Writes a SEPARATE ``impersonation_token`` cookie so the admin's
    ``access_token`` is never overwritten. Portfolio routes prefer the
    impersonation cookie; admin routes ignore it. See
    ``backend.middleware.auth_middleware`` for the read-side invariant.

    Soft-deleted clients are 404'd (M9) — the impersonation flow must not
    grant access to a deleted account even if the admin still has its id.
    """
    stmt = select(Client).where(
        Client.id == client_id,
        Client.is_deleted.is_(False),
    )
    client = (await db.execute(stmt)).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    token = create_access_token(client.id, is_admin=False, token_version=client.token_version)

    from backend.config import get_settings
    _settings = get_settings()
    secure_cookie = _settings.APP_ENV == "production"

    response.set_cookie(
        key="impersonation_token",
        value=token,
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/",
        max_age=_settings.JWT_EXPIRY_HOURS * 3600,
    )

    from backend.services.audit_service import get_client_ip, get_request_id, log_audit
    await log_audit(
        db, user_id=admin["client_id"], action="IMPERSONATE",
        resource_type="CLIENT", resource_id=client_id,
        target_client_id=client_id,
        ip_address=get_client_ip(request),
        request_id=get_request_id(request),
        details={"admin_id": admin["client_id"], "target_client": client.client_code},
    )

    return {"client_name": client.name, "client_id": client.id}


@router.post("/stop-impersonate")
async def stop_impersonate(
    request: Request,
    response: Response,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """End an impersonation session.

    Deletes ONLY the ``impersonation_token`` cookie — the admin's
    ``access_token`` remains untouched so the admin returns to a clean admin
    session. Audit-logged.
    """
    from backend.config import get_settings
    _settings = get_settings()
    secure_cookie = _settings.APP_ENV == "production"

    response.delete_cookie(
        key="impersonation_token",
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/",
    )

    from backend.services.audit_service import get_client_ip, get_request_id, log_audit
    await log_audit(
        db, user_id=admin["client_id"], action="IMPERSONATE_END",
        resource_type="CLIENT",
        ip_address=get_client_ip(request),
        request_id=get_request_id(request),
        details={"admin_id": admin["client_id"]},
    )

    return {"success": True}
