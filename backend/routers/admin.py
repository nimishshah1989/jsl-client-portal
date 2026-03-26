"""Admin router — file upload (background), preview, risk recompute, upload log,
impersonate, and aggregate analytics dashboard."""

import asyncio
import logging
import os
import tempfile
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import select, desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from backend.database import AsyncSessionLocal, get_db
from backend.middleware.auth_middleware import create_access_token, get_admin_user
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.upload_log import UploadLog
from backend.schemas.admin import UploadLogResponse, UploadPreviewResponse, UploadResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

# In-memory upload job tracker for background processing status
_upload_jobs: dict[str, dict[str, Any]] = {}


def _validate_upload(file: UploadFile) -> str:
    """Validate upload file extension. Returns the extension."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}",
        )
    return ext


async def _run_ingestion_background(
    tmp_path: str,
    ingest_func_name: str,
    file_type: str,
    filename: str,
    admin_id: int,
    job_id: str,
) -> None:
    """Run ingestion in background with its own DB session. Updates job status."""
    try:
        import backend.services.ingestion_service as svc
        ingest_fn = getattr(svc, ingest_func_name)

        def progress_callback(client_index: int, total_clients: int, client_code: str) -> None:
            _upload_jobs[job_id].update({
                "clients_processed": client_index,
                "clients_total": total_clients,
                "current_client": client_code,
            })

        async with AsyncSessionLocal() as db:
            result = await ingest_fn(tmp_path, admin_id, db, progress_callback=progress_callback)
            if hasattr(result, "__dataclass_fields__"):
                from dataclasses import asdict
                result = asdict(result)
            await db.commit()

        _upload_jobs[job_id].update({
            "status": "complete",
            "rows_processed": result.get("rows_processed", 0),
            "rows_failed": result.get("rows_failed", 0),
            "clients_affected": result.get("clients_affected", 0),
            "errors": result.get("errors", []),
        })

    except Exception as exc:
        logger.error("Background %s ingestion failed: %s", file_type, exc, exc_info=True)
        _upload_jobs[job_id].update({
            "status": "failed",
            "errors": [{"stage": "ingestion", "error": str(exc)}],
        })
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _save_and_start_background(
    file: UploadFile,
    ingest_func_name: str,
    file_type: str,
    admin_id: int,
) -> dict[str, Any]:
    """Save upload to temp file and kick off background ingestion.

    Returns immediately with a job_id so the frontend can poll for status.
    """
    _validate_upload(file)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=os.path.splitext(file.filename or "upload")[1]
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    job_id = f"{file_type}_{int(time.time() * 1000)}"
    _upload_jobs[job_id] = {
        "status": "processing",
        "file_type": file_type,
        "filename": file.filename,
        "rows_processed": 0,
        "rows_failed": 0,
        "clients_affected": 0,
        "errors": [],
        "started_at": time.time(),
        "clients_processed": 0,
        "clients_total": 0,
        "current_client": "",
    }

    asyncio.create_task(
        _run_ingestion_background(
            tmp_path, ingest_func_name, file_type,
            file.filename or "unknown", admin_id, job_id,
        )
    )

    return {"job_id": job_id, "status": "processing", "file_type": file_type}


@router.post("/upload-nav")
async def upload_nav(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Upload NAV file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_nav_file", "NAV", admin["client_id"],
    )


@router.post("/upload-transactions")
async def upload_transactions(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Upload transaction file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_transaction_file", "TRANSACTIONS", admin["client_id"],
    )


@router.post("/upload-cashflows")
async def upload_cashflows(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Upload cash flow file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_cashflow_file", "CASHFLOWS", admin["client_id"],
    )


@router.get("/upload-status/{job_id}")
async def get_upload_status(
    job_id: str,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Poll upload job status. Returns processing/complete/failed."""
    job = _upload_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    elapsed = time.time() - job.get("started_at", time.time())
    return {
        "job_id": job_id,
        "status": job["status"],
        "file_type": job["file_type"],
        "filename": job["filename"],
        "rows_processed": job["rows_processed"],
        "rows_failed": job["rows_failed"],
        "clients_affected": job["clients_affected"],
        "errors": job["errors"][:20],
        "elapsed_seconds": round(elapsed, 1),
        "clients_processed": job.get("clients_processed", 0),
        "clients_total": job.get("clients_total", 0),
        "current_client": job.get("current_client", ""),
    }


