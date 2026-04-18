"""Admin router — risk recompute, price update, upload log, data status,
dashboard analytics, and client impersonation."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from backend.database import AsyncSessionLocal, get_db
from backend.middleware.auth_middleware import create_access_token, get_admin_user
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.upload_log import UploadLog
from backend.schemas.admin import UploadLogResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/recompute-risk")
async def recompute_risk(
    client_id: int | None = None,
    force: bool = False,
    admin: dict = Depends(get_admin_user),
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
    admin: dict = Depends(get_admin_user),
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
    admin: dict = Depends(get_admin_user),
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
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch live NSE prices and update all holdings."""
    from backend.services.live_prices import update_holdings_prices
    result = await update_holdings_prices(db)
    return result


@router.get("/upload-log", response_model=list[UploadLogResponse])
async def get_upload_log(
    admin: dict = Depends(get_admin_user),
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
    admin: dict = Depends(get_admin_user),
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
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate analytics for the admin dashboard.

    Returns:
        total_aum: Total assets under management (sum of all latest NAV values)
        total_clients: Number of active clients
        blended_cagr: AUM-weighted average CAGR across all clients
        total_cash: Total cash position across all clients
        total_cash_pct: Cash as percentage of total AUM
        top_performers: Top 5 clients by CAGR
        bottom_performers: Bottom 5 clients by CAGR
        avg_max_drawdown: Average max drawdown across clients
        data_as_of: Latest NAV date in the system
    """
    # Total active clients
    client_count = (await db.execute(
        text("SELECT COUNT(*) FROM cpp_clients WHERE is_active = true AND is_admin = false")
    )).scalar() or 0

    # Latest NAV per client (for AUM, cash calculations)
    latest_navs = await db.execute(text("""
        SELECT DISTINCT ON (n.client_id)
            n.client_id, c.name, c.client_code,
            n.nav_value, n.invested_amount, n.nav_date,
            COALESCE(n.etf_value, 0) AS etf_value,
            COALESCE(n.cash_value, 0) AS cash_value,
            COALESCE(n.bank_balance, 0) AS bank_balance,
            n.cash_pct
        FROM cpp_nav_series n
        JOIN cpp_clients c ON c.id = n.client_id
        WHERE c.is_active = true AND c.is_admin = false
        ORDER BY n.client_id, n.nav_date DESC
    """))
    nav_rows = latest_navs.fetchall()

    total_aum = 0.0
    total_invested = 0.0
    total_cash = 0.0
    data_as_of = None

    for row in nav_rows:
        nav_val = float(row.nav_value or 0)
        total_aum += nav_val
        total_invested += float(row.invested_amount or 0)

        # True cash = ETF + ledger cash + bank
        etf = float(row.etf_value or 0)
        cash = float(row.cash_value or 0)
        bank = float(row.bank_balance or 0)
        client_cash = etf + cash + bank
        if client_cash > 0:
            total_cash += client_cash
        elif row.cash_pct and nav_val > 0:
            # Fallback to Liquidity%
            total_cash += nav_val * float(row.cash_pct) / 100

        if data_as_of is None or (row.nav_date and row.nav_date > data_as_of):
            data_as_of = row.nav_date

    total_cash_pct = (total_cash / total_aum * 100) if total_aum > 0 else 0.0
    total_profit = total_aum - total_invested
    total_profit_pct = ((total_aum / total_invested - 1) * 100) if total_invested > 0 else 0.0

    # Latest risk metrics per client for blended CAGR and performer ranking
    risk_rows = await db.execute(text("""
        SELECT DISTINCT ON (r.client_id)
            r.client_id, c.name, c.client_code,
            r.cagr, r.max_drawdown, r.sharpe_ratio, r.xirr,
            r.volatility, r.up_capture, r.down_capture
        FROM cpp_risk_metrics r
        JOIN cpp_clients c ON c.id = r.client_id
        WHERE c.is_active = true AND c.is_admin = false
        ORDER BY r.client_id, r.computed_date DESC
    """))
    risk_data = risk_rows.fetchall()

    # Build AUM + invested lookup for weighting and ranking
    aum_by_client: dict[int, float] = {}
    invested_by_client: dict[int, float] = {}
    for row in nav_rows:
        aum_by_client[row.client_id] = float(row.nav_value or 0)
        invested_by_client[row.client_id] = float(row.invested_amount or 0)

    # Blended (AUM-weighted) metrics
    weighted_cagr_sum = 0.0
    weighted_dd_sum = 0.0
    weighted_sharpe_sum = 0.0
    total_weight = 0.0
    client_metrics: list[dict[str, Any]] = []

    for row in risk_data:
        weight = aum_by_client.get(row.client_id, 0.0)
        cagr_val = float(row.cagr or 0)
        dd_val = float(row.max_drawdown or 0)
        sharpe_val = float(row.sharpe_ratio or 0)

        weighted_cagr_sum += cagr_val * weight
        weighted_dd_sum += dd_val * weight
        weighted_sharpe_sum += sharpe_val * weight
        total_weight += weight

        client_metrics.append({
            "client_id": row.client_id,
            "name": row.name,
            "client_code": row.client_code,
            "cagr": round(cagr_val, 2),
            "max_drawdown": round(dd_val, 2),
            "sharpe_ratio": round(sharpe_val, 2),
            "xirr": round(float(row.xirr or 0), 2),
            "aum": round(weight, 2),
            "invested": round(invested_by_client.get(row.client_id, 0.0), 2),
        })

    blended_cagr = (weighted_cagr_sum / total_weight) if total_weight > 0 else 0.0
    avg_max_dd = (weighted_dd_sum / total_weight) if total_weight > 0 else 0.0
    blended_sharpe = (weighted_sharpe_sum / total_weight) if total_weight > 0 else 0.0

    # Sort for top performers by different criteria
    by_cagr = sorted(client_metrics, key=lambda x: x["cagr"], reverse=True)
    top_performers = by_cagr[:5]
    bottom_performers = by_cagr[-5:] if len(by_cagr) > 5 else []

    by_aum = sorted(client_metrics, key=lambda x: x["aum"], reverse=True)
    top_by_nav = by_aum[:5]

    by_invested = sorted(client_metrics, key=lambda x: x["invested"], reverse=True)
    top_by_invested = by_invested[:5]

    # Upload history summary
    recent_uploads = await db.execute(text("""
        SELECT file_type, filename, rows_processed, clients_affected, uploaded_at
        FROM cpp_upload_log
        ORDER BY uploaded_at DESC
        LIMIT 5
    """))
    upload_history = [
        {
            "file_type": r.file_type,
            "filename": r.filename,
            "rows_processed": r.rows_processed,
            "clients_affected": r.clients_affected,
            "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
        }
        for r in recent_uploads.fetchall()
    ]

    return {
        "total_aum": round(total_aum, 2),
        "total_invested": round(total_invested, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "total_clients": client_count,
        "blended_cagr": round(blended_cagr, 2),
        "blended_sharpe": round(blended_sharpe, 2),
        "total_cash": round(total_cash, 2),
        "total_cash_pct": round(total_cash_pct, 2),
        "avg_max_drawdown": round(avg_max_dd, 2),
        "top_performers": top_performers,
        "top_by_nav": top_by_nav,
        "top_by_invested": top_by_invested,
        "bottom_performers": bottom_performers,
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
        "recent_uploads": upload_history,
    }


@router.post("/impersonate/{client_id}")
async def impersonate_client(
    client_id: int,
    request: Request,
    response: Response,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issue a JWT for viewing a client's dashboard. Admin only. Audit-logged."""
    stmt = select(Client).where(Client.id == client_id)
    client = (await db.execute(stmt)).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    token = create_access_token(client.id, is_admin=False)

    from backend.config import get_settings
    _settings = get_settings()
    secure_cookie = _settings.APP_ENV == "production"

    response.set_cookie(
        key="access_token",
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
