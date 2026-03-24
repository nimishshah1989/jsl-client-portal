"""Admin router — file upload, preview, risk recompute, upload log, impersonate."""

import logging
import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import select, desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from backend.database import get_db
from backend.middleware.auth_middleware import create_access_token, get_admin_user
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.upload_log import UploadLog
from backend.schemas.admin import UploadLogResponse, UploadPreviewResponse, UploadResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


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


async def _save_and_ingest(
    file: UploadFile,
    ingest_func_name: str,
    file_type: str,
    admin_id: int,
    db: AsyncSession,
) -> UploadResponse:
    """Save upload to temp file, run ingestion, log result."""
    _validate_upload(file)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=os.path.splitext(file.filename or "upload")[1]
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        import backend.services.ingestion_service as svc
        ingest_fn = getattr(svc, ingest_func_name)
        result = await ingest_fn(tmp_path, admin_id, db)
        if hasattr(result, '__dataclass_fields__'):
            from dataclasses import asdict
            result = asdict(result)
    except (ImportError, AttributeError):
        result = {
            "rows_processed": 0, "rows_failed": 0, "clients_affected": 0,
            "errors": [{"message": f"{ingest_func_name} not implemented"}],
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{file_type} ingestion failed: {exc!s}",
        ) from exc
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    log = UploadLog(
        uploaded_by=admin_id, file_type=file_type, filename=file.filename,
        rows_processed=result.get("rows_processed", 0),
        rows_failed=result.get("rows_failed", 0),
        clients_affected=result.get("clients_affected", 0),
        errors=result.get("errors", []),
    )
    db.add(log)
    await db.flush()

    return UploadResponse(
        file_type=file_type, filename=file.filename or "unknown",
        rows_processed=result.get("rows_processed", 0),
        rows_failed=result.get("rows_failed", 0),
        clients_affected=result.get("clients_affected", 0),
        errors=result.get("errors", []),
    )


@router.post("/upload-nav", response_model=UploadResponse)
async def upload_nav(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Upload NAV file, parse, ingest, compute risk metrics."""
    return await _save_and_ingest(file, "ingest_nav_file", "NAV", admin["client_id"], db)


@router.post("/upload-transactions", response_model=UploadResponse)
async def upload_transactions(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Upload transaction file, parse, ingest, recompute holdings."""
    return await _save_and_ingest(
        file, "ingest_transaction_file", "TRANSACTIONS", admin["client_id"], db,
    )


@router.post("/upload-cashflows", response_model=UploadResponse)
async def upload_cashflows(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Upload cash flow file, parse, ingest to cpp_cash_flows."""
    return await _save_and_ingest(
        file, "ingest_cashflow_file", "CASHFLOWS", admin["client_id"], db,
    )


@router.post("/upload-preview", response_model=UploadPreviewResponse)
async def upload_preview(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> UploadPreviewResponse:
    """Preview first 10 rows of an uploaded file with auto-column mapping."""
    from typing import Any
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
        text = content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
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
    from typing import Any
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
    from backend.database import AsyncSessionLocal

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
        # Use a separate session per client so one failure doesn't poison the
        # transaction for subsequent clients (PostgreSQL aborted-txn behavior).
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
            logger.error("Risk recompute failed for client_id=%d: %s", cid, exc)
            errors.append(f"client_id={cid}: {exc!s}")
            continue
    result: dict = {"message": f"Recomputed risk for {count} clients"}
    if errors:
        result["errors"] = errors[:20]  # Cap at 20 to avoid huge response
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
    # Last upload timestamp
    last_upload_stmt = (
        select(UploadLog.uploaded_at)
        .order_by(desc(UploadLog.uploaded_at))
        .limit(1)
    )
    last_upload = (await db.execute(last_upload_stmt)).scalar_one_or_none()

    # Latest NAV date in the data (across all clients)
    last_nav_stmt = select(func.max(NavSeries.nav_date))
    last_nav_date = (await db.execute(last_nav_stmt)).scalar_one_or_none()

    return {
        "last_uploaded_at": last_upload.isoformat() if last_upload else None,
        "last_data_date": last_nav_date.isoformat() if last_nav_date else None,
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

    # Create a token scoped to the target client (not admin)
    token = create_access_token(client.id, is_admin=False)

    from backend.config import get_settings
    settings = get_settings()
    secure_cookie = "http://" not in settings.CORS_ORIGINS

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        path="/",
        max_age=48 * 3600,
    )

    return {"client_name": client.name, "client_id": client.id}