@router.post("/upload-preview", response_model=UploadPreviewResponse)
async def upload_preview(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> UploadPreviewResponse:
    """Preview first 10 rows of an uploaded file with auto-column mapping."""
    import csv
    import io

    ext = _validate_upload(file)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

    columns: list[str] = []
    sample_rows: list[dict[str, Any]] = []
    row_count = 0

    if ext == ".csv":
        text_content = content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text_content))
        columns = reader.fieldnames or []
        for i, row in enumerate(reader):
            row_count += 1
            if i < 10:
                sample_rows.append(dict(row))
    else:
        columns, sample_rows, row_count = _parse_xlsx_preview(content, ext)

    auto_mapped = _auto_map_columns(columns)
    return UploadPreviewResponse(
        columns=columns, sample_rows=sample_rows, row_count=row_count,
        auto_mapped=auto_mapped,
    )


def _parse_xlsx_preview(
    content: bytes, ext: str
) -> tuple[list[str], list[dict], int]:
    """Read first 10 data rows from xlsx file."""
    import openpyxl

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    columns: list[str] = []
    sample_rows: list[dict[str, Any]] = []
    row_count = 0

    try:
        wb = openpyxl.load_workbook(tmp_path, read_only=True, data_only=True)
        ws = wb.active
        if ws is not None:
            header_done = False
            for row_cells in ws.iter_rows(values_only=True):
                vals = [str(c) if c is not None else "" for c in row_cells]
                if not header_done:
                    columns = vals
                    header_done = True
                    continue
                row_count += 1
                if row_count <= 10:
                    sample_rows.append(
                        {columns[i]: vals[i] for i in range(min(len(columns), len(vals)))}
                    )
            wb.close()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return columns, sample_rows, row_count


def _auto_map_columns(columns: list[str]) -> dict[str, str]:
    """Auto-map known column names to internal field names."""
    known = {
        "ucc": "client_code", "date": "nav_date", "corpus": "invested_amount",
        "nav": "nav_value", "liquidity %": "cash_pct",
        "high water mark": "high_water_mark", "script": "symbol",
        "exch": "exchange", "stno": "settlement_no",
    }
    auto_mapped: dict[str, str] = {}
    for col in columns:
        col_lower = col.strip().lower()
        if col_lower in known:
            auto_mapped[col] = known[col_lower]
    return auto_mapped


@router.post("/recompute-risk")
async def recompute_risk(
    client_id: int | None = None,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger risk recomputation for all or a specific client."""
    try:
        from backend.services.risk_engine import run_risk_engine
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Risk engine not yet implemented") from exc

    if client_id is not None:
        pid = (await db.execute(
            text("SELECT id FROM cpp_portfolios WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        )).scalar()
        if pid is None:
            raise HTTPException(status_code=404, detail=f"No portfolio found for client_id={client_id}")
        await run_risk_engine(client_id, pid, db)
        return {"message": f"Recomputed risk for client_id={client_id}"}

    # Fetch all active client IDs upfront
    stmt = select(Client.id).where(Client.is_active.is_(True))
    client_ids = [row[0] for row in (await db.execute(stmt)).all()]
    count = 0
    errors: list[str] = []
    for cid in client_ids:
        try:
            async with AsyncSessionLocal() as client_db:
                pid = (await client_db.execute(
                    text("SELECT id FROM cpp_portfolios WHERE client_id = :cid LIMIT 1"),
                    {"cid": cid},
                )).scalar()
                if pid is None:
                    continue
                await run_risk_engine(cid, pid, client_db)
                await client_db.commit()
                count += 1
        except Exception as exc:
            logger.error("Risk recompute failed for client_id=%d: %s", cid, exc, exc_info=True)
            errors.append(f"client_id={cid}: {exc!s}")
            continue
    result: dict = {"message": f"Recomputed risk for {count} clients"}
    if errors:
        result["errors"] = errors[:20]
    return result


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
        total_cash: Total cash position across all clients (₹)
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
    response: Response,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issue a JWT for viewing a client's dashboard. Admin only."""
    stmt = select(Client).where(Client.id == client_id)
    client = (await db.execute(stmt)).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    token = create_access_token(client.id, is_admin=False)

    from backend.config import get_settings
    settings = get_settings()
    secure_cookie = "http://" not in settings.CORS_ORIGINS

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/",
        max_age=48 * 3600,
    )

    return {"client_name": client.name, "client_id": client.id}
